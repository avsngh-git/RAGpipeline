# Phase 2 development evaluation report

**Status:** P2-14 complete · **Reviewer:** assistant · **Date:** 2026-09-27
**Snapshot:** 4b11fab3-d4a5-4e7a-a58e-8654accf2c6c · 44,277 selected chunks
**Benchmark scope:** canonical calibration q01–q10 and source-reviewed development q11–q19.
q20, q21 and held-out q22–q31 were excluded. No held-out labels or rankings informed these decisions.

## Method and replay

The harness was first reconciled on a one-query replay against the saved result IDs and source matches. The full comparison then used the same snapshot selection, candidate cap of 50, eligible filters, query set and five warm repeats for BM25, dense E5, dense BGE, hybrid E5 and hybrid BGE. The 19 query families comprise ten calibration families and nine development families. Four queries applied metadata filters. No retrieval first-run or warm-repeat failures occurred.

For the reranker comparison, both models received the exact saved hybrid-E5 pool of 50 candidate IDs for each of 19 queries. Candidate-set hashes matched the upstream pool. The 512-token pair policy rejects the whole reranker pool when any pair exceeds budget; it never truncates or removes a candidate. The reported serving candidate is MiniLM with the explicit reranked-to-hybrid fallback for the six over-budget queries, so its quality denominator includes all 19 attempted queries.

Source quality uses ten source-grounded calibration families and 31 direct-positive development anchors: 27 prose spans and four assistant-reviewed table anchors. The q12/q14 table audit records exact accepted-extraction coordinates. Two independently source-found table anchors contribute to recall denominators but are not inserted in result lists. These are pooled source-recall measures, not exhaustive corpus recall.

## Retrieval comparison

Calibration metrics are macro means over answerable families. Evidence ranking uses the frozen source-match and evaluation-scoring policies; judgment coverage is reported in the private raw run record.

| Profile | Paper nDCG@10 | Paper direct MRR@10 | Paper judged recall@20 | Evidence nDCG@10 | Evidence direct MRR@10 | Evidence judged recall@20 | Dev source-anchor recall@10 / @20 / @50 | Warm median / nearest-rank p95 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| BM25 | 0.770 | 0.686 | 0.944 | 0.043 | 0.028 | 0.222 | 0.226 / 0.323 / 0.484 | 324 / 383 ms |
| Dense E5 | 0.873 | 0.944 | 1.000 | 0.456 | 0.460 | 0.667 | 0.226 / 0.290 / 0.452 | 550 / 704 ms |
| Dense BGE | 0.857 | 0.861 | 1.000 | 0.308 | 0.260 | 0.611 | 0.226 / 0.258 / 0.516 | 595 / 745 ms |
| Hybrid E5 | 0.879 | 0.889 | 1.000 | 0.261 | 0.198 | 0.667 | 0.226 / 0.355 / 0.581 | 876 / 1,037 ms |
| Hybrid BGE | 0.822 | 0.736 | 1.000 | 0.199 | 0.148 | 0.611 | 0.226 / 0.323 / 0.613 | 929 / 1,046 ms |
| MiniLM over Hybrid E5, with fallback and cap five | 0.928 | 0.944 | 1.000 | 0.496 | 0.509 | 0.667 | 0.290 / 0.355 / 0.419 | Stagewise bound below |

The five first-stage rows report candidate rankings before response selection; the MiniLM composite row reports the served order after the per-paper cap of five. All five first-stage profiles retrieved 7/31 direct-positive anchors by rank 10. Hybrid E5's deeper-pool advantage appears at ranks 20 and 50, while dense E5 ranks evidence substantially better on calibration and is faster. The 10-family paired bootstrap for hybrid E5 versus dense E5 source-anchor recall@10 has mean delta +0.012, 95% percentile interval [-0.071, +0.107]; this is not evidence of a reliable top-10 gain.

MiniLM fallback raises calibration evidence nDCG@10 by +0.234 (paired 10 families; 95% interval [+0.096, +0.383]) and direct MRR@10 by +0.312 (9 answerable families; interval [+0.108, +0.528]) versus the same hybrid order. Across seven positive development families, source-anchor recall@10 is 9/31 (0.290), with at least one anchor returned in five families. The paired family mean delta versus hybrid is +0.052 (interval [0.000, +0.114]). These small family counts support a directional development choice, not a general claim about scientific literature.

## Reranker and selection results

| Reranker | Full-pool success | Over-budget fallback share | Successful-pool warm median / p95 | GPU peak allocated / reserved |
| --- | ---: | ---: | ---: | ---: |
| MS MARCO MiniLM-L6-v2 | 13/19 | 6/19 (31.6%) | 236 / 301 ms, 78 samples | 129 / 164 MiB |
| BGE reranker base | 6/19 | 13/19 (68.4%) | 964 / 1,157 ms, 36 samples | 1,136 / 1,285 MiB |

The fallback policy yields an all-query quality score. The stagewise conservative latency estimate for MiniLM is the hybrid-E5 nearest-rank p95 (1,037 ms) plus reranker p95 (301 ms), or 1,338 ms. This is a sum of separately measured component tails, not an observed joint-request p95; the integrated service must measure and meet the 1,500 ms gate. MiniLM and E5 measured model loads were 6.4 s and 6.1 s, respectively. Their conservative sum is 12.6 s. Summed peak CUDA allocation is below 1 GiB. BGE reranking misses both the fallback-share and resource/latency limits.

With dense E5 candidates, the per-paper evidence cap retained 154/450, 281/450 and 337/450 results for caps 1, 3 and 5. Source-anchor recall@10 was 0.065, 0.129 and 0.226; cap 5 preserved the unbounded top-10 score. Source-overlap dedup removed no candidates in this snapshot. Paper support caps 1, 3 and 5 yielded means of 1.00, 2.10 and 2.68 support passages among the top ten papers. The serving cap is five evidence items per paper and five support passages per paper. Recheck the selected reranked ordering against this cap in the final replay.

Section-aware chunking remains selected; the fixed-window audit found one more reviewed prose anchor at rank 10 and both chunkers supported 13/27 prose anchors at rank 50. No chunking change is justified by these results.

## Runtime and storage observations

The matrix used single-user serial execution, five warm repeats across 19 queries per retrieval profile (114 samples), an RTX 3050 Laptop GPU exposed through WSL, and the local 8 GiB WSL memory limit. Retrieval first-run failures and warm-repeat failures were zero. Embedding load times were E5 6.1 s and BGE 0.9 s in the measured process/cache state; these are local observations, not portable cold-start guarantees.

A synthetic zero-match metadata-filter probe ran five requests per profile with zero eligible papers and zero results. Median / nearest-rank p95 were: BM25 11 / 13 ms, dense E5 330 / 417 ms, dense BGE 303 / 335 ms, hybrid E5 310 / 331 ms and hybrid BGE 327 / 352 ms. The exact zero-match count and raw samples remain in the private run record.

Local lexical artifacts occupied 116,212,269 bytes across 42 files. Model caches occupied 3,677,633,032 bytes for rerankers, 1,315,758,697 bytes for BGE embeddings and 268,957,394 bytes for E5. Qdrant reported both disposable vector collections green with 44,277 points; this version did not expose their disk use. The accepted database and vector collection were not written. Full measurements and IDs remain mode-0600 under ignored local-reference/phase2-runs.

## P2-14 decision and acceptance limits

MiniLM over hybrid E5 with whole-pool reranked-to-hybrid fallback is the only measured profile that clears the declared evidence-quality floors while keeping a plausible single-user runtime on this hardware. Dense E5 remains the named dense baseline; hybrid E5, BM25 and the fixed-window run remain paired comparisons. The unsupported-query acceptance threshold stays disabled: all search responses mean ranking only.

The numeric gates are versioned in benchmarks/phase2/acceptance-v1.toml. They require calibration evidence nDCG@10 >= 0.45, direct MRR@10 >= 0.45 and judged Recall@20 >= 0.60; development source-anchor recall >= 0.25 at rank 10 and >= 0.35 at rank 50, with at least one direct anchor in five of seven positive families. This means the profile must retrieve at least roughly one quarter of known direct-source requirements within ten results and about one third within fifty after output selection. The floor is modest and applies only to the reviewed pool. Held-out scoring uses the same frozen limits. The selected profile must also remain within 1% hard failures, 35% explicit reranker fallbacks, 1,500 ms warm p95, 15 s combined cold model load and 1 GiB summed CUDA allocation. If held-out usefulness or operations fail, report a failed gate; do not adjust these limits using test labels.

## Reproduction and artifact links

The offline scorer was replayed after adding the full-query fallback composite. It reconciles candidate IDs and exact accepted-source mappings before scoring. The raw benchmark and scorer are private, mode-0600 artifacts; only their hashes are recorded in the local handoff. The sanitized table-coordinate audit is [q12/q14 source review](phase-2-q12-q14-table-candidate-audit.md), the fixed-window results are [P2-13 source fairness audit](phase-2-fixed-window-source-fairness-audit.md), and the tracked profile and thresholds are [acceptance-v1.toml](../../benchmarks/phase2/acceptance-v1.toml) and [frozen-profile-v1.toml](../../benchmarks/phase2/frozen-profile-v1.toml).


## P2-15 freeze and integrated API check — 2026-09-27

The selected serving configuration is frozen as MiniLM over Hybrid E5, with a
whole-pool reranked-to-hybrid fallback, five evidence items per paper, and no
unsupported-query cutoff. The serving profile identity is
`sha256:243e3d5923ee930940a29cf4ba79db2392cf4a5bfe777a54cedd2a316fd22870`; the
acceptance configuration identity is
`sha256:6beb525c6a5d76b2bcf28dd0c03bce527872ca462ce44dceba4ea5ce383590bb`.
The tracked profile's dense binding was corrected to the separate, filter-ready Phase
2 collection used by development evaluation. This corrects artifact identity and
runtime configuration binding; it does not change the selected model, ranking,
selection, thresholds, query set, or acceptance decision. The accepted Phase 1
collection was retained.

The real-model WSL API smoke check passed for paper search, table-filtered evidence
search, a zero-eligible filter, paper metadata, references and citations. Each route
returned the expected successful response. Five warm table-filtered requests measured
1,128.81–1,245.15 ms (nearest-rank p95 1,245.15 ms), under the predeclared 1,500 ms
limit. The first warm request after startup is included; this is a small local smoke
sample, not a replacement for held-out timing. The isolated dense collection was
rebuilt and reconciled against all 44,277 selected evidence units. No held-out query,
label, score or result was inspected.
