# Phase 2 source matching policy v1

Status: implemented for the `phase2-calibration-v1` calibration set on 2026-09-26.

The executable matching policy is `source-match-policy-v1`; ranked scoring is
specified in [phase-2-scoring-policy.md](phase-2-scoring-policy.md). Its coordinate
manifest is
[`source-alignment-v1.toml`](../../benchmarks/phase2/source-alignment-v1.toml),
loaded by `research_platform.evaluation.source_alignment` and applied by
`research_platform.evaluation.matching`.

## Identity and overlap

A returned hit is resolved through its source evidence IDs to canonical evidence
regions. Each region must match the hit's document and extraction IDs. Evidence IDs
locate provenance; relevance depends on canonical extraction coordinates. Matching
works across chunk boundaries and duplicate IDs or overlapping regions add no extra
coverage.

Text regions are unioned within the same section and clipped to each annotated span.
Ordinary prose spans require at least 80% character coverage. A critical span requires
100%; the alignment loader accepts only these two thresholds. An anchor is fully
supported only when every annotated span meets its threshold. Its reported coverage
fraction is the length-weighted coverage across spans.

For tables, an alignment names the table ordinal and its target cells. Each target
cell must be fully present together with every listed row or column header cell.
Repeated row groups contribute their exact source rows and repeated headers. Long
cell segments contribute token intervals; they fail closed when the canonical token
count is unavailable. Coverage is unioned by cell coordinate, so duplicate chunks do
not increase it. A table anchor is fully supported only when all mapped target cells
and their header cells are present, and all listed table context types are present.
The coverage fraction counts fully covered target cells. The matcher does not credit a
matching number at a different row or column.

The manifest requests captions for seven aligned tables. It omits caption context for
`s-table10` because the accepted extraction caption disagrees with the visually
reviewed Table 10 anchor. That alignment remains pinned to the accepted document,
extraction, and table ordinal, and still requires its mapped cells and headers. The
aligned tables have no extracted units or footnotes.

## Calibration coverage and limits

The current manifest aligns all eight label-2 table anchors and contains 942 target
cell coordinates plus their required header coordinates. It has no prose alignments:
the current calibration contains no label-2 prose anchor. Ordinary and critical prose
thresholds are therefore frozen but not exercised by this dataset. A future direct-
positive prose anchor must receive spans before the alignment loader accepts the
updated calibration.

The coordinate manifest contains IDs, ordinals, and cell coordinates, with no source
text or cell values. Coordinates were generated from the accepted extraction and
assistant-reviewed for alignment identity and question scope against the calibration
queries and source anchors. The underlying source attribution remains the reviewed
calibration record; P2-05.2 did not independently reassess it.
