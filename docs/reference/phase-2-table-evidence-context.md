# Phase 2 structured table evidence

Policy ID: `table-evidence-context-v1`

A selected table evidence hit may carry an optional `table_context`. The hit keeps
its existing `text` unchanged as the readable rendering of the indexed evidence
unit. Ingestion chunks table rows and oversized cells under the selected
`ChunkingConfig.maximum_text_tokens`; this policy adds structure without clipping
that source text or substituting a new flattened rendering.

## Structured fields

- The context identifies the table ordinal and total header-row count, caption, units,
  footnotes, and source evidence IDs.
- Row-group hits include only their selected body rows plus the table's header rows.
  Each returned cell preserves row/column coordinates, exact value, merged-cell range,
  explicit header references, and resolved row/column header labels.
- Oversized-cell hits include only the selected value segment, its half-open token
  interval, and the header cells referenced by that segment. The full table is not
  copied into a cell result.
- Missing grid positions are not fabricated as empty cells. Table source location
  remains on the parent evidence hit, and source evidence IDs identify the extracted
  units used to resolve the structure.
- A hit spanning multiple source units may combine rows or segments from one table
  only. Unknown IDs, cross-document/extraction units, stale header counts, invalid
  ranges, and cells that cannot be resolved against the source table fail closed.

The `EvidenceHit.text` field is the bounded readable representation; the structured
context keeps values connected to their table meaning. Aggregate result/context
budgets and omission reporting remain in P2-11.4.

Implementation: `src/research_platform/search/table_context.py`.
Contract: `src/research_platform/search/contracts.py` and the typed evidence API
schema.
Synthetic behavior: `tests/test_evidence_table_context.py`.
