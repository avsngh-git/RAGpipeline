# Phase 3.5 lexical parity and built-in BM25 comparison

**Status:** assistant-reviewed, 2026-10-05. Card P35-15
([#59](https://github.com/avsngh-git/RAGpipeline/issues/59)).

**Parity: pass** under ADR-0022 item 7 as amended by the owner on 2026-10-05 (tie-aware).
Under the original strict reading the check fails: 74 lexical comparisons, all from
37 sampled queries, differ only in the order of equally scored results. Profile
`v10-qdrant` therefore inherits the Phase 2 acceptance of v10. P35-16 (full
re-evaluation) is not needed.

This report holds aggregates only. Query text, evidence IDs and per-query rankings stay
under ignored `local-reference/phase35/lexical-parity/` and
`local-reference/phase35/builtin-bm25/`.

## Run record

| Field | Value |
| --- | --- |
| Date | 2026-10-05 |
| Qdrant | `qdrant/qdrant:v1.19.1@sha256:12364fe851b9f17356fc88189fc06d1b521262e04659ec7345975b00c9246a10` |
| Code revision (runs) | `a8a69098629290a53da8811a2c74092e4ad06cae` plus the uncommitted P35-15 scripts, committed with this report |
| Snapshot | `4b11fab3-d4a5-4e7a-a58e-8654accf2c6c` (generation 1) |
| Profiles | v10 `sha256:52a152db…` (BM25S); v10-qdrant `sha256:d4d26d26…` (Qdrant `scientific_bm25`) |
| Generation configuration | `configs/phase35-generation-index-lexical.example.json` (`sha256:3130e408…`) |
| Development queries | 21: 10 `calibration-v1`, 9 allowlisted `benchmark-development-questions-v1` (q11–q19), 2 `calibration-v13-development`; each with its family filters |
| Sampled queries | 200: the first 12 whitespace-separated words of 200 snapshot chunks, chosen with `random.Random(35)` from the chunks sorted by ID |
| Scripts | [`scripts/phase35_lexical_parity.py`](../../scripts/phase35_lexical_parity.py), [`scripts/phase35_builtin_bm25_comparison.py`](../../scripts/phase35_builtin_bm25_comparison.py) |

No held-out data was read.

## Part 1 — parity

### Lexical, top 50

Each query was run through the BM25S retriever and the Qdrant branch with limit 50, for
the evidence and paper roles and both BM25S artifacts that v10 serves (the bm25 profile's
and the hybrid profile's). Paper eligibility is the snapshot's eligible papers under the
query's filters.

| Queries | Role | Comparisons | Identical | Tie order only | Tie across the cut | Other | Count mismatches | Largest relative score difference |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Development | evidence | 42 | 42 | 0 | 0 | 0 | 0 | 2.3e-7 |
| Development | paper | 42 | 42 | 0 | 0 | 0 | 0 | 2.1e-7 |
| Sampled | evidence | 400 | 326 | 52 | 22 | 0 | 0 | 2.8e-7 |
| Sampled | paper | 400 | 400 | 0 | 0 | 0 | 0 | 2.5e-7 |

"Tie order only" means the same IDs with the same score at every position (within 1e-6
relative); only equally scored results changed places. "Tie across the cut" means the same
score at every position, but an equally scored result entered or left the top 50. Both
BM25S artifacts give the same results, so each sampled query appears twice: 37 distinct
queries differ.

**Cause.** BM25S scores those results exactly equally in float32 and orders them by
evidence ID. Qdrant computes the same sums in a different order, so its scores for them
differ by about one float32 unit in the last place (largest difference 2.8e-7) and its
order follows that noise. No result whose BM25S scores differ changed order. Equal
`eligible_count` and `available_count` held for every comparison.

### End to end

v10 (BM25S) and v10-qdrant served every development query in all four modes, for evidence
and paper search, at result limits 10 and 50. Both runs read the same generation
collection (`research-passages-gte-bm25-v1`) so that only the lexical engine changed.
Compared: returned IDs and ranks, supporting evidence, effective mode, eligible count,
status, truncation, omissions and warnings, lexical scores (1e-4 relative), dense and
fused scores (1e-6) and reranker scores (exact).

| Mode | Evidence (identical / compared) | Paper (identical / compared) |
| --- | --- | --- |
| Lexical | 42 / 42 | 42 / 42 |
| Dense | 42 / 42 | 42 / 42 |
| Hybrid | 42 / 42 | 42 / 42 |
| Reranked | 42 / 42 | 42 / 42 |

### Decision

| Rule | Lexical mismatches | End-to-end mismatches | Result |
| --- | --- | --- | --- |
| Strict (IDs equal and in order) | 74 | 0 | fail |
| Tie-aware (ADR-0022 item 7, amended 2026-10-05) | 0 | 0 | **pass** |

The owner chose the tie-aware rule after seeing these results; the alternatives were
re-scoring Qdrant candidates with BM25S arithmetic in Python, the full Phase 2
re-evaluation (P35-16), or keeping BM25S for lexical search.

### Diagnostic: tie effects on sampled queries end to end

Not part of the decision. The 200 sampled queries were also run end to end in hybrid and
reranked modes at limit 10:

| Mode | Evidence responses that differ | Paper responses that differ |
| --- | --- | --- |
| Hybrid | 10 / 200 | 15 / 200 |
| Reranked | 10 / 200 | 11 / 200 |

A swapped lexical tie changes the lexical ranks fed to rank fusion, so final lists can
change. These queries are chunk prefixes, which often reproduce near-duplicate passages
and so create many exact ties; the development questions produced none.

### Finding for the cutover (P35-17): dense ties depend on the collection

The same v10 served from the original dense generation collection (`research-corpus`)
and from `research-passages-gte-bm25-v1` differs in 18 of 336 development responses
(dense 9, hybrid 3, reranked 6; lexical 0). Every difference is between results with
exactly equal dense scores: duplicate chunks with identical embeddings, which Qdrant's
exact search returns in an order that depends on the collection. The dense branch has no
evidence-ID tie-breaker. Cutting over to the lexical generation collection will therefore
change some served rankings among duplicates, independently of the lexical engine.

## Part 2 — built-in `Qdrant/bm25` comparison

Comparison only; it changes no decision (ADR-0022 item 3).

**Build.** `research-passages-qdrant-bm25-v1` copies the 44,277 generation 1 points
(payloads and dense vectors) and adds a server-side sparse vector `bm25` (model
`qdrant/bm25`, `k` 1.2, `b` 0.75, IDF modifier). Qdrant's default `avg_len` of 256 does
not fit this corpus, so each point's token count was solved from its stored weights and
points were re-encoded until `avg_len` equalled the mean count: 31.10 tokens after three
passes. 1,058 passages produce no `Qdrant/bm25` tokens. Every query sends the generation
filter as the IDF corpus.

**Arms.** Each arm changes only the passage lexical scorer. Dense search, fusion code,
selection rules, reranking and paper-title lexical search are shared. "Scientific" is
BM25S, which equals `v10-qdrant` on these queries (Part 1). Hybrid arms use RRF rank
constant 10 (v10) and 60 (the card's setting). Paper lexical-only results are identical
by construction, because paper metadata search uses titles in both arms.

**Data.** The 12 development families that still have source judgments (10
`calibration-v1`, 2 `calibration-v13-development`). The reviewed labels for q11–q19 were
lost on 2026-09-30 and could not be used. MRR and recall are over the 10 queries with
positive judgments. Result limit 50.

| Arm | Paper nDCG@10 | Paper direct MRR@10 | Paper judged R@20 | Evidence nDCG@10 | Evidence direct MRR@10 | Evidence judged R@20 | Evidence judged R@50 | Evidence judgment coverage |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Scientific, lexical | 0.566 | 0.558 | 0.750 | 0.020 | 0.033 | 0.033 | 0.033 | 0.6% |
| Built-in, lexical | 0.566 | 0.558 | 0.750 | 0.116 | 0.140 | 0.267 | 0.267 | 3.8% |
| Scientific, hybrid k=10 (v10) | 0.839 | 0.900 | 1.000 | 0.278 | 0.237 | 0.600 | 0.600 | 8.0% |
| Built-in, hybrid k=10 | 0.783 | 0.833 | 1.000 | 0.352 | 0.420 | 0.500 | 0.500 | 5.5% |
| Scientific, hybrid k=60 | 0.790 | 0.829 | 1.000 | 0.250 | 0.228 | 0.500 | 0.500 | 6.0% |
| Built-in, hybrid k=60 | 0.746 | 0.779 | 1.000 | 0.321 | 0.400 | 0.400 | 0.400 | 5.3% |

No request failed.

**Reading.** In this small sample the built-in encoder ranks judged passages higher
(evidence nDCG@10 and direct MRR), while the scientific encoder gives better paper ranking
in hybrid mode and higher evidence recall@20 in hybrid mode. Judgment coverage is very
low: `calibration-v1` has 21 evidence judgments for 10 families, so most returned passages
are unjudged and score as non-relevant. These are conservative judged-pool scores over 12
families and support no conclusion about which encoder is better.

## Limitations

- The development families are few and were used to choose v10; parity on them says
  nothing new about quality, only that the engine change leaves rankings unchanged.
- Sampled queries are chunk prefixes, not user questions. They exercise exact ties much
  more often than the development questions.
- The tie-aware rule accepts reordering among results whose scores agree within 1e-6
  relative. Their order is arbitrary in both engines, but served rankings can still change
  for queries that produce such ties (diagnostic above).
- Part 2 rests on 12 families with 0.6–8% evidence judgment coverage.
