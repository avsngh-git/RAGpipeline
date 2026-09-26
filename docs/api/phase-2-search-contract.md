# Phase 2 search contract

Status: P2-02 implementation contract; local private API only. Limits are
provisional defaults for the laptop pilot and may be tuned from measured workload
evidence without changing the retrieval policy. This document specifies schemas
and service boundaries; HTTP routes are delivered later in P2-16.

## Operations

| Operation | Input | Result | Evidence text |
| --- | --- | --- | --- |
| Paper search | Query, finalized snapshot, retrieval profile, mode, filters, result limit | Ranked `PaperHit` values with bounded supporting `EvidenceHit` values | Included only in supporting evidence when source inspection is permitted |
| Evidence search | Same common request fields | Ranked source-linked `EvidenceHit` values | Included only when source inspection is permitted |
| Paper metadata | Metadata query and compatible filters | `PaperMetadataHit` values | Not present in the result schema |

Paper metadata cannot apply an evidence-kind filter. It has a separate result
type with no passage, chunk-summary, or debug-text field, so an adapter cannot
leak retained passages through this operation.

## Request fields

| Field | Type / default | Behavior |
| --- | --- | --- |
| `query` | Nonblank string; at most 2,000 characters | Trim surrounding whitespace; reject empty or oversized values |
| `snapshot_id` | UUID | Required; service resolves this exact snapshot |
| `retrieval_profile_id` | `sha256:` plus 64 lowercase hex characters | Required; service verifies compatibility with the snapshot |
| `mode` | `lexical`, `dense`, `hybrid`, or `reranked` | Required; unknown modes are invalid |
| `filters` | Object; all fields optional | Unknown fields are invalid |
| `limit` | Integer; default 10, range 1–50 | Bounds returned papers/evidence hits |

Provisional work bounds are serialized by `SearchLimits.to_dict()`:

| Limit | Default | Maximum |
| --- | ---: | ---: |
| Query characters | 2,000 | 2,000 |
| Returned results | 10 | 50 |
| Internal candidate pool | 50 | 200 |
| Supporting evidence per paper | 3 | 5 |
| Paper IDs in one filter | — | 100 |
| Request timeout | 30 seconds | 30 seconds |

Internal candidate and per-paper limits are server configuration, not client
controls. They must be part of the effective configuration identity used in a
search response. The pilot may revise these values after recording latency and
resource use.

## Filters

| Field | Values | Semantics |
| --- | --- | --- |
| `year_from`, `year_to` | Nonnegative integers | Inclusive bounds; lower bound cannot exceed upper bound |
| `paper_ids` | 1–100 canonical OpenAlex work IDs (`W` followed by digits) | OR within this list |
| `evidence_kinds` | `text`, `table`, `table_row_group`, `caption`, `figure`, `equation` | OR within list; evidence search only |
| `document_version_kinds` | `published`, `preprint`, `other`, `unknown` | OR within list |

Different filter fields combine with AND. Missing metadata fails any filter that
requires it. Duplicate values and unknown fields are rejected. Filters are applied
consistently before component candidate limits so lexical, dense, fused, and
reranked modes see the same eligible set.

## Result fields and provenance

`PaperHit` contains a canonical paper ID, title/year, rank, component scores, and at
most five supporting evidence hits (three by default). Each `EvidenceHit` retains
the chunk ID, source evidence IDs, paper ID, document ID and version, version kind,
extraction ID, optional chunking configuration ID, evidence kind, source location,
rank, component scores, and text when private inspection is allowed.

Each response includes `request_id`, resolved `snapshot_id`, retrieval profile and
effective configuration identities, requested and effective modes, warnings,
`truncated`, `omitted_count`, and ranked hits. Component scores are raw method
scores/ranks, not calibrated probabilities; a missing component is `null`. A
fallback must report the effective mode and a warning.

## Access boundary

`RESEARCH_PLATFORM_EVIDENCE_ACCESS_PROFILE` is server-owned and accepts only
`disabled` (the default) or `trusted_private_local`. Neither request fields nor
forwarded headers can select or elevate the profile. Private inspection requires
both the artifact association and its reviewed permission evidence to permit
storage and indexing. Public passage display stays unavailable throughout Phase 2,
even when recorded display flags are true.

The reusable service policy enforces these rights before reading or returning
passage text. Metadata-only result schemas contain no evidence text. Search route
adapters must not add passage content to metadata summaries, diagnostics, or error
responses.

## Error categories

| Category | HTTP mapping when routes are added | Examples |
| --- | ---: | --- |
| `invalid_request` | 400 | Blank/oversized query, malformed ID, unknown field/mode, invalid range, unsupported filter |
| `access_denied` | 403 | Private inspection disabled or source storage/index permission absent |
| `resource_not_found` | 404 | Snapshot or retrieval profile does not exist |
| `incompatible_configuration` | 409 | Profile does not match the requested snapshot/evidence representation |
| `retrieval_unavailable` | 503 | Required index, model, or backing service is unavailable |
| `deadline_exceeded` | 504 | The bounded request timeout expires |

Responses must not expose SQL, local paths, secrets, passage text in metadata-only
operations, or internal exception details. Stable error codes and request IDs are
returned; implementation-specific diagnostics stay in server logs.
