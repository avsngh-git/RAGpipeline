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


## Held-out status update — 2026-09-27

The P2-15 profile was frozen for v3 assessment, not accepted as the final quality
default. The held-out run failed paper nDCG@10, evidence nDCG@10, reranker fallback,
and warm p95 gates. See the [P2-20 acceptance report](../reference/phase-2-acceptance-report.md).
Do not tune from v3 results; new selection work must use development data and a newly
frozen held-out question set.

## Reranker prefix cap follow-up — 2026-09-27

After the v3 gate failed, a bounded follow-up varied only the MiniLM reranker prefix
size over the same 50-candidate Hybrid-E5 pool. Calibration q01–q10 and source-
reviewed development q11–q19 were used; q20, q21 and every held-out family were
excluded. A successful run reranks the first *k* fused candidates and keeps the
remaining candidates in their original hybrid order. Any token-budget or typed
inference failure returns the complete unchanged 50-candidate hybrid order. The
pair budget, model revision, query text, filters, source judgments, selection caps
and quality gates were unchanged.

| Reranked prefix | Fallbacks | Paper nDCG@10 | Paper direct MRR@10 | Evidence nDCG@10 | Evidence direct MRR@10 | Evidence judged Recall@20 | Source anchors @10 / @50 | Positive families hit @10 | Reranker warm p95 |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 10 | 0/19 | 0.9255 | 0.9444 | 0.5018 | 0.5556 | 0.6667 | 7/31 / 12/31 | 7/7 | 75 ms |
| 20 | 4/19 (21.1%) | 0.9583 | 1.0000 | 0.5124 | 0.5370 | 0.6667 | 9/31 / 13/31 | 7/7 | 134 ms |
| 50 | 6/19 (31.6%) | 0.9277 | 0.9444 | 0.4957 | 0.5093 | 0.6667 | 9/31 / 13/31 | 7/7 | 315 ms |

The 10-candidate setting missed the development source-anchor recall@10 floor
(0.226 < 0.25). The 20-candidate setting met the development floors and matched
the full-pool setting's source-anchor recall while improving calibration ranking
scores and lowering reranker fallback and latency. Its 90 successful timing samples
included five warm repeats per family. Adding the previously measured Hybrid-E5
p95 of 1,037 ms to the reranker p95 gives a conservative stagewise estimate of
1,171 ms. This is not an observed joint API p95; the integrated API measurement is
still required. The selected profile is frozen at
sha256:3a8b4b57638d025405f276ddc22f9e5593f99e2807f40ee2c0e7a3fea8df7692,
with rerank prefix 20 and hybrid tail preservation. Numeric acceptance thresholds
are unchanged in acceptance-v2.toml.

Raw rankings and timing samples, together with mode-0600 reproduction scripts, are
under ignored local-reference/phase2-runs/p2-14-validation/. These results use
development-only data and do not use or disclose v3 item-level results. The v3
acceptance failure remains in the historical report; the profile requires a new,
freshly frozen held-out assessment.

## Development-only prefix re-selection — 2026-09-28

After the v5 held-out assessment failed its paper nDCG gate, the spent holdout was
sealed from selection. A fresh development-only cap sweep used calibration q01–q10
and source-reviewed q11–q19; no held-out ranks, scores, or judgments informed this
choice. All candidates used the same 50-item Hybrid-E5 pool, source labels,
per-paper selection limits, pair budget, and acceptance floors. Only the MiniLM
reranker prefix changed.

| Rerank prefix | Fallbacks | Paper nDCG@10 / MRR@10 / Recall@20 | Evidence nDCG@10 / MRR@10 / Recall@20 | Source anchors @10 / @50 | Positive families hit @10 | Reranker p95 |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 12 | 0/19 | 0.9438 / 0.9444 / 1.0000 | 0.4938 / 0.5370 / 0.6667 | 8/31 / 12/31 | 7/7 | 86 ms |
| 14 | 1/19 | 0.9799 / 1.0000 / 1.0000 | 0.4938 / 0.5370 / 0.6667 | 8/31 / 12/31 | 7/7 | 95.89 ms |
| 16 | 3/19 | 0.9799 / 1.0000 / 1.0000 | 0.5282 / 0.5556 / 0.6667 | 8/31 / 12/31 | 7/7 | 106.83 ms |
| 18 | 3/19 | 0.9778 / 1.0000 / 1.0000 | 0.5282 / 0.5556 / 0.6667 | 8/31 / 12/31 | 7/7 | 120.81 ms |

At that checkpoint, cap14 was selected using development data only. It ties cap16 on paper
nDCG@10, MRR@10 and Recall@20; its evidence nDCG@10 remains above the frozen floor,
while the observed fallback share is lower (1/19 rather than 3/19) and reranker p95
is 95.89 ms rather than 106.83 ms. Source-anchor counts and positive-family coverage
are unchanged across these two caps. Cap14's profile identity is
`sha256:c8a974c9956a408ae8baa50a0d16b49930f68e2dc0062d66007ef5cf61ecd9b4`.
This interim selection used no held-out outcomes. The cap16 re-selection below
supersedes it. The v7 assessment is recorded separately; any later
acceptance attempt must use a newly source-reviewed held-out set and the unchanged
numerical gates.


## Development-only prefix re-selection — 2026-09-28

A further comparison used only calibration q01–q10 and source-reviewed development
q11–q19. It compared the already measured prefix 14 and 16 configurations; no held-
out question, score, rank or judgment informed this freeze.

| Prefix | Paper nDCG / MRR / Recall@20 | Evidence nDCG / MRR / Recall@20 | Source anchors @10 / @50 | Fallbacks | Reranker p95 |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 14 | 0.9799 / 1.0000 / 1.0000 | 0.4938 / 0.5370 / 0.6667 | 8/31 / 12/31 | 1/19 | 95.89 ms |
| 16 | 0.9799 / 1.0000 / 1.0000 | 0.5282 / 0.5556 / 0.6667 | 8/31 / 12/31 | 3/19 | 106.83 ms |

Prefix 16 was selected for the v9 freeze because it improved development evidence
nDCG and direct MRR while tying cap14 on paper metrics, evidence Recall@20 and source
coverage. Its development fallback share (3/19) and reranker p95 remained below the
frozen operational limits. This is a development-only selection rationale; v9 later
missed the paper nDCG gate, and that spent held-out outcome does not change this
selection or authorize tuning from v9.

## Integrated search-service timing replay — 2026-09-28

A separate warm timing replay exercised the frozen v8 profile on the ten calibration
families and nine source-reviewed development families only. It made five measured
repeats for each family and operation after one full warm-up pass (95 paper-search
and 95 evidence-search samples). This calls the integrated application search
executor; it does not include HTTP transport or response serialization.

| Operation | Samples | Median | Warm p95 (nearest rank) | Maximum |
| --- | ---: | ---: | ---: | ---: |
| Paper search | 95 | 1,179.79 ms | 1,433.45 ms | 1,563.31 ms |
| Evidence search | 95 | 1,127.83 ms | 1,336.92 ms | 1,412.76 ms |

The replay had zero hard failures and 30 explicit reranker fallbacks across 190
measured requests (15.8%). It ran on the WSL-exposed RTX 3050 Laptop GPU with profile
`sha256:959e24b6ff6de711bbdfbf5020c5ac82a91cce43f48c8f52ba9d214c3e00e9be`. The
mode-0600 aggregate and reproduction script are retained under ignored
`local-reference/phase2-runs/p2-14-validation/`.

Both operation-specific development p95 values are below the frozen 1,500 ms limit.
At that checkpoint, this development replay did not replace or clear the v10 held-out
result, whose selected-profile p95 was 1,602.2 ms across 100 warm requests. No threshold
or profile changed. The later fresh v11 assessment is recorded below and in the
[acceptance report](../reference/phase-2-acceptance-report.md).




## Typed fallback and warm API diagnostic — 2026-09-28

After the request-scoped selection change, the tracked development runner exercised the
actual HTTP routes on only allowlisted q11–q19 development families (18 cases across
paper and evidence search). It used frozen profile v9
(`sha256:959e24b6ff6de711bbdfbf5020c5ac82a91cce43f48c8f52ba9d214c3e00e9be`), six
warm-ups and 100 measured requests in each of three sessions, with result limit 10,
concurrency one, four CPU threads, automatic device selection, and no intentional
background load. The private input and aggregate output are mode 0600 under `/tmp`;
the output identifies the code revision, tracked diff, input, and run by digest.

| Session | HTTP median | HTTP p95 (nearest rank) | Hard failures | Whole-pool fallbacks | Selection reconstructions |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 635.18 ms | 851.00 ms | 0 | 23/100 | 100 |
| 2 | 648.59 ms | 875.56 ms | 0 | 23/100 | 100 |
| 3 | 670.47 ms | 893.61 ms | 0 | 23/100 | 100 |

All 69 fallbacks were typed `pair_overflow` events (23%); there were no timeout, busy,
device-exhaustion, or other adapter failures. Every fallback query was in the 0–512
character bucket, and the length-only candidate breakdown associates the observed
overflow with long prose inputs (2,049+ characters); table candidates in the rerank
prefix were in the 513–2,048 bucket. Each request performed one exact selection
reconstruction. The fallback rate is below the frozen 35% allowance, so this diagnostic
does not justify changing pair formatting, reranker policy, or profile thresholds.
The private per-request report retains response fingerprints and stage timings without
query text, evidence identifiers, or passage text; it remains outside Git.


## Offline runtime and retained asset inventory — 2026-09-28

The digest-checked `active-profile.toml` resolves to frozen profile v9 in the source
checkout, the CLI and the rebuilt Linux AMD64 image. A real FastAPI lifespan loaded
the pinned E5 and MiniLM revisions with `HF_HUB_OFFLINE=1` and
`TRANSFORMERS_OFFLINE=1`; the loopback `/ready` returned 200 with PostgreSQL, Qdrant
and Phase 2 runtime ready. Synthetic requests to `/v1/search` and
`/v1/evidence/search` both returned 200 with five results and effective mode
`reranked`. The smoke printed counts and mode only. Both model adapters use
`local_files_only=True`; no model download was enabled. One initial Uvicorn start logged
runtime unavailable, but the same settings succeeded through direct runtime and API
lifespan checks and the subsequent loopback run; no repeatable startup error was found.

Read-only size checks recorded the current local footprint:

| Asset | Measured size | Retention note |
| --- | ---: | --- |
| `local-reference/phase2-indexes` lexical artifacts | 111 MB | Keep; configured runtime input for BM25 and Hybrid-E5. |
| `/tmp/phase1-embedding-hf-cache` E5 cache | 634 MB | Diagnostic cache; copy to a durable configured cache before clearing `/tmp`. |
| `/tmp/phase2-reranker-hf-cache` MiniLM cache | 1.2 GB | Diagnostic cache; copy to a durable configured cache before clearing `/tmp`. |
| `ragpipeline_qdrant_data` total | 564 MB | Keep; contains retained Phase 1 and Phase 2 data. Phase 2 collection directory measures 157 MB. |
| `p2_eval_20260927_qdrant_data` total | 557 MB | Preserve; isolated comparison volume may contain referenced evaluation variants. |

No index, model cache or volume was deleted. The two `ragpipeline-phase2-r3-test-*`
containers used for integration are disposable and run without named persistent volumes;
they can be stopped after verification. The locally built `ragpipeline-phase2-r7` image
is also a verification artifact and can be removed after publication checks.

## Later Phase 2 acceptance — 2026-09-28

This report records development-only choices. The subsequent fresh v11 held-out
assessment passed every frozen gate with the unchanged selected profile and numeric
limits; see the [acceptance report](../reference/phase-2-acceptance-report.md) for
sanitized results. Earlier held-out failures remain historical and spent.


## R1–R7 integrated verification and R8 freeze — 2026-09-28

The reconciled implementation is frozen at code revision `586f83ce08580b4a206830e83d7f71cab4722d59`. The active profile resolves to v9 with canonical profile identity `sha256:959e24b6ff6de711bbdfbf5020c5ac82a91cce43f48c8f52ba9d214c3e00e9be`. Configuration file hashes: `active-profile.toml` `db2617ecdcc598eef8171ec17bceef88da736fade73e0eecb442eb5c5cb6c039`, `frozen-profile-v9.toml` `11c70b0c3dbd92bf35ad473b0085f42dbd752cb2341e3f28f570c5e77614d32e`, and `acceptance-v9.toml` `3ef732d9a0645371d63dd57aa205f8e066a6eec48b4936bb6f81c4ccfa3bd572`.

Post-reconciliation local checks passed: Ruff lint, formatting (214 files), strict mypy (81 source files), 451 offline tests, 21 integration tests against fresh disposable PostgreSQL/Qdrant services, `pip check`, Linux AMD64 Docker build, packaged-image `pip check`, and active-profile image smoke. The offline suite command used `PYTHONPATH=src` to make the isolated worktree take precedence over the shared Conda environment's editable install. The image smoke resolved `frozen-profile-v9.toml` and the expected canonical profile identity. Hosted CI passed on the exact frozen code revision in [run 36445793795](https://github.com/avsngh-git/RAGpipeline/actions/runs/36445793795).

The R8 source screen is preparatory only; it contains no family wording or labels. The missing-evidence scan and freshness review remain before the new held-out set can be frozen and scored. No result from the new set has been observed.
