**Historical v3 report.** The current v4 assessment is in [phase-2-acceptance-report.md](phase-2-acceptance-report.md).

# Phase 2 held-out acceptance report

**Status:** Acceptance gate failed; Phase 2 is not accepted.

**Review:** Assistant-reviewed, 2026-09-27.

**Evaluation:** Frozen v3 held-out split; no retrieval settings were changed after scoring.

## Decision

The Phase 2 implementation and held-out assessment ran, but the selected profile failed
four frozen gates: paper nDCG@10, evidence nDCG@10, reranker fallback fraction, and
warm p95 latency. Ten of fourteen gates passed. The implementation remains available
for local use, but its frozen profile is provisional and must not be described as a
quality-accepted default.

Do not tune against this now-disclosed split. Any further retrieval selection must use
the development split and a newly assembled, reviewed held-out question set. Preserve
the v1 thresholds unless a separately documented change-control decision is approved
before the next evaluation.

## Frozen inputs and implementation identity

| Input | Identity |
| --- | --- |
| Acceptance | `phase2-acceptance-v1`; SHA-256 `6beb525c6a5d76b2bcf28dd0c03bce527872ca462ce44dceba4ea5ce383590bb` |
| Frozen profile manifest | SHA-256 `e2f96a8b3ee852a814d19465923d0e04a86abd5e7838d93e0c33c6da31892bc8` |
| Held-out manifest | SHA-256 `d4b13f0a63b732f9b7b3a35a50e6e509c463dc20cdcc95b42a085170b21f653b` |
| Split manifest | SHA-256 `d33d66256512aeea5b21168877e5f01b990b8c42f75443948ace328e16607bba` |
| Assistant source judgments | SHA-256 `85abf63ccbe5b5deadb3ac94b340788bfcc6913a2fb8d4ee6523b0c70fd9f9f5` |
| Exact source-to-chunk map v7 | SHA-256 `720cd6cd8f36929ea17e1f5043ad21d308740af226385f4425584294d7dcbd73` |
| Code revision | `0ea87098608f24c14f518c370f2f5a65c488d7c5`; tracked worktree clean during evaluation |
| Private runner | SHA-256 `0f4b53ef14221c0bdd415cce290f00e17d81b545b46178d6729cd1462ac0e9d8` |
| Evaluation snapshot | `4b11fab3-d4a5-4e7a-a58e-8654accf2c6c`; selection identity `sha256:cc5b7c30962ce66ad279a5ff95b0e1e6dd8aede68980292717d1a7a23ecd6f18` |

The comparison profile identities and frozen model/index settings are:

| Comparison | Profile identity | Frozen components |
| --- | --- | --- |
| BM25 lexical | `sha256:f36849d5b7ce411a2ddbc35f5516b9462a5948bf9651728ac84a65005922b5e6` | BM25S 0.3.11; `scientific-en-v1` analyzer |
| E5 dense | `sha256:1eb792e949142afbd45a34b081149565fd273156fdcf2f21f5c456f845736884` | E5-small-v2 revision `e8b23a92af33fd81c865283d505f8f058a570cc8`; 384 dimensions; 512-token input |
| Hybrid E5 | `sha256:29cc1cc6a9b78758f518d76df391859433b9cd034b9ef1f71f8ede30009cb5fa` | E5-small-v2 plus BM25S; RRF rank constant 60 |
| MiniLM reranked Hybrid E5 | `sha256:243e3d5923ee930940a29cf4ba79db2392cf4a5bfe777a54cedd2a316fd22870` | Cross-encoder MiniLM-L6-v2 revision `233902d25c440f23af6f7d6e94d2946bac0bee0a`; all-or-fallback pair policy; batch size 4 |
| Fixed-window E5 dense | `sha256:c2c7429ca329014e1d2b24f3dfd958cb461d93f5315a2977d5e23b9681b7f785` | E5-small-v2 on the fixed-window comparison snapshot |

The selected configuration uses a 50-candidate pool, 10-result service default,
strongest-passage paper selection, five supporting evidence items per paper, five
items per paper in evidence results, and no unsupported-query cutoff. Its E5 index
configuration is `sha256:21cb8e4df7f24affb524a84a788f275fa54b08076d519afb1ecf5961ac88ee02`,
the lexical index configuration is
`sha256:5e38809545dc6b4a09110767a7ff4b576bc48971de2f4573baa797a0ba8caa14`, and the
snapshot index configuration is
`sha256:4d6a82110a37bd21974bd5fcc0aeae416b2996b79082b6645e6d39e7720f5ca7`. Its text
budget tokenizer is `unicode-token-v1`. The fixed-window comparison used snapshot
`c3447473-a9f7-4d8c-93c0-e45ebcab763f` and selection identity
`sha256:7a17675a8ee27f512b115d23f4d9dec23fc73e8ca8fe272bdc21ed68919919a4`. The
accepted Phase 2 index is separate from the retained Phase 1 index.

Hosted P2-19 CI passed on the sanitized public branch at
[`b1c1232`](https://github.com/avsngh-git/RAGpipeline/actions/runs/36344475763).
That public-safe revision contains the evaluated retrieval code and configuration;
private held-out question manifests and source review files remain local.

Several nonfinal local runner invocations stopped before producing an assessment
artifact. One full request replay stopped during null-metric aggregation; the corrected
runner replayed the same frozen inputs and produced the sole result artifact used here.
No retrieval configuration, query, judgment, threshold, or source mapping changed.
The recorded assessment ran from 2026-09-27 20:36:40Z to 20:45:04Z.

## Benchmark and scoring

The held-out set contains 10 assistant-reviewed question families across overlapping
categories: discovery (3), specific evidence (8), table results (3), cross-paper
comparison (4), filters (8), and missing evidence (3). It has 245 judged paper
candidates (181 label 0, 52 label 1, 12 label 2) and 1,581 judged evidence candidates
(883 label 0, 607 label 1, 91 label 2). Source review covers 21 anchors and 34
candidate links; 17 anchors have direct-positive label 2. No required evidence groups
were defined, so group coverage is not measurable on this version.

Paper metrics use the project `evaluation-scoring-policy-v1` scorer. Source metrics
use the frozen v7 mapping from reviewed source candidates to exact selected chunk
identities, validated against candidate content hashes and source lineage before
retrieval. A hit receives source credit only when its returned chunk or source ID is
one of the mapped identities for that profile’s chunk variant. This is a strict direct
identity match: it does not credit a different chunk merely because its text overlaps
an anchor. Evidence nDCG uses anchor-level gain, caps gain per rank at label 2, and
uses distinct positive anchors for the ideal ranking. Evidence MRR and recall use the
17 label-2 anchors. Unjudged results receive zero gain; report judgment coverage with
the conservative judged-pool scores.

The 10-family sample is small and assistant-reviewed without an independent second
annotator. Paired bootstrap intervals are directional, not confirmatory. Bootstrap
resampling used 10,000 family-level draws with seed `20260927`. The unsupported-query
cutoff remained disabled; no rejection-accuracy result is claimed.

## Retrieval results

Quality values are macro means over answerable families where a positive denominator
is required; nDCG uses all scored families. Source-anchor recall and judgment coverage
are micro means. Warm p95 uses nearest rank over 100 repeated requests per profile
(50 paper and 50 evidence requests). Requests ran sequentially: one warm-up pass,
one primary scoring pass, and five measured repeats for each of the ten families and
two operations.

| Profile | Paper nDCG@10 | Paper MRR@10 | Paper Recall@20 | Evidence nDCG@10 | Evidence MRR@10 | Evidence Recall@20 | Source Recall@10 / @50 | Judgment coverage paper / evidence | Warm p95 ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| BM25 lexical | 0.6241 | 0.7542 | 0.9375 | 0.1113 | 0.1667 | 0.1875 | 0.1176 / 0.1176 | 0.8160 / 0.0116 | 530.2 |
| E5 dense | 0.7203 | 0.8750 | 0.8750 | 0.2151 | 0.2604 | 0.3750 | 0.2353 / 0.2353 | 1.0000 / 0.0265 | 929.8 |
| Hybrid E5 | 0.7116 | 0.7292 | 0.9375 | 0.1938 | 0.2292 | 0.3125 | 0.1765 / 0.1765 | 0.8812 / 0.0192 | 1,217.9 |
| MiniLM reranked Hybrid E5 (selected) | 0.7249 | 0.7500 | 0.9375 | 0.3314 | 0.4729 | 0.6500 | 0.3529 / 0.4706 | 0.8812 / 0.0596 | 1,541.2 |
| Fixed-window E5 dense | 0.7174 | 0.8750 | 0.8750 | 0.2551 | 0.3542 | 0.3750 | 0.2353 / 0.2353 | 0.9884 / 0.0714 | 344.9 |

The selected profile retrieved 6 of 17 direct-positive source anchors by rank 10 and
8 of 17 by rank 50. Its paper and evidence judgment coverage were 230/261 (88.12%) and
9/151 (5.96%), respectively. Low evidence coverage means most returned chunks were
outside this reviewed exact-match pool; it is not evidence that those chunks are
irrelevant. The selected profile improved evidence ranking over each named baseline,
while paper nDCG remained below its frozen floor.

### Paired family bootstrap: selected profile minus baseline

Intervals are percentile 95% intervals over paired family resamples. `n` is the
number of families with defined values for that metric.

**Paper metrics**

| Baseline | Δ nDCG@10 (95% CI), n=10 | Δ MRR@10 (95% CI), n=8 | Δ Recall@20 (95% CI), n=8 |
| --- | --- | --- | --- |
| BM25 lexical | +0.1008 [+0.0151, +0.1981] | -0.0042 [-0.3333, +0.2417] | 0.0000 [0.0000, 0.0000] |
| E5 dense | +0.0046 [-0.0732, +0.0893] | -0.1250 [-0.3125, 0.0000] | +0.0625 [0.0000, +0.1875] |
| Hybrid E5 | +0.0133 [-0.0193, +0.0570] | +0.0208 [0.0000, +0.0625] | 0.0000 [0.0000, 0.0000] |
| Fixed-window E5 dense | +0.0075 [-0.1107, +0.1228] | -0.1250 [-0.2500, 0.0000] | +0.0625 [0.0000, +0.1875] |

**Evidence and source metrics**

| Baseline | Δ nDCG@10 (95% CI), n=10 | Δ MRR@10 (95% CI), n=8 | Δ Recall@20 (95% CI), n=8 | Δ Source Recall@10 (95% CI), n=8 | Δ Source Recall@50 (95% CI), n=8 |
| --- | --- | --- | --- | --- | --- |
| BM25 lexical | +0.2200 [+0.0080, +0.4631] | +0.3063 [-0.1104, +0.7167] | +0.4625 [+0.1500, +0.7750] | +0.3375 [+0.0625, +0.6500] | +0.4625 [+0.1500, +0.7750] |
| E5 dense | +0.1163 [-0.0162, +0.2445] | +0.2125 [-0.0292, +0.5000] | +0.2750 [+0.0625, +0.5250] | +0.1500 [-0.1250, +0.4625] | +0.2750 [+0.0625, +0.5250] |
| Hybrid E5 | +0.1376 [-0.0057, +0.2977] | +0.2438 [-0.0438, +0.5875] | +0.3375 [+0.0625, +0.6500] | +0.2125 [0.0000, +0.4625] | +0.3375 [+0.0625, +0.6500] |
| Fixed-window E5 dense | +0.0763 [-0.0627, +0.2120] | +0.1188 [-0.1208, +0.4167] | +0.2750 [+0.0625, +0.5250] | +0.1500 [-0.1250, +0.4625] | +0.2750 [+0.0625, +0.5250] |

Most paired intervals include zero, consistent with a directional result from a small
sample. They do not support a broad superiority claim.

### Category view for the selected profile

Categories overlap; these are descriptive aggregates, not additional gates.

| Category | Families | Paper nDCG@10 | Evidence nDCG@10 | Source Recall@10 |
| --- | ---: | ---: | ---: | ---: |
| Discovery | 3 | 0.7395 | 0.2420 | 0.2500 |
| Specific evidence | 8 | 0.7524 | 0.4142 | 0.4000 |
| Table results | 3 | 0.9270 | 0.5791 | 0.7500 |
| Cross-paper comparison | 4 | 0.7309 | 0.2299 | 0.2222 |
| Filters | 8 | 0.7909 | 0.3846 | 0.3529 |
| Missing evidence | 3 | 0.4444 | 0.0791 | 0.0000 |

### Missing-evidence returned-hit profile

The cutoff is disabled, so these counts describe rankings and do not measure rejection
accuracy. Each of the three missing-evidence families requested up to 50 results.

| Profile | Paper hits returned | Evidence hits returned | Exact source-anchor matches |
| --- | ---: | ---: | ---: |
| BM25 lexical | 148 | 74 | 0 |
| E5 dense | 43 | 66 | 0 |
| Hybrid E5 | 150 | 64 | 0 |
| MiniLM reranked Hybrid E5 | 150 | 56 | 1 |
| Fixed-window E5 dense | 35 | 16 | 0 |

## Frozen acceptance gates

| Gate | Frozen requirement | Result | Status |
| --- | ---: | ---: | --- |
| Paper nDCG@10 | ≥ 0.80 | 0.7249 | **Fail** |
| Paper direct MRR@10 | ≥ 0.70 | 0.7500 | Pass |
| Paper judged Recall@20 | ≥ 0.90 | 0.9375 | Pass |
| Evidence nDCG@10 | ≥ 0.45 | 0.3314 | **Fail** |
| Evidence direct MRR@10 | ≥ 0.45 | 0.4729 | Pass |
| Evidence judged Recall@20 | ≥ 0.60 | 0.6500 | Pass |
| Source-anchor Recall@10 (micro) | ≥ 0.25 | 0.3529 | Pass |
| Source-anchor Recall@50 (micro) | ≥ 0.35 | 0.4706 | Pass |
| Positive source families with a hit by rank 10 | ≥ 0.50 | 0.7500 (6/8) | Pass |
| Hard failure fraction | ≤ 0.01 | 0/20 | Pass |
| Reranker fallback fraction | ≤ 0.35 | 8/20 = 0.4000 | **Fail** |
| Warm p95 | ≤ 1,500 ms | 1,541.2 ms | **Fail** |
| Combined cold model load | ≤ 15,000 ms | 5,153.0 ms | Pass |
| Summed CUDA allocated model memory | ≤ 1 GiB | 224,966,656 bytes | Pass |

No profile had a hard primary failure or warm-repeat failure. All 20 primary requests
per profile were marked degraded because each returned warnings; all 10 paper and all
10 evidence primary requests were truncated under the frozen 50-result bound. The
selected reranker completed in the requested mode for 12/20 primary requests and fell
back to Hybrid E5 for 8/20. Rank order was stable across all 100 warm repeats for each
profile. These degraded/truncated results are reported separately from hard failures.

## Runtime, storage, and replay

- Device: NVIDIA GeForce RTX 3050 Laptop GPU; CUDA available.
- In-process runtime startup: 8,181 ms.
- Cold E5 model load: 4,699.9 ms; MiniLM reranker load: 453.1 ms; combined: 5,153.0 ms.
- Summed model allocation delta: 224,966,656 bytes; combined peak allocated: 276,493,312 bytes; peak reserved: 325,058,560 bytes.
- Process peak RSS: 1,734,623,232 bytes. CPU thread counts and per-query cold index-build cost were not measured in this held-out replay; index build/reconciliation evidence is recorded in the Phase 2 implementation and development reports.
- BM25-only and Hybrid E5 lexical artifact directories: 38,737,423 bytes each. Fixed-window local profile artifacts: 28,179,129 bytes.
- Disposable Qdrant `/qdrant/storage` directory: 2,971,084,445 bytes. This is the directory total, not an isolated collection-size measurement.
- Dense Phase 2 index reconciliation from P2-19 covered 44,277 selected evidence units. The Phase 1 accepted index was retained.

The private, mode-0600 raw record is kept outside Git at
`local-reference/phase2-runs/p2-20-acceptance/heldout-run-20260927T204504Z.json`
(SHA-256 `3943a88fd4ce8911d52f6c8585fffd493edb8d791ebeae295c1fd4eda34fcf1c`). It
contains private result identities and ranks; it must not be published. The query
manifest, source-review cards and chunk map also remain local. With those private
inputs and the disposable local services prepared, the replay command is:

```bash
PYTHONPATH=src conda run --no-capture-output -n sci_research_agent \
  python local-reference/phase2-runs/p2-20-acceptance/run-heldout-evaluation.py
```

The runner uses offline cached weights and does not use paid compute or make model
network requests. The unsupported-query cutoff remains disabled, so rejection
accuracy is not evaluated.

## Next phase boundary

P2-19 implementation verification is complete, including hosted CI. P2-20 produced a
complete and auditable assessment, but its acceptance gate failed. Phase 2 therefore
remains unaccepted. Use development data to improve the system, then freeze the next
configuration and thresholds before assembling a new held-out version. A future
assessment needs new held-out questions; v3 is now disclosed and cannot serve as an
unseen test again. Record any accepted model or lexical default in an ADR only after a
new frozen gate passes.
