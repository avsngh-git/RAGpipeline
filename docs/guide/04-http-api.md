# 4. HTTP API

The API is a FastAPI application, versioned under `/v1`. FastAPI also serves the generated OpenAPI schema at `/openapi.json` and interactive documentation at `/docs`; both list every request and response field.

Examples use the CPU demo on port 8000. The owner's host development API uses port 8001.

```bash
BASE=http://127.0.0.1:8000
KEY=$(cat demo-data/api-key)
AUTH="Authorization: Bearer $KEY"
```

## Endpoints

| Method | Path | Scope | Rate-limit class | Purpose |
| --- | --- | --- | --- | --- |
| `GET` | `/health` | none | — | Process liveness |
| `GET` | `/ready` | none | — | Dependency readiness |
| `GET` | `/metrics` | none | — | Prometheus metrics |
| `GET` | `/` | none | — | The web page |
| `GET` | `/v1/serving` | `read` | run read | The snapshot, retrieval profile and generation this server answers from |
| `POST` | `/v1/search` | `read` | search | Ranked papers with supporting evidence |
| `POST` | `/v1/evidence/search` | `read` | search | Ranked passages and table excerpts |
| `GET` | `/v1/papers/{paper_id}` | `read` | paper read | Paper metadata and selected document version |
| `GET` | `/v1/papers/{paper_id}/references` | `read` | paper read | Papers this paper cites (stored, one hop) |
| `GET` | `/v1/papers/{paper_id}/citations` | `read` | paper read | Papers in the corpus that cite this paper |
| `POST` | `/v1/research` | `research` | research run creation | Start a research run |
| `GET` | `/v1/research/{run_id}` | `read` | run read | Read a run you started |
| `POST` | `/v1/collections/{collection_id}/ingest` | `ingest` | ingestion | Request ingestion of papers |
| `GET` | `/v1/collections/{collection_id}/ingest/{request_id}` | `ingest` | run read | Read an ingestion request |

`find_related_papers` is available to the agent and over MCP, but has no HTTP route. The specification's `POST /v1/collections` (create a collection) is not implemented; collections are created with the CLI.

## Authentication

Send an API key as a bearer token: `Authorization: Bearer <key>`. Never put a key in a URL. Keys are created with `research-keys` ([CLI](06-cli.md#research-keys)) and stored only as SHA-256 hashes.

| Scope | Allows |
| --- | --- |
| `read` | Search, evidence search, papers, citations, serving identity, reading your own runs |
| `research` | Starting research runs |
| `ingest` | Collection ingestion and its status; lets a `deep_research` run add papers |
| `admin` | Everything, including reading other principals' runs |

A run belongs to the principal that started it. Another principal gets `404` for it, not `403`, so run IDs cannot be probed.

For local development only, `RESEARCH_PLATFORM_AUTH_MODE=disabled` makes every request run as principal `local` with all scopes. Startup refuses this in `production` or when `RESEARCH_PLATFORM_API_BIND_HOST` is not a loopback address. See the [authentication guide](../operations/authentication.md).

## Health and readiness

```bash
curl $BASE/health        # {"status":"ok"}
curl -i $BASE/ready      # 200 {"status":"ready","dependencies":{...}} or 503 "not_ready"
```

`/health` only says the process is alive. `/ready` checks PostgreSQL and Qdrant and reports whether the search and research runtimes initialized; each dependency is `ok` or `unavailable`, without connection details.

## Serving identity

Search requests must name the snapshot and retrieval profile they expect, so a client cannot silently get results from a different corpus. Ask the server first:

```bash
curl -s -H "$AUTH" $BASE/v1/serving
# {"snapshot_id":"4b11fab3-...","retrieval_profile_id":"sha256:...","generation":1}
SNAPSHOT=4b11fab3-d4a5-4e7a-a58e-8654accf2c6c
PROFILE=sha256:...    # copy from the response
```

A request for another snapshot fails with `incompatible_snapshot`.

## Search papers

```bash
curl -s -X POST $BASE/v1/search -H "$AUTH" -H 'Content-Type: application/json' -d '{
  "query": "cross-encoder reranking for retrieval-augmented generation",
  "snapshot_id": "'$SNAPSHOT'",
  "retrieval_profile_id": "'$PROFILE'",
  "mode": "reranked",
  "filters": {"year_from": 2022},
  "limit": 10
}'
```

| Field | Rules |
| --- | --- |
| `query` | Required; at most 2,000 characters |
| `snapshot_id`, `retrieval_profile_id` | Required; must match `/v1/serving` |
| `mode` | `lexical`, `dense`, `hybrid` or `reranked` |
| `limit` | 1 to 50; default 10 |
| `filters.year_from`, `filters.year_to` | Inclusive publication-year range |
| `filters.paper_ids` | Up to 100 OpenAlex IDs (`W` followed by digits) |
| `filters.evidence_kinds` | Evidence search only: `text`, `table`, `table_row_group`, `caption`, `figure`, `equation` |
| `filters.document_version_kinds` | `published`, `preprint`, `other`, `unknown` |

Unknown fields are rejected. Each paper hit carries the paper's metadata, component scores and up to five supporting evidence hits.

## Search evidence

`POST /v1/evidence/search` takes the same body and returns evidence hits. Each hit includes:

- its chunk, evidence unit, document and paper IDs;
- the `kind` and text (for tables: caption, units, footnotes, header rows and cells with their row and column headers);
- a source span: section ordinal, character offsets, heading path, and page with bounding box;
- `component_scores` with the `lexical`, `dense`, `fusion` and `reranker` rank and score.

Evidence text is returned only when the server runs with `RESEARCH_PLATFORM_EVIDENCE_ACCESS_PROFILE=trusted_private_local`; otherwise the route returns `403 permission_denied`. The Compose demo enables it because the bundle contains only display-cleared CC BY passages.

### Reading a search response

Both search responses share these fields:

| Field | Meaning |
| --- | --- |
| `eligible_count` | How many records passed the filters, before ranking limits |
| `result_status` | `ranked_candidates`, `no_eligible_records` (filters excluded everything) or `no_candidates_returned` (eligible records exist, but none ranked) |
| `ranking_interpretation` | Always `ranking_only`: scores order results; they are **not** relevance probabilities, and no cutoff is applied |
| `requested_mode`, `effective_mode` | They differ when a stage fell back, for example `reranked` → `hybrid` if reranking failed |
| `warnings` | Why the effective mode differs, or other notes |
| `truncated`, `omitted_count` | Whether the evidence budget cut results |
| `effective_configuration_id` | The hash of the exact settings used |

## Papers and citations

```bash
PAPER_ID=W...     # an OpenAlex ID from a search hit
curl -s -H "$AUTH" "$BASE/v1/papers/$PAPER_ID?snapshot_id=$SNAPSHOT"
curl -s -H "$AUTH" "$BASE/v1/papers/$PAPER_ID/references?snapshot_id=$SNAPSHOT&limit=20"
curl -s -H "$AUTH" "$BASE/v1/papers/$PAPER_ID/citations?snapshot_id=$SNAPSHOT&limit=20&cursor=$NEXT"
```

Paper reads return metadata only: title, year, availability and the selected document version, but no passage or abstract text. Citation pages return one-hop edges stored in PostgreSQL. Each endpoint has a `status`: `in_snapshot`, `outside_snapshot` (known paper, not in this corpus) or `unresolved` (only an external identifier such as a DOI is known). `limit` is 1 to 100 (default 20). Follow `next_cursor` while `has_more` is true; cursors are tamper-checked. `/citations` lists only *locally observed* incoming edges; it does not query global citation counts.

## Research runs

Start a run:

```bash
curl -s -X POST $BASE/v1/research -H "$AUTH" -H 'Content-Type: application/json' -d '{
  "question": "What evidence suggests that reranking improves retrieval-augmented generation?",
  "mode": "deep_research",
  "filters": {"year_from": 2022}
}'
```

| Field | Rules |
| --- | --- |
| `question` | 3 to 2,000 characters |
| `mode` | `quick` or `deep_research` |
| `snapshot_id` | Optional; must be the served snapshot if given |
| `filters.year_from`, `filters.year_to` | Optional inclusive range, 1900 to 2100 |

The response is `202 Accepted` with the run view in status `queued`. Poll it:

```bash
curl -s -H "$AUTH" $BASE/v1/research/$RUN_ID
```

A completed run view looks like this (abridged):

```json
{
  "run_id": "0de45d17-...",
  "status": "completed",
  "mode": "quick",
  "question": "...",
  "answer": "...",
  "answer_outcome": "partially_supported",
  "claims": [
    {
      "claim_id": "claim-1",
      "text": "Reranking the fused candidates raised evidence nDCG@10 ...",
      "quote": "the exact sentence copied from the cited passage",
      "evidence": [{"handle": "E3", "chunk_id": "...", "paper_id": "W..."}],
      "support": "supported"
    }
  ],
  "papers": [{"paper_id": "W...", "title": "...", "publication_year": 2023}],
  "uningested_candidates": [],
  "provenance": {
    "snapshot_id": "...", "generation": 1, "retrieval_profile_id": "sha256:...",
    "configuration_id": "sha256:...", "code_revision": "...",
    "model": {"...": "..."}, "thinking": {"plan": true, "evaluate": true, "synthesize": true},
    "prompt_versions": {"...": "..."}, "budgets": {"max_tool_calls": 12, "...": "..."},
    "trace_id": "...", "provenance_version": 2
  },
  "usage": {"plan_rounds": 0, "tool_calls": 2, "model_calls": 1, "active_seconds": 214.7,
            "resumes": 0, "rejected_claims": 1, "unsupported_claims": 0},
  "created_at": "...", "completed_at": "..."
}
```

A failed run has `status: "failed"`, a `failure_category` and no `answer_outcome`. [Research runs](10-research-runs.md) explains every field.

## Ingestion

```bash
curl -s -X POST $BASE/v1/collections/$COLLECTION_ID/ingest -H "$AUTH" \
  -H 'Content-Type: application/json' -d '{"paper_ids": ["W..."]}'
curl -s -H "$AUTH" $BASE/v1/collections/$COLLECTION_ID/ingest/$REQUEST_ID
```

At most 20 papers per request. Code decides each paper against the membership policy and returns `accepted` or `refused` with a reason. Accepted papers form one queued request, which `research-worker` processes. Polling returns per-paper outcomes and, once published, the new generation number. The worker must be running with `RESEARCH_PLATFORM_INGESTION_HANDLER=online`; see [Corpus and ingestion](08-corpus-and-ingestion.md#online-ingestion).

## Errors

Every handled error uses one envelope, and the request ID is also returned in the `X-Request-ID` header:

```json
{"error": {"code": "insufficient_scope", "message": "...", "request_id": "..."}}
```

| Status | Codes |
| --- | --- |
| 400 | `invalid_request` (unparseable body) |
| 401 | `authentication_required`, `invalid_api_key` |
| 403 | `insufficient_scope`, `permission_denied` |
| 404 | `not_found` (including runs owned by someone else) |
| 405 | `method_not_allowed` |
| 409 | `incompatible_snapshot` (the request names a snapshot this server does not serve) |
| 422 | `invalid_request` for validation failures. The body does not yet name the invalid field ([#253](https://github.com/avsngh-git/RAGpipeline/issues/253)) |
| 413 | `request_too_large` (body above 64 KiB) |
| 429 | `rate_limited`, `too_many_active_runs`, with `Retry-After` |
| 500 | `internal_error` (no exception text or stack trace is exposed) |
| 503 | `authentication_unavailable`, or a runtime that is not ready |

A caller-supplied `X-Request-ID` is kept if it is non-empty and reasonably short; otherwise the API generates a UUID.

## Limits

| Limit | Default | Variable |
| --- | --- | --- |
| Research runs started | 20 per hour per principal | `RESEARCH_PLATFORM_RATE_LIMIT_RESEARCH_CREATE` |
| Searches | 60 per minute | `RESEARCH_PLATFORM_RATE_LIMIT_SEARCH` |
| Paper and citation reads | 120 per minute | `RESEARCH_PLATFORM_RATE_LIMIT_PAPER_READ` |
| Run reads | 120 per minute | `RESEARCH_PLATFORM_RATE_LIMIT_RUN_READ` |
| Ingestion | 10 per hour | `RESEARCH_PLATFORM_RATE_LIMIT_INGEST` |
| Active runs per principal | 2 | `RESEARCH_PLATFORM_MAX_ACTIVE_RUNS_PER_KEY` |
| Request body | 65,536 bytes | `RESEARCH_PLATFORM_MAX_BODY_BYTES` |

Rate limits are in-memory token buckets, written as `capacity/seconds` (for example `60/60`). They reset when the API restarts and are not shared between processes.

Next: [MCP server](05-mcp.md).
