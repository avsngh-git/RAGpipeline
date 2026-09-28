# Phase 2 held-out acceptance report

**Current status — Phase 2 accepted.** The fresh, source-reviewed `phase2-benchmark-v11`
assessment passed every frozen quality and operational gate. The selected profile and
all numeric limits were unchanged. P2-01–P2-20 are complete; Phase 3 has not started.
This report publishes aggregate measurements and artifact identities only. Held-out
questions, source excerpts, candidate text, item-level judgments, rankings and raw run
records remain private.

## v11 decision and scope

The ten-family v11 set was frozen before scoring and reviewed by the assistant against
primary source material. Its composition was 10 discovery, 8 specific-evidence, 4
table-result, 3 cross-paper-comparison, 5 filters and 3 missing-evidence families
(category membership may overlap). All 622 pooled candidates were assistant-reviewed: 235 paper candidates (204 label 0,
22 label 1, 9 label 2) and 387 evidence candidates (273 label 0, 88 label 1, 26 label 2).
Nine direct source anchors were checked by assistant review against their sources, with
eight actual retrieval-hit links in the candidate pool; no gold item was inserted into
a result. The selected profile's judgment coverage over evaluated results was 217/301
paper results (72.1% micro; 82.3% macro across ten families) and 173/173 evidence
results (100%). Review time was not separately measured. Source uncertainty and
judgments remain recorded in the private assistant-reviewed materials; no second
reviewer or human verification is claimed. The accepted snapshot contains 100 papers
and 44,277 selected chunks.

The sample is purposive and supports directional evidence, not precise population
estimates or a claim about the whole literature. This measures ranking and retrieval;
no generated-answer quality was tested. Source/group coverage beyond the predeclared
gates is descriptive. Public passage display remains disabled.

## Frozen v11 identities

| Field | Value |
| --- | --- |
| Assessment | `phase2-benchmark-v11`, ten held-out families |
| Acceptance config | [`acceptance-v9.toml`](../../benchmarks/phase2/acceptance-v9.toml); SHA-256 `3ef732d9a0645371d63dd57aa205f8e066a6eec48b4936bb6f81c4ccfa3bd572` |
| Frozen profile | [`frozen-profile-v9.toml`](../../benchmarks/phase2/frozen-profile-v9.toml); SHA-256 `11c70b0c3dbd92bf35ad473b0085f42dbd752cb2341e3f28f570c5e77614d32e` |
| Selected profile identity | `sha256:959e24b6ff6de711bbdfbf5020c5ac82a91cce43f48c8f52ba9d214c3e00e9be` |
| Question-manifest SHA-256 | `d9c307c35dce3f97ad3b26885ebb74da47d1338a21e319404db22dd066f41175` |
| Split-manifest SHA-256 | `185ec18ad7e9483e2b4f636e0ed3d5e9baa06c063f6ba002dc8886086744d2fd` |
| Source-review SHA-256 | `1cc76aab917cbaed8d73aaead305cd862127ed87d9d1b7bce6ed97fc282b5dba` |
| Source-judgment SHA-256 | `32308177ba07d44e2a58997a7711656b25b22a4ea84e8ed40310b38aa3f10c4a` |
| Source-chunk mapping SHA-256 | `d1430c94ad31c1e2f42675ccbe7e8a28c7bd90b0622093bbe3fee9e8472bd958` |
| Snapshot | `4b11fab3-d4a5-4e7a-a58e-8654accf2c6c`, 100 papers, 44,277 selected chunks |
| Snapshot selection identity | `sha256:cc5b7c30962ce66ad279a5ff95b0e1e6dd8aede68980292717d1a7a23ecd6f18` |
| Candidate-pool manifest SHA-256 | `00ad816857fdc08a8de0be22b6c225a51f6b9c1c7d0fd85e60b57190ece042f6` |
| Evaluated worktree identity | Git revision `ed56e59451203cc4ddaadfb6c4a070ba18260368`; tracked diff SHA-256 `70757330c2c03197eeae6c536bb53486a54c0e5f678ace2cb59bf91f429c6a44` (tracked worktree was dirty) |
| Evaluated implementation content | Runtime/source/test/dependency files match sanitized implementation revision `8304b8a44a862f6737c14f6434112ee619908f83` |
| Bootstrap | 10,000 paired family resamples; seed 20260930 |
| Run-record SHA-256 | `39e209c09e376b26adeaf7f5a692fa39e40cffe878484b3c4c196b804b440fd1` |

The v11 question set, split, source review, source judgments, source map, candidate
cards and raw run are retained under the ignored private `local-reference/` directory.
The public config files contain frozen hashes and model/ranking settings, not question
text or item-level labels.

## v11 profile comparison

nDCG values are macro means over ten held-out families. Direct MRR and judged recall
use the seven families with applicable positive judgments; source-anchor recall is micro
recall over nine independently reviewed anchors. Each profile has 100 warm requests
(50 paper and 50 evidence searches), after one warm-up pass; the run uses five repeats
per family and operation.

| Profile | Paper nDCG@10 | Paper MRR@10 | Paper Recall@20 | Evidence nDCG@10 | Evidence MRR@10 | Evidence Recall@20 | Source Recall@10 / @50 | Warm p95 (ms) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| BM25 lexical | 0.7270 | 0.7381 | 1.0000 | 0.4459 | 0.3571 | 0.3723 | 0.2222 / 0.3333 | 576.7 |
| Dense E5 | 0.9037 | 0.9286 | 1.0000 | 0.4958 | 0.5000 | 0.4278 | 0.4444 / 0.4444 | 883.2 |
| Hybrid E5 | 0.9301 | 1.0000 | 1.0000 | 0.4871 | 0.4762 | 0.4437 | 0.4444 / 0.5556 | 1,232.1 |
| MiniLM over Hybrid E5 (selected) | 0.9208 | 1.0000 | 1.0000 | 0.6682 | 0.6357 | 0.8737 | 0.5556 / 0.5556 | 1,485.8 |
| Fixed-window dense E5 | 0.9202 | 0.9286 | 1.0000 | 0.3408 | 0.4286 | 0.2561 | 0.4444 / 0.4444 | 370.6 |

The MiniLM-over-Hybrid-E5 profile remains the selected serving profile under its frozen
identity. Its result shows the strongest evidence-ranking metrics in this comparison;
profile selection was made from development evidence before v11.

### Selected-profile category results

Categories overlap. Source recall is micro recall and is omitted where there is no
positive direct source anchor.

| Category | Families | Paper nDCG@10 | Evidence nDCG@10 | Source Recall@10 |
| --- | ---: | ---: | ---: | ---: |
| Cross-paper comparison | 3 | 0.7870 | 0.6959 | 0.7500 |
| Discovery | 10 | 0.9208 | 0.6682 | 0.5556 |
| Filters | 5 | 0.9663 | 0.6883 | 0.4000 |
| Missing evidence | 3 | 0.7824 | 0.7066 | — |
| Specific evidence | 8 | 0.9734 | 0.6616 | 0.5556 |
| Table result | 4 | 0.9875 | 0.6518 | 0.2500 |

### Paired differences and uncertainty

Deltas are selected MiniLM-over-Hybrid-E5 minus each named profile; intervals are
percentile 95% intervals from 10,000 paired family resamples with seed 20260930.
The number of families with a defined paired metric varies by row. These intervals are
descriptive for the purposive ten-family sample, not population estimates.

| Baseline | Metric | Families | Mean delta [95% interval] |
| --- | --- | ---: | ---: |
| BM25 lexical | Paper nDCG@10 | 10 | +0.1938 [+0.0877, +0.3209] |
| BM25 lexical | Paper direct MRR@10 | 7 | +0.2619 [+0.0714, +0.5000] |
| BM25 lexical | Paper judged Recall@20 | 7 | +0.0000 [0.0000, 0.0000] |
| BM25 lexical | Evidence nDCG@10 | 10 | +0.2222 [+0.0871, +0.3497] |
| BM25 lexical | Evidence direct MRR@10 | 7 | +0.2786 [-0.1286, +0.6429] |
| BM25 lexical | Evidence judged Recall@20 | 7 | +0.5014 [+0.2157, +0.7857] |
| BM25 lexical | Source Recall@10 | 7 | +0.2857 [0.0000, +0.5714] |
| BM25 lexical | Source Recall@50 | 7 | +0.2143 [0.0000, +0.5000] |
| Dense E5 | Paper nDCG@10 | 10 | +0.0171 [-0.0896, +0.1341] |
| Dense E5 | Paper direct MRR@10 | 7 | +0.0714 [0.0000, +0.2143] |
| Dense E5 | Paper judged Recall@20 | 7 | +0.0000 [0.0000, 0.0000] |
| Dense E5 | Evidence nDCG@10 | 10 | +0.1723 [+0.0962, +0.2495] |
| Dense E5 | Evidence direct MRR@10 | 7 | +0.1357 [-0.1857, +0.4929] |
| Dense E5 | Evidence judged Recall@20 | 7 | +0.4459 [+0.1429, +0.7619] |
| Dense E5 | Source Recall@10 | 7 | +0.0714 [0.0000, +0.2143] |
| Dense E5 | Source Recall@50 | 7 | +0.0714 [0.0000, +0.2143] |
| Hybrid E5 | Paper nDCG@10 | 10 | -0.0092 [-0.0428, +0.0137] |
| Hybrid E5 | Paper direct MRR@10 | 7 | +0.0000 [0.0000, 0.0000] |
| Hybrid E5 | Paper judged Recall@20 | 7 | +0.0000 [0.0000, 0.0000] |
| Hybrid E5 | Evidence nDCG@10 | 10 | +0.1811 [+0.0779, +0.2861] |
| Hybrid E5 | Evidence direct MRR@10 | 7 | +0.1595 [-0.2024, +0.5167] |
| Hybrid E5 | Evidence judged Recall@20 | 7 | +0.4300 [+0.1429, +0.7302] |
| Hybrid E5 | Source Recall@10 | 7 | +0.0714 [0.0000, +0.2143] |
| Hybrid E5 | Source Recall@50 | 7 | +0.0000 [0.0000, 0.0000] |
| Fixed-window dense E5 | Paper nDCG@10 | 10 | +0.0006 [-0.0867, +0.0718] |
| Fixed-window dense E5 | Paper direct MRR@10 | 7 | +0.0714 [0.0000, +0.2143] |
| Fixed-window dense E5 | Paper judged Recall@20 | 7 | +0.0000 [0.0000, 0.0000] |
| Fixed-window dense E5 | Evidence nDCG@10 | 10 | +0.3274 [+0.1944, +0.4333] |
| Fixed-window dense E5 | Evidence direct MRR@10 | 7 | +0.2071 [-0.2571, +0.6714] |
| Fixed-window dense E5 | Evidence judged Recall@20 | 7 | +0.6176 [+0.2987, +0.9048] |
| Fixed-window dense E5 | Source Recall@10 | 7 | +0.0714 [0.0000, +0.2143] |
| Fixed-window dense E5 | Source Recall@50 | 7 | +0.0714 [0.0000, +0.2143] |

The selected profile's evidence nDCG interval is above zero against all four baselines.
Paper nDCG intervals against Dense E5, Hybrid E5 and Fixed-window Dense E5 include
zero. The small sample and purposive selection limit the strength of these conclusions.

## v11 selected-profile acceptance gates

| Gate | Frozen limit | v11 aggregate | Result |
| --- | ---: | ---: | --- |
| Paper nDCG@10 | ≥ 0.80 | 0.9208 | Pass |
| Paper direct MRR@10 | ≥ 0.70 | 1.0000 | Pass |
| Paper judged Recall@20 | ≥ 0.90 | 1.0000 | Pass |
| Evidence nDCG@10 | ≥ 0.45 | 0.6682 | Pass |
| Evidence direct MRR@10 | ≥ 0.45 | 0.6357 | Pass |
| Evidence judged Recall@20 | ≥ 0.60 | 0.8737 | Pass |
| Source-anchor Recall@10 | ≥ 0.25 | 0.5556 | Pass |
| Source-anchor Recall@50 | ≥ 0.35 | 0.5556 | Pass |
| Positive source families with a hit at @10 | ≥ 0.50 | 0.5714 (4/7) | Pass |
| Hard-failure fraction | ≤ 0.01 | 0.0000 | Pass |
| Reranker-fallback fraction | ≤ 0.35 | 0.1000 | Pass |
| Warm p95 | ≤ 1,500 ms | 1,485.8 ms | Pass |
| Combined cold model load | ≤ 15,000 ms | 6,142.4 ms | Pass |
| Summed CUDA allocation | ≤ 1 GiB | 224,966,656 bytes | Pass |

The warm p95 cleared its frozen ceiling by 14.2 ms. Per-operation timing was:

| Operation | Samples | Median | p95 (nearest rank) |
| --- | ---: | ---: | ---: |
| Paper search | 50 | 1,208.2 ms | 1,480.4 ms |
| Evidence search | 50 | 1,188.3 ms | 1,492.7 ms |
| Combined selected profile | 100 | 1,201.3 ms | 1,485.8 ms |

The WSL-exposed GPU was an NVIDIA GeForce RTX 3050 Laptop GPU. Full
`create_phase2_runtime` startup, which constructs the local model/index runtime, was
8,900.3 ms; instrumented combined model load was 6,142.4 ms within that startup window.
Summed model-load CUDA allocation was 224,966,656 bytes; peak CUDA allocation/reservation
after replay was 278,103,552 / 329,252,864 bytes. Process peak RSS was 1,715,552,256
bytes. The acceptance replay reused existing indexes and did not measure index-build
cost; the development report records the build/chunking experiments. The BM25 lexical and hybrid artifacts each occupied
38,737,423 bytes; the fixed-window comparison artifacts occupied 28,179,129 bytes.
The reranked profile reuses the hybrid lexical artifact. Qdrant dense collection disk
use was not captured.

Across the selected profile's 20 primary attempts, hard failures were 0/20 and explicit
reranker fallback was 2/20 (10%). The harness's broader degradation flag was set for
20/20 attempts because any response warning marks an attempt degraded. All 100 warm
repeats completed without failure and result ordering was stable. This warning
classification is reported separately from hard failures and explicit fallbacks.

Evidence-requirement-group coverage was descriptive: seven groups, piece coverage 0.5556
at @10 and @50, and complete-group fraction 0.4286 at both cutoffs. No numeric group-
coverage gate was predeclared. Every frozen quality and operational gate passed.

## Reproduction and permissions

The private acceptance run was produced from the repository root with:

```bash
python local-reference/phase2-runs/benchmark-v11-private/run-heldout-evaluation-v11.py
```

Reproduction requires the ignored v11 benchmark/source-review files, the accepted local
snapshot and indexes, and the pinned model weights. Those files remain private and are
not part of the published change. The source snapshot retains its existing storage and
indexing permissions; public passage display is disabled. Hosted CI on the published
implementation and completion revisions verifies the CPU-only lint, formatting, type,
unit/integration, migration, dependency and Docker checks.

## Historical v10 assessment

The v10 assessment below is retained as historical evidence. It passed 14 of 15
frozen gates and missed warm p95 at 1,602.2 ms. Its set is spent and was not used for
v11 selection or tuning. Its item-level results remain private.

**Historical v10 status:** The v10 assessment passed 14 of 15 frozen gates and missed
warm p95 at 1,602.2 ms against a 1,500 ms maximum. This historical result was superseded
by the fresh v11 acceptance assessment above.

## Historical v10 decision

The v10 assessment is complete and spent. All quality, source-coverage, hard-failure,
reranker-fallback, cold-load and CUDA-allocation gates passed. The warm-latency gate
failed by 102.2 ms. The predeclared thresholds were not changed. No v10 item-level
result will be used to select or tune a profile. Phase 3 has not started.

At that time, the development-selected MiniLM-over-Hybrid-E5 profile remained the
serving candidate while acceptance was open. Any repair was required to use
calibration/development evidence, retain the locked strongest-passage paper aggregation
rule and numeric limits, and be assessed on a fresh source-reviewed held-out set. The
failed v10 gate was not used to inspect v10 families or change the profile from v10
scores.

## Frozen v10 inputs

| Field | Value |
| --- | --- |
| Assessment | `phase2-benchmark-v10`, ten held-out families |
| Selected profile | MiniLM reranking over Hybrid E5, rerank prefix 16, paper RRF rank constant 10 |
| Profile identity | `sha256:959e24b6ff6de711bbdfbf5020c5ac82a91cce43f48c8f52ba9d214c3e00e9be` |
| Published frozen profile SHA-256 | `652a4e2ed244eb991039d9db5f29435b8a9ac39c017dc5aabc832499ac22f355` |
| Acceptance config SHA-256 | `69c83710a8a3fad98e9f900a3c1d6946185a0e20291a347016a02fba41ef4191` |
| Question manifest SHA-256 | `6606593fa7fb26e2e180d25f0517c41899bd70593c3828c012e2852e257c510f` |
| Split manifest SHA-256 | `973fc191f2f9f0d4b036edae1aac7e14853736c831a814bfceffaabb297d9379` |
| Source review / judgments / map | `d37fb4c045ea3f35862e79afbbe641d43487ee1d35da873a803e55bb9289aa78` / `14204316524dd3e35a7f5f1bec6c1b44deacf958c7b697ddb3605c79afe4de49` / `6e86954fff8e7eacb571ca1a6d139af58ebe21bba027b69b7a80f95f7a3d8811` |
| Candidate review | 231 papers and 328 evidence candidates; all resolved |
| Positive source review | Nine direct anchors; ten direct pooled-candidate links across seven families |
| Snapshot | Accepted 100-paper snapshot; 44,277 selected evidence units |
| Run record SHA-256 | `abffece969be42b184e422411019035029ebcfdca32c0a064932df88b047d297` |
| Evaluated source revision | `ed56e59451203cc4ddaadfb6c4a070ba18260368`, tracked diff SHA-256 `7bc08fc0a0eee2cad24fcbe52aa37fa45c9ce74ca2554765725a40d54c3a96d0` |

The public frozen-profile manifest generalizes its descriptive family-set note to
protect opaque held-out family IDs. Its model, index, selection, threshold and benchmark
binding fields are unchanged from the evaluated freeze; the canonical profile ID and
private run record SHA-256 remain as recorded above.

The ten-family set is purposive and supports directional evidence, not precise
population estimates. Question identities, raw rankings, candidate text, per-family
results and run files remain in the ignored private directory. This report contains
sanitized aggregates only.

## Historical v10 aggregate profile comparison

Metrics are macro means over the ten held-out families except source-anchor recall,
which is micro recall over nine independently reviewed direct anchors. Latency is the
nearest-rank p95 across 100 warm requests per profile.

| Profile | Paper nDCG@10 | Paper direct MRR@10 | Paper Recall@20 | Evidence nDCG@10 | Evidence direct MRR@10 | Evidence Recall@20 | Source Recall@10 / @50 | Warm p95 (ms) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| BM25 lexical | 0.6960 | 0.7619 | 1.0000 | 0.5926 | 0.6071 | 0.8690 | 0.8889 / 0.8889 | 548.0 |
| Dense E5 | 0.8055 | 0.8571 | 0.8571 | 0.5864 | 0.5476 | 0.5476 | 0.5556 / 0.5556 | 947.6 |
| Hybrid E5 | 0.8353 | 0.8929 | 1.0000 | 0.6102 | 0.5833 | 0.6548 | 0.7778 / 0.7778 | 1,333.9 |
| MiniLM over Hybrid E5 (selected) | 0.8465 | 0.9286 | 1.0000 | 0.7040 | 0.6786 | 0.6905 | 0.7778 / 0.7778 | 1,602.2 |
| Fixed-window dense E5 | 0.8147 | 0.7429 | 0.8571 | 0.5574 | 0.5000 | 0.5238 | 0.4444 / 0.4444 | 412.8 |

## Historical v10 paired difference versus Hybrid E5

The bootstrap used 10,000 paired family resamples with seed 20260930. Deltas are
selected MiniLM-over-Hybrid-E5 minus Hybrid E5; intervals are percentile 95% intervals.

| Metric | Families | Mean delta | 95% interval |
| --- | ---: | ---: | ---: |
| Paper nDCG@10 | 10 | +0.0111 | [-0.0042, +0.0324] |
| Paper direct MRR@10 | 7 | +0.0357 | [0.0000, +0.1071] |
| Paper judged Recall@20 | 7 | +0.0000 | [0.0000, 0.0000] |
| Evidence nDCG@10 | 10 | +0.0938 | [+0.0447, +0.1463] |
| Evidence direct MRR@10 | 7 | +0.0952 | [0.0000, +0.2857] |
| Evidence judged Recall@20 | 7 | +0.0357 | [0.0000, +0.1071] |
| Source-anchor Recall@10 / @50 | 7 | +0.0000 / +0.0000 | [0.0000, 0.0000] / [0.0000, 0.0000] |

The profile comparison describes this spent set and does not authorize selection from
it. The paired evidence nDCG interval is positive; paper nDCG's interval includes
zero. Source recall matches Hybrid E5 on this sample.

## Historical v10 selected-profile category summaries

Categories overlap. Source recall is omitted where a category has no positive direct
source anchor.

| Category | Families | Paper nDCG@10 | Evidence nDCG@10 | Source Recall@10 (micro) |
| --- | ---: | ---: | ---: | ---: |
| Cross-paper comparison | 3 | 0.8947 | 0.7695 | 0.7500 |
| Discovery | 3 | 0.8174 | 0.6907 | 1.0000 |
| Filters | 8 | 0.8753 | 0.6705 | 0.7500 |
| Missing evidence | 3 | 0.8113 | 0.7923 | — |
| Specific evidence | 10 | 0.8465 | 0.7040 | 0.7778 |
| Table result | 5 | 0.8415 | 0.6369 | 0.6667 |

## Historical v10 selected-profile acceptance gates

| Gate | Frozen limit | v10 aggregate | Result |
| --- | ---: | ---: | --- |
| Paper nDCG@10 | ≥ 0.80 | 0.8465 | Pass |
| Paper direct MRR@10 | ≥ 0.70 | 0.9286 | Pass |
| Paper judged Recall@20 | ≥ 0.90 | 1.0000 | Pass |
| Evidence nDCG@10 | ≥ 0.45 | 0.7040 | Pass |
| Evidence direct MRR@10 | ≥ 0.45 | 0.6786 | Pass |
| Evidence judged Recall@20 | ≥ 0.60 | 0.6905 | Pass |
| Source-anchor Recall@10 | ≥ 0.25 | 0.7778 | Pass |
| Source-anchor Recall@50 | ≥ 0.35 | 0.7778 | Pass |
| Positive source families with a hit at @10 | ≥ 0.50 | 0.8571 (6/7) | Pass |
| Hard-failure fraction | ≤ 0.01 | 0.0000 (0/20) | Pass |
| Reranker-fallback fraction | ≤ 0.35 | 0.2000 (4/20) | Pass |
| Warm p95 | ≤ 1,500 ms | 1,602.2 ms | **Fail** |
| Combined cold model load | ≤ 15,000 ms | 5,606.9 ms | Pass |
| Summed CUDA allocation | ≤ 1 GiB | 224,966,656 bytes | Pass |

No requests failed during the selected profile's primary attempts or warm repeats.
The harness marks a returned request degraded when it contains any response warning;
20/20 selected-profile primary attempts carried at least one warning. This combines
routine selection/truncation diagnostics with actual mode fallbacks, so the warning
status is reported separately from the frozen hard-failure and explicit fallback
gates. Four of 20 primary requests used the unchanged Hybrid-E5 fallback. This status
classification should be made more specific in any future evaluation harness.

## Historical v10 runtime, unsupported behavior and limitations

The run used a WSL-exposed NVIDIA GeForce RTX 3050 Laptop GPU. Combined cold model
load was 5.61 s; E5 plus reranker allocated 224,966,656 bytes at load. Peak CUDA
allocated/reserved memory after replay was 278,363,648 / 329,252,864 bytes, and process
peak RSS was 1,727,795,200 bytes. The measured BM25 artifact used 38,737,423 bytes;
the fixed-window profile artifacts used 28,179,129 bytes. Qdrant collection disk use
was not captured.

For the selected profile, the three snapshot-scoped unsupported families returned 150
paper and 69 evidence results at the quality limit; none matched a positive source
anchor. Unsupported-query
cutoff remains disabled, so this measures ranking-only returned-hit behavior and does
not establish rejection accuracy. Evidence-requirement-group coverage was descriptive:
7 groups, piece coverage 0.7778 at ranks 10 and 50, complete-group fraction 0.7143 at
both cutoffs; no numeric gate was predeclared.

The 10-family set is purposive and cannot establish whole-literature retrieval quality.
Source-anchor recall covers only nine reviewed anchors, not all relevant passages.
All results are ranking measurements; no generated answer quality was tested.

## Previous held-out assessments

| Assessment | Result | Failed gates |
| --- | --- | --- |
| v7 | 12/14 | Paper nDCG@10; warm p95 |
| v8 | 13/14 | Evidence direct MRR@10 |
| v9 | 13/14 | Paper nDCG@10 |
| v10 | 14/15 | Warm p95 |

Earlier sets are also spent and cannot guide selection. Their item-level records remain
private. The v10 profile, threshold and result identities are recorded above; raw
artifacts are mode-restricted under ignored `local-reference/phase2-runs/`.

## Historical P2-19 verification

Local verification on the implementation worktree passed Ruff lint, Ruff formatting,
strict mypy, unit/API/evaluation and isolated PostgreSQL/Qdrant integration checks,
package audits, and a Docker build/image smoke check. Hosted CI passed on sanitized
implementation revision `8304b8a` ([run
36407122155](https://github.com/avsngh-git/RAGpipeline/actions/runs/36407122155)). The v10
assessment subsequently missed its warm-latency gate, as recorded above.

## Current project status

P2-20 is complete and Phase 2 is accepted after the fresh v11 assessment above. The
selected profile and all numeric limits remain as frozen. Every held-out set is spent
and sealed from tuning. Phase 3 has not started. Hosted CI passed on the sanitized
v11 completion revision `fefc04c` ([run
36420803867](https://github.com/avsngh-git/RAGpipeline/actions/runs/36420803867)).
