# Phase 2 fixed-window source fairness and paired development audit

| Field | Value |
| --- | --- |
| Reviewer | Assistant |
| Date | 2026-09-27 |
| Gate | P2-13.5 |
| Comparison | Section-aware vs fixed-window, dense E5 |
| Benchmark slice | q11–q19 only |

## Scope and controls

Both profiles use the same accepted paper/document/extraction selection, E5-small-v2
revision `e8b23a92af33fd81c865283d505f8f058a570cc8`, query formatting, canonical
query text, family filters and 50-result limit. Only selected prose chunking and its
resulting vector index differ. Table and figure units remain in both ranked pools.

The section-aware profile is
`sha256:4f2326bfcbbaf1fc9495931e0f1dbd8fbb18c55015170ebbfcb6ac3c1926df70`,
with index configuration
`sha256:af4ae74756b20946caee031eefeb26aecad5963a451741ef833c66398f30dbe7`.
The fixed-window profile is
`sha256:c2c7429ca329014e1d2b24f3dfd958cb461d93f5315a2977d5e23b9681b7f785`,
with index configuration
`sha256:93ca6395843fe829fa58e550c24ecfceddf79c39874927c7e948fd08ac973844`.
The variant snapshot is
`c3447473-a9f7-4d8c-93c0-e45ebcab763f`.

q11–q19 contain nine new development families. Seven have direct-positive prose
anchors, totaling 27; q15 and q19 have no positive prose anchor and are excluded
from this metric's denominator. Calibration families q01–q10 are table-only for
this chunking question and are not part of the prose-specific paired score. q20 is
excluded after partial unblinding, q21 is excluded after rank/score exposure, and
all held-out families/results remain sealed.

## Source mapping and tokenizer limits

For each reviewed label-2 prose candidate, the complete candidate source interval was
used as its anchor. This is a source-anchored, reproducible proxy: each candidate's
stored text matched its accepted source interval byte for byte, and a unique parent
source mapping was confirmed for all 27 anchors. This interval is broader than a
minimal manually marked supporting sentence; interpret retrieval rates accordingly.

Using the production `region_from_evidence_unit` and
`match_evidence_hits` implementation, every anchor reached full coverage when all
selected chunks in its paper were considered under both strategies. This verifies
that each strategy can represent the same judgments without losing source
coordinates.

| Input set | Count | Max E5 tokens | Max BGE tokens | Over 512 |
| --- | ---: | ---: | ---: | ---: |
| Reviewed full-span prose anchors | 27 | 359 | 357 | 0 |
| Fixed-window chunks in anchor-bearing papers | 301 | 485 | 483 | 0 |

Token counts use the pinned tokenizer revisions and the production E5 passage
prefix where applicable. Table-rendering behavior is unchanged. Parent and variant
retain the same 5,068 non-text IDs: 5,067 table row groups and one figure. The live
variant test also verifies extraction reuse and repeatable chunking from the retained
extraction.

## Paired retrieval results

The metric is the fraction of the 27 source anchors that meet the frozen 80% prose
coverage threshold after unioning source ranges in the top-k dense results. Table
hits remain in rank positions but are not counted as prose support.

| Rank cutoff | Section-aware supported | Section-aware recall | Fixed-window supported | Fixed-window recall |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 2/27 | 7.4% | 1/27 | 3.7% |
| 5 | 4/27 | 14.8% | 4/27 | 14.8% |
| 10 | 7/27 | 25.9% | 6/27 | 22.2% |
| 20 | 9/27 | 33.3% | 9/27 | 33.3% |
| 50 | 13/27 | 48.1% | 13/27 | 48.1% |

At rank 10, the paired family comparison has one improved family, five ties, and
one decline; the unweighted mean family recall change is -1.9 percentage points.
The aggregate anchor count is one lower for fixed windows at rank 10 and tied at
the other reported cutoffs. This q11–q19 prose slice does not show a retrieval
quality gain from fixed-window chunking. The 27-anchor sample is small and
assistant-reviewed, so results are directional rather than a general quality claim.

## Reproduction and integrity

The detailed rank/score artifact is private and ignored:
`local-reference/phase2-runs/fixed-window-20260927/paired-dev-dense-results-v1.json`
(mode 0600, SHA-256
`19ecfacbae803c6e7fa6916b809841245586c714966d79b91356b824b4d45439`).
It stores only q11–q19 result IDs/ranks/scores and aggregate anchor matches; it does
not store query text or source excerpts. The q11–q19 review-card and source-review
hashes are recorded inside that file.

The local-only paired runner is
`run-paired-dev-dense.py` (SHA-256
`abc260a3cbe6bbe74ca651215571b2425113390ecae6a006bc0c2ee73995e56f`).
The setup helper `mirror-parent-e5-test-index.py` (SHA-256
`c79eeb3a06ae7c01bba495d8e2654b62ff43c16dc1882f5135036222c0a1ac8b`)
copies parent vectors read-only from the existing Qdrant collection into disposable
test Qdrant. It reconciles all 44,277 evidence IDs against the cloned parent
selection and sources year/kind/version filter metadata from the test database.
The paired profiles were then run through `SnapshotDenseSearch.evaluate_query`
against the isolated database/Qdrant. The mirror and evaluation changed no accepted
database or index. Implementation revision: `c5e6fc70bf2294197765f872bb5e5dbf3b857caa`.

Focused verification:
- `pytest -q tests/test_ingestion_evidence.py tests/test_ingestion_processing.py tests/test_evidence_deduplication.py tests/test_evaluation_runner.py`: 46 passed.
- `tests/integration/test_live_services.py::test_runner_rechunks_without_repeating_matching_extraction_checkpoint`: 1 passed against disposable `research_test` PostgreSQL and Qdrant; BM25S came from the previously verified temporary /tmp path.
- `git diff --check`: passed after the report and status updates.

## P2-14 implication

Keep fixed-window chunking as a measured alternative. Do not select it based on a
quality claim from this slice. P2-14 must compare it alongside lexical, dense,
hybrid and reranked profiles across the eligible development families, report
candidate recall and source-anchor metrics separately, and declare acceptance limits
before held-out evaluation. No q20/q21 or held-out result informed this audit.
