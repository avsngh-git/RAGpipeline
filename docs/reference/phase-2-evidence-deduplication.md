# Phase 2 evidence deduplication

Policy ID: `evidence-deduplication-v1`

## Scope

The evidence selector processes ranked `EvidenceHit` values against their source
`EvidenceUnit` records. It removes exact chunk repeats and conservatively removes
a hit only when all of its resolved source coverage is already represented by
higher-ranked retained hits. It does not compare passage wording or infer semantic
equivalence.

## Identity and overlap rules

- Candidates have unique positive ranks and are considered by rank, then chunk ID.
- A repeated chunk ID is removed only when its source-bearing payload agrees with
  the first occurrence. Conflicting payload under one chunk ID is an error. Rank and
  component scores may differ because they describe retrieval, not source identity.
- Source overlap requires each referenced source ID to resolve to an evidence unit
  with the same document and extraction as the hit. Unknown or unsupported source
  locations are reported as unresolved and prevent source-coverage removal.
- Text uses half-open character intervals within one extraction and section.
  Coverage from multiple retained intervals can cover one candidate; partial
  overlap preserves the candidate.
- Tables use half-open body-row intervals within one extraction and table.
  Repeated header rows are context, not body coverage. A complete row group can cover
  a cell segment in one of its body rows. Cell segments cannot claim to cover an
  entire row group.
- Oversized-cell segments use half-open token intervals within one extraction,
  table, row and column. Partial segments remain available.
- Equal wording, offsets, or table coordinates from different extractions do not
  imply the same source. Different papers are never merged by text similarity.
- Every omission records its reason, original rank, source IDs and retained hit IDs
  that overlap its covered source. An exact duplicate whose first occurrence was
  itself source-subsumed points through to the retained covering hits.

## Limits

Text offsets are comparable only within the same extraction and section. Table
coordinates are comparable only within the same extraction and table. The policy
keeps evidence when source mapping is incomplete, favoring possible repetition over
discarding source content. It does not deduplicate semantically equivalent findings,
claims, or results across papers.

Implementation: `src/research_platform/search/evidence_deduplication.py`.
Synthetic behavior: `tests/test_evidence_deduplication.py`.
