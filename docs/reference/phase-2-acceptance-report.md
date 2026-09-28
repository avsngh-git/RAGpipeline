# Phase 2 held-out acceptance report

**Status:** Phase 2 remains unaccepted. The fresh v10 assessment passed 14 of 15
frozen gates; selected-profile warm p95 was 1,602.2 ms against a 1,500 ms maximum.
P2-01–P2-19 implementation and local verification are complete. Hosted CI for the
current publication revision is pending; P2-20 acceptance remains open.

## Decision

The v10 assessment is complete and spent. All quality, source-coverage, hard-failure,
reranker-fallback, cold-load and CUDA-allocation gates passed. The warm-latency gate
failed by 102.2 ms. The predeclared thresholds were not changed. No v10 item-level
result will be used to select or tune a profile. Phase 3 has not started.

The development-selected MiniLM-over-Hybrid-E5 profile remains the serving candidate
while acceptance is open. Any repair must use calibration/development evidence, retain
the locked strongest-passage paper aggregation rule and the numeric limits, and be
assessed on a fresh source-reviewed held-out set. The current failed gate is not a
basis for inspecting v10 families or changing the profile from v10 scores.

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

## Aggregate profile comparison

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

## Paired difference versus Hybrid E5

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

## Selected-profile category summaries

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

## Selected-profile acceptance gates

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

## Runtime, unsupported behavior and limitations

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

## P2-19 verification and next step

Local verification on the current worktree passed Ruff lint, Ruff formatting, strict
mypy (79 source files), 424 non-integration tests and 21 integration tests against
fresh no-volume PostgreSQL/Qdrant services. `pip check` passed in the Conda environment
and built image. `pip_audit --skip-editable` found no known vulnerabilities; the
editable project distributions were skipped. The Docker image built with a 36.69 KB
context; its CLI, BM25S/NumPy imports and v8 frozen-profile loader passed smoke checks.
No dependency lock or runtime dependency changed in this update. Hosted CI for the
current publication revision is pending.

P2-20 remains open because the frozen held-out gate failed. Use development-only
measurements for any performance investigation and preserve the thresholds. Any later
acceptance assessment must use a fresh, source-reviewed held-out set frozen before
scoring. Do not inspect v10 item-level outcomes or reuse v10 as an unseen test.
