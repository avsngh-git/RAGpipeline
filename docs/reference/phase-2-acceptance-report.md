# Phase 2 held-out acceptance report

**Current status — Phase 2 accepted. The one-time R8 v14 held-out assessment (30
families, `phase2-acceptance-v14`) passed all 16 gates on 2026-09-30.** The selected
profile is `frozen-profile-v10` (gte-modernbert-base + BM25S hybrid + Ettin-150M
reranker; [ADR-0017](../adr/0017-phase2-accepted-profile-v10.md)). Three quality gates
passed by narrow margins well inside sampling noise, and the gates were lowered after v13
failed (see the caveats in the v14 section). v3–v13 are historical and unchanged: each is
judged under its own frozen gates, and v13 stays failed under them. Held-out questions,
source excerpts, candidate text, item-level judgments, rankings and raw run records remain
private. Phase 3 has not started.

## R8 v14 result — assistant-reviewed 2026-09-30

**Result: PASS, 16 of 16 gates.** The one-time frozen assessment used
`phase2-benchmark-v14` (30 families) with the selected profile
`sha256:52a152db9fb350c91810353650864eaffef0b3fe148fde9781956373d3fe5449`
(`frozen-profile-v10`), on the accepted snapshot `4b11fab3-d4a5-4e7a-a58e-8654accf2c6c`.
The run used the freeze commit `82694aa` on a clean worktree and the RTX 3050 Laptop GPU
(4 GB). Hosted CI run
[36740163129](https://github.com/avsngh-git/RAGpipeline/actions/runs/36740163129) passed on
that commit. **v14 is now spent and sealed from tuning.**

### Method

- **Acceptance method ([ADR-0014](../adr/0014-phase2-acceptance-method.md)).** One fresh,
  assistant-reviewed held-out set of 30 families, frozen before scoring; a coverage-only
  pre-check before freeze; a single run; gates judged on point estimates, with paired
  family-bootstrap 95% intervals reported beside them (10,000 resamples, seed 20260930);
  descriptive BM25 difficulty band; sealing after the run.
- **Gate revision ([ADR-0015](../adr/0015-phase2-acceptance-gate-revision.md)).** Owner-approved
  on 2026-09-30, from development data only and after v13 failed. Paper nDCG@10 0.80 to
  0.65, evidence nDCG@10 0.45 to 0.40 and evidence judged Recall@20 0.60 to 0.50;
  evidence direct MRR@10 stays at 0.45. Two relative gates are added: the paired 95% lower
  bound of the selected profile's gain over BM25 must exceed 0 for paper and for evidence
  nDCG@10. That makes 16 gates (the original 14 plus the two relative ones). The inclusive
  context rule (label 1 = useful context or incomplete support) applies to every label.
- **Warm latency ([ADR-0016](../adr/0016-phase2-warm-latency-5000ms.md)).** Maximum warm
  p95 is 5,000 ms; the separate 30-second request deadline is unchanged.
- **Timing.** The selected profile ran three sessions (366 measured requests; median
  789.9 ms); each comparator ran one session (122 requests). Concurrency 1, four CPU
  threads, `auto` device, result limit 10.

### Frozen v14 identities

| Field | Value |
| --- | --- |
| Freeze commit | `82694aa` (hosted CI run 36740163129, green) |
| Freeze manifest SHA-256 | `c42c1113938cb6dcdd2947f1d260c39ad5160eb0497fa3ad5e790af510e8d052` ([`r8-v14-freeze-v1.toml`](../../benchmarks/phase2/r8-v14-freeze-v1.toml)) |
| Acceptance config SHA-256 | `5cef7e1174a83f5474779b3deaf08a797efc2170d7df855a5173a2ef93603482` ([`acceptance-v14.toml`](../../benchmarks/phase2/acceptance-v14.toml)) |
| Frozen profile | [`frozen-profile-v10.toml`](../../benchmarks/phase2/frozen-profile-v10.toml); profile identity `sha256:52a152db9fb350c91810353650864eaffef0b3fe148fde9781956373d3fe5449` |
| Held-out dataset SHA-256 | `2f36323141f9cce1c539a8d70a6d91adb63491a4d959b412539edfc00eceb176` |
| Source-alignment SHA-256 | `208f3e472089094a7348ea36881e7c53b5706668301c55f88209e19856cd15b3` |
| Private raw run record SHA-256 | `c26f096d3aeb6d1f34e0073de1c7e30b02771882304d589091e50675138c5036` |
| Snapshot | `4b11fab3-d4a5-4e7a-a58e-8654accf2c6c`, 100 papers, 44,277 selected chunks |

The raw record, dataset, alignment and review files stay in the ignored private
`local-reference/` directory. This report holds sanitized aggregates only: no family IDs,
question text, candidate IDs, rankings or per-family values.

### Selected-profile gates

Margin is the observed value minus the limit (limit minus value for maxima). The interval
column is the 95% bootstrap interval of the selected profile's own family-level mean: 10,000
family resamples, nearest-rank percentiles, seed 20260930 plus the metric's position in
the runner's list. The raw record stores only paired intervals against baselines, so the
closeout derived these intervals from it, using the same resampling scheme and publishing
only the aggregate bounds. They are descriptive; no gate is passed or failed on an interval.
Source-anchor recall and the positive-family fraction pool anchors that cluster within
families, so no interval is given for them. The two relative gates are themselves lower
bounds.

| Gate | Limit | v14 aggregate | Margin | 95% interval | Result |
| --- | ---: | ---: | ---: | ---: | --- |
| Paper nDCG@10 | ≥ 0.65 | 0.6522 | +0.0022 | [0.5592, 0.7420] | Pass |
| Paper direct MRR@10 | ≥ 0.70 | 0.7811 | +0.0811 | [0.6683, 0.8846] | Pass |
| Paper judged Recall@20 | ≥ 0.90 | 0.9499 | +0.0499 | [0.9082, 0.9850] | Pass |
| Evidence nDCG@10 | ≥ 0.40 | 0.4074 | +0.0074 | [0.3417, 0.4710] | Pass |
| Evidence direct MRR@10 | ≥ 0.45 | 0.5887 | +0.1387 | [0.4434, 0.7260] | Pass |
| Evidence judged Recall@20 | ≥ 0.50 | 0.5122 | +0.0122 | [0.3759, 0.6513] | Pass |
| Source-anchor Recall@10 | ≥ 0.25 | 0.5714 (72/126) | +0.3214 | — | Pass |
| Source-anchor Recall@50 | ≥ 0.35 | 0.6508 (82/126) | +0.3008 | — | Pass |
| Positive source families with a hit at @10 | ≥ 0.50 | 0.8462 (22/26) | +0.3462 | — | Pass |
| Hard-failure fraction | ≤ 0.01 | 0.0000 | 0.0100 | — | Pass |
| Reranker-fallback fraction | ≤ 0.35 | 0.0000 | 0.3500 | — | Pass |
| Warm p95 | ≤ 5,000 ms | 1,016.06 ms | 3,983.94 ms | — | Pass |
| Combined cold model load | ≤ 15,000 ms | 6,517 ms | 8,483 ms | — | Pass |
| Summed CUDA allocation | ≤ 1 GiB | 634,404,864 B | 439,336,960 B | — | Pass |
| Paper nDCG@10 gain over BM25, 95% lower bound | > 0 | 0.1690 (mean +0.2258) | +0.1690 | [0.1690, 0.2853] | Pass |
| Evidence nDCG@10 gain over BM25, 95% lower bound | > 0 | 0.0961 (mean +0.1592) | +0.0961 | [0.0961, 0.2221] | Pass |

Direct MRR and judged Recall use the 26 positive families; nDCG uses all 30. Cold load
splits into 5,603.6 ms (gte) and 913.8 ms (Ettin); the measured runtime startup was
10,424.9 ms and is not a gate.

### Baselines and category results

Baseline rows are descriptive and do not authorize tuning from v14. The selected row is
repeated for comparison.

| Profile | Paper nDCG@10 | Evidence nDCG@10 | Source Recall@10 / @50 | Warm p95 |
| --- | ---: | ---: | ---: | ---: |
| BM25 lexical | 0.4264 | 0.2482 | 0.3095 / 0.3810 | 634.1 ms |
| Dense gte | 0.7183 | 0.3610 | 0.5476 / 0.5556 | 710.9 ms |
| Hybrid gte | 0.6523 | 0.3644 | 0.5556 / 0.6587 | 799.3 ms |
| Selected: reranked gte-ettin hybrid | 0.6522 | 0.4074 | 0.5714 / 0.6508 | 1,016.1 ms |
| Fixed-window dense E5 | 0.6672 | 0.2380 | 0.3730 / 0.3810 | 423.3 ms |

Selected-profile categories (overlapping; source recall is micro over anchors and is
omitted for missing evidence, which has none):

| Category | Families | Paper nDCG@10 | Evidence nDCG@10 | Source Recall@10 |
| --- | ---: | ---: | ---: | ---: |
| Cross-paper comparison | 5 | 0.5542 | 0.3202 | 0.3600 |
| Discovery | 6 | 0.7848 | 0.4474 | 0.3750 |
| Filters | 5 | 0.7449 | 0.3816 | 0.3214 |
| Missing evidence | 4 | 0.1786 | 0.2057 | — |
| Specific evidence | 15 | 0.7581 | 0.4743 | 0.7869 |
| Table result | 10 | 0.7591 | 0.4516 | 0.8095 |

Category cells rest on 4 to 15 families, so they are descriptive. Missing-evidence paper
nDCG scores a ranking against judged context only; it is not a rejection-accuracy measure
(the unsupported-query cutoff stays disabled).

### Paired differences and uncertainty

Deltas are selected minus each baseline; intervals are percentile 95% intervals from
10,000 paired family resamples (seed 20260930). Direct-MRR, Recall@20 and source rows use
the 26 positive families (source rows use per-family recall); nDCG rows use 30.

| Baseline | Metric | Families | Mean delta [95% interval] |
| --- | --- | ---: | ---: |
| BM25 lexical | Paper nDCG@10 | 30 | +0.2258 [+0.1690, +0.2853] |
| BM25 lexical | Paper direct MRR@10 | 26 | +0.2351 [+0.1614, +0.3122] |
| BM25 lexical | Paper judged Recall@20 | 26 | +0.2472 [+0.1522, +0.3480] |
| BM25 lexical | Evidence nDCG@10 | 30 | +0.1592 [+0.0961, +0.2221] |
| BM25 lexical | Evidence direct MRR@10 | 26 | +0.3605 [+0.2329, +0.4919] |
| BM25 lexical | Evidence judged Recall@20 | 26 | +0.3075 [+0.1825, +0.4389] |
| BM25 lexical | Source-anchor Recall@10 | 26 | +0.3250 [+0.1795, +0.4744] |
| BM25 lexical | Source-anchor Recall@50 | 26 | +0.2996 [+0.1560, +0.4573] |
| Dense gte | Paper nDCG@10 | 30 | -0.0661 [-0.1205, -0.0148] |
| Dense gte | Paper direct MRR@10 | 26 | -0.0989 [-0.2037, +0.0080] |
| Dense gte | Paper judged Recall@20 | 26 | -0.0173 [-0.0493, +0.0109] |
| Dense gte | Evidence nDCG@10 | 30 | +0.0464 [+0.0191, +0.0728] |
| Dense gte | Evidence direct MRR@10 | 26 | +0.1530 [+0.0481, +0.2630] |
| Dense gte | Evidence judged Recall@20 | 26 | +0.0768 [+0.0253, +0.1364] |
| Dense gte | Source-anchor Recall@10 | 26 | +0.0600 [-0.0122, +0.1436] |
| Dense gte | Source-anchor Recall@50 | 26 | +0.1013 [+0.0359, +0.1795] |
| Hybrid gte | Paper nDCG@10 | 30 | -0.0001 [-0.0265, +0.0238] |
| Hybrid gte | Paper direct MRR@10 | 26 | +0.0359 [-0.0018, +0.0776] |
| Hybrid gte | Paper judged Recall@20 | 26 | -0.0032 [-0.0096, +0.0000] |
| Hybrid gte | Evidence nDCG@10 | 30 | +0.0430 [+0.0095, +0.0752] |
| Hybrid gte | Evidence direct MRR@10 | 26 | +0.2036 [+0.0964, +0.3177] |
| Hybrid gte | Evidence judged Recall@20 | 26 | +0.0787 [+0.0159, +0.1468] |
| Hybrid gte | Source-anchor Recall@10 | 26 | +0.0458 [-0.0215, +0.1231] |
| Hybrid gte | Source-anchor Recall@50 | 26 | +0.0138 [-0.0413, +0.0705] |
| Fixed-window dense E5 | Paper nDCG@10 | 30 | -0.0150 [-0.0828, +0.0485] |
| Fixed-window dense E5 | Paper direct MRR@10 | 26 | -0.0827 [-0.2103, +0.0457] |
| Fixed-window dense E5 | Paper judged Recall@20 | 26 | +0.0393 [+0.0064, +0.0768] |
| Fixed-window dense E5 | Evidence nDCG@10 | 30 | +0.1694 [+0.1173, +0.2248] |
| Fixed-window dense E5 | Evidence direct MRR@10 | 26 | +0.2108 [+0.0813, +0.3480] |
| Fixed-window dense E5 | Evidence judged Recall@20 | 26 | +0.1615 [+0.0628, +0.2660] |
| Fixed-window dense E5 | Source-anchor Recall@10 | 26 | +0.1856 [+0.0731, +0.3064] |
| Fixed-window dense E5 | Source-anchor Recall@50 | 26 | +0.2247 [+0.1080, +0.3487] |

Reading: the selected profile beats BM25 on every metric with intervals above zero. It
beats dense gte and hybrid gte on evidence nDCG@10 and evidence direct MRR@10 (intervals
above zero), but does not beat dense gte on paper ranking (below).

### Composition, coverage and review

The set has 30 families: 26 positive and 4 missing-evidence. Category membership overlaps:
discovery 6, specific evidence 15, table result 10, filters 5, cross-paper comparison 5,
missing evidence 4. Modalities: 8 direct-positive prose, 6 numeric-table, 5 negative or
mixed findings. There are 126 positive anchors (88 source-first builder anchors across 26
families and 38 pool-found label-2 anchors). See the [dataset card](phase-2-benchmark-dataset-card.md)
for construction.

Coverage pre-check (judged fraction of returned results, passed before freeze). Paper
coverage was 1.000 at top 10 and top 20 for every profile. The selected profile's lowest
per-family coverage at top 10 was 1.000 for papers and 0.933 for evidence, above the 0.80
floor.

| Profile | Evidence @10 | Evidence @20 |
| --- | ---: | ---: |
| BM25 | 0.998 | 0.998 |
| Dense gte | 1.000 | 1.000 |
| Hybrid gte | 0.998 | 0.999 |
| Selected | 0.998 | 0.999 |
| Fixed-window | 0.994 | 0.994 |

Judged fraction over all returned results (macro across 30 families; up to 50 results, while
pooling went to depth 20 for papers and 50 for evidence):

| Profile | Paper | Evidence |
| --- | ---: | ---: |
| BM25 | 0.824 | 0.996 |
| Dense gte | 0.990 | 1.000 |
| Hybrid gte | 0.884 | 0.997 |
| Selected | 0.884 | 0.998 |
| Fixed-window | 0.977 | 0.993 |

Unjudged results carry zero gain under the conservative judged-pool convention. Paper
ranks 21–50 are the unjudged ones and affect neither nDCG@10 nor Recall@20. Five
builder/reviewer disagreements were adjudicated against the PDF pages by a third assistant
judge (the reviewer's label was corrected in each), and one further record fixed a
requirement-piece mapping. Pooled candidates from the five declared profiles were judged blind to profile and rank.

### Baseline context

BM25 paper nDCG@10 (0.4264) is below the descriptive band 0.50–0.85; evidence nDCG@10
(0.2482) is below 0.25–0.75. The runner flagged "set difficulty unusual". This is
descriptive only and changes no gate. A weak BM25 baseline lowers the bar for the two
relative-to-BM25 gates, so read their margins with that in mind.

### Limitations and caveats

- **Narrow margins.** Paper nDCG@10 passed by 0.002, evidence nDCG@10 by 0.007 and
  evidence judged Recall@20 by 0.012. Each margin is far inside sampling noise: the 95%
  intervals are [0.5592, 0.7420], [0.3417, 0.4710] and [0.3759, 0.6513], and each contains
  its threshold. A rerun on a different fresh set could fall on either side. Judged by the
  pre-registered point-estimate rule, these gates passed; they do not show that the true
  quality exceeds the limits.
- **Gates lowered after a failure.** Paper nDCG@10, evidence nDCG@10 and evidence judged
  Recall@20 were lowered from 0.80, 0.45 and 0.60 by owner-approved
  [ADR-0015](../adr/0015-phase2-acceptance-gate-revision.md) after v13 failed 10 of 14
  gates, using development data only. v13's aggregates were known when the values were
  chosen, so v13 stays failed under its own gates and the new values apply only to this
  fresh set. The absolute floors are project-local quality guards, not field standards.
  Warm p95 moved from 2,000 ms to 5,000 ms (ADR-0016).
- **Difficulty flag.** The BM25 band was out of range (above), so the set's difficulty is
  unusual relative to the pre-registered reference band.
- **Dense gte ranks papers better.** Dense gte alone scored paper nDCG@10 0.7183 against the
  selected 0.6522 (selected minus dense −0.0661, 95% interval [−0.1205, −0.0148]), and
  higher paper direct MRR (−0.0989 [−0.2037, +0.0080] for the selected). The selected
  profile ranks evidence better (+0.0464 [+0.0191, +0.0728]). Improving paper ordering is a
  known target; the hybrid pipeline stays as locked in section 9.1 of the source of truth.
- **Labels are assistant-reviewed.** No human verification is claimed. The owner spot-checked
  three cards in one development family; that check covered no v14 card and is not a
  measured error rate. The inclusive context rule raises nDCG for every profile alike.
- **Adjudication.** Five builder/reviewer disagreements were resolved against the PDFs by
  an assistant judge, not a human.
- **Freshness and scope.** Freshness against earlier private family identities cannot be
  fully certified. Three families came from the v13 reserve pool. The set is purposive,
  covers one snapshot and measures ranking only: no generated-answer quality, rejection
  accuracy or whole-literature claim. The pass accepts the Phase 2 retrieval service for
  this private corpus; it is not evidence of general retrieval quality.
- **Sealing.** Do not inspect item-level v14 data or tune on this result.

## v11 decision and scope

*Historical: the sections from here to the end of this report describe spent sets (v11 and earlier, v12, v13) under their own gates. They are kept unchanged except for status notes.*

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
reranker fallback was 2/20 (10%). The historical schema-v2 run record marked all 20
attempts degraded because it treated any response warning as degradation; that status
combined truncation warnings with actual fallback. All 100 warm repeats completed
without failure and result ordering was stable. Schema v3 records fallback status,
warning count and truncation separately.

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

The v10 assessment below is retained as historical evidence. It passed 13 of 14
frozen gates and missed warm p95 at 1,602.2 ms. Its set is spent and was not used for
v11 selection or tuning. Its item-level results remain private.

**Historical v10 status:** The v10 assessment passed 13 of 14 frozen gates and missed
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
| v10 | 13/14 | Warm p95 |
| v12 | 8/14 | Paper nDCG@10; evidence nDCG@10, direct MRR@10, judged Recall@20; source Recall@50; positive-family hit@10 |
| v13 | 10/14 | Paper nDCG@10; evidence nDCG@10, direct MRR@10, judged Recall@20 |

Earlier sets, including v13, are also spent and cannot guide selection. Their item-level records remain
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

Historical v11 checkpoint: P2-20 passed with the selected profile and numeric limits
unchanged. R8 v12 passed 8 of 14 gates and the R8 v13 assessment (30 families, ADR-0014)
passed 10 of 14 under their own frozen gates. The R8 v14 assessment (30 families,
acceptance-v14, hosted CI run 36740163129 green on commit `82694aa`) passed all 16 gates on
2026-09-30, so Phase 2 is accepted with `frozen-profile-v10`
([ADR-0017](../adr/0017-phase2-accepted-profile-v10.md)). The v14 section at the top of this
report is the current result. v13 and every earlier held-out set remain spent and sealed.
v13 stays failed under its own gates. Phase 3 has not started.

## R8 v12 result — assistant-reviewed 2026-09-28

The one-time frozen assessment used `phase2-benchmark-v12`,
`phase2-acceptance-v10`, and freeze manifest `phase2-r8-v1`. The selected profile was
`sha256:959e24b6ff6de711bbdfbf5020c5ac82a91cce43f48c8f52ba9d214c3e00e9be`; the source
snapshot was `4b11fab3-d4a5-4e7a-a58e-8654accf2c6c`. The freeze manifest SHA-256 is
`ad2dab06ea1fd103f16ac64ca9f2e458e1c21654149a2e91e1c7dece14d0547c`; its held-out
dataset and source-alignment hashes are `04c42aad7ce45a1480712a2d7e819cb7d98ed9a7254372c8160f5dcb4ac8436f`
and `29c2e139048a587663fa14baaaa3f3729165519cdb1b89df1698763e8665b28e`. The frozen
acceptance configuration hash is
`dd75323a5fa263dc29f91056c646e001756e76192cfa6025ec59148709a50377`. The manifest
records that source freshness cannot be fully certified against earlier private
family identities; this limitation remains part of the result.

### Selected-profile gates

| Gate | Frozen limit | R8 aggregate | Result |
| --- | ---: | ---: | --- |
| Paper nDCG@10 | ≥ 0.80 | 0.5793 | **Fail** |
| Paper direct MRR@10 | ≥ 0.70 | 0.8143 | Pass |
| Paper judged Recall@20 | ≥ 0.90 | 1.0000 | Pass |
| Evidence nDCG@10 | ≥ 0.45 | 0.3231 | **Fail** |
| Evidence direct MRR@10 | ≥ 0.45 | 0.2857 | **Fail** |
| Evidence judged Recall@20 | ≥ 0.60 | 0.4286 | **Fail** |
| Source-anchor Recall@10 | ≥ 0.25 | 0.3000 | Pass |
| Source-anchor Recall@50 | ≥ 0.35 | 0.3000 | **Fail** |
| Positive source families with a hit at @10 | ≥ 0.50 | 0.4286 (3/7) | **Fail** |
| Hard-failure fraction | ≤ 0.01 | 0.0000 | Pass |
| Reranker-fallback fraction | ≤ 0.35 | 0.1000 | Pass |
| Warm p95 | ≤ 2,000 ms | 894.349 ms | Pass |
| Combined cold model load | ≤ 15,000 ms | 5,500.9119 ms | Pass |
| Summed CUDA allocation | ≤ 1 GiB | 224,966,656 bytes | Pass |

### Sanitized profile comparison

The following aggregate comparison is retained only as a description of this spent
set. It does not authorize profile selection or tuning from v12. Direct-MRR and other
profile metrics are omitted because they were not present in the sanitized run summary.

| Profile | Paper nDCG@10 | Evidence nDCG@10 | Source Recall@10 / @50 | Warm p95 |
| --- | ---: | ---: | ---: | ---: |
| BM25 lexical | 0.3426 | 0.1803 | 0.2000 / 0.2000 | 568.8 ms (100 samples) |
| Dense E5 | 0.6375 | 0.3044 | 0.3000 / 0.3000 | 659.7 ms (100 samples) |
| Hybrid E5 | 0.5437 | 0.3044 | 0.3000 / 0.3000 | 690.0 ms (100 samples) |
| MiniLM-over-Hybrid selected | 0.5793 | 0.3231 | 0.3000 / 0.3000 | 894.3 ms (300 samples) |
| Fixed-window Dense E5 | 0.6624 | 0.4286 | 0.3000 / 0.3000 | 341.8 ms (100 samples) |

The selected-profile timing used 300 measured HTTP requests across three sessions,
with six warmups per session, result limit 10, concurrency 1, four CPU threads, and
`auto` device selection. No-match filter cases were included. Each comparison profile
used one 100-request session. The selected run used a WSL-exposed NVIDIA GeForce RTX
3050 Laptop GPU; combined cold model load was 5,500.9119 ms and summed CUDA allocation
was 224,966,656 bytes. The raw result is retained privately (SHA-256
`6205c14af18613654516ba7a9e28d08a254a0a605d17a592bec52840710fdecb`) and is not
included in this report. The sanitized run summary did not include category or
bootstrap rows, so this report does not publish those statistics.

The v12 set is spent and sealed. Do not inspect its item-level outcomes or tune on its
aggregate comparison. Make further changes using development data, then prepare and
source-review another held-out set before a new freeze and one-time assessment. The
sample is purposive and directional; this ranking evaluation does not test generated
answer quality.

## R8 v13 result — assistant-reviewed 2026-09-29

**Result: FAIL, 10 of 14 gates passed.** The one-time frozen assessment used
`phase2-benchmark-v13` (30 families) under [ADR-0014](../adr/0014-phase2-acceptance-method.md),
with the unchanged selected profile
`sha256:959e24b6ff6de711bbdfbf5020c5ac82a91cce43f48c8f52ba9d214c3e00e9be`, the
unchanged 14 gate thresholds and the accepted snapshot
`4b11fab3-d4a5-4e7a-a58e-8654accf2c6c`. It ran on 2026-09-29 at commit `5ab0070`;
hosted CI run [36598523416](https://github.com/avsngh-git/RAGpipeline/actions/runs/36598523416)
passed on that commit. **v13 is spent and sealed from tuning. Phase 2 remained
unaccepted at that point (superseded by the v14 result at the top of this report).** Per ADR-0014 point 9, work returns to a development-only diagnosis note
(aggregates only); at most one replacement set remains authorized, and a second failure
goes to the owner through change control.

### Frozen v13 identities

| Field | Value |
| --- | --- |
| Freeze manifest SHA-256 | `bccc6310c83715d2125feae6334b3eff67e6d5ff30b51b0a8ab53c3e03b351fd` |
| Held-out dataset SHA-256 | `b0f86851da70bd73a9d350ef2972e16e00cb153c394af4026cdede2a997071e8` |
| Source-alignment SHA-256 | `c6ca4bd8b113456a1b697bacdf5e8db7a6e68a330e8f1a93a4d6d4b3b167169d` |
| Private raw run record SHA-256 | `ac7778510e44bc8a706c441cc00bd6889e6da47d4a5c4c565e20111ce3a58819` |
| Evaluated commit | `5ab0070` |

The raw record, dataset, alignment and review files stay in the ignored private
`local-reference/` directory and are not published.

### Composition and review process

The set has 30 families: 25 positive and 5 missing-evidence. Category membership
overlaps: discovery 10, specific evidence 18, table result 16, filters 12,
cross-paper comparison 5, missing evidence 5. There are 96 positive anchors: 84
source-first builder anchors across 25 families and 12 pool-found label-2 anchors.
The source alignment holds 135 table and 2,290 prose anchors, mostly derived label-0
anchors that exist for coverage.

Every builder anchor was verified against the PDF by a separate verifier. Blind
reviewers judged pooled candidates without seeing profile or rank. Builder-anchor
disagreements arose in 9 families and were resolved in favour of the twice-verified
anchors (decision O11). Eleven cards were unmatchable (segmented or figure chunks).
Eight reranker fallbacks occurred during pooling. All judgments are assistant-reviewed;
no human verification is claimed.

### Coverage pre-check

Judged fraction of results at top 10 / top 20. Every profile's paper coverage was
1.000 / 1.000. The per-family 80% rule was applied to both paper and evidence, and every
selected-profile family reached 1.000 at top 10. The pre-check was met.

| Profile | Evidence @10 / @20 |
| --- | ---: |
| BM25 | 0.998 / 0.996 |
| Dense E5 | 0.989 / 0.993 |
| Hybrid E5 | 1.000 / 0.995 |
| Selected | 1.000 / 0.996 |
| Fixed-window | 0.997 / 0.997 |

### Selected-profile gates

| Gate | Frozen limit | v13 aggregate | Result |
| --- | ---: | ---: | --- |
| Paper nDCG@10 | ≥ 0.80 | 0.6863 | **Fail** |
| Paper direct MRR@10 | ≥ 0.70 | 0.7582 | Pass |
| Paper judged Recall@20 | ≥ 0.90 | 1.0000 | Pass |
| Evidence nDCG@10 | ≥ 0.45 | 0.2733 | **Fail** |
| Evidence direct MRR@10 | ≥ 0.45 | 0.2831 | **Fail** |
| Evidence judged Recall@20 | ≥ 0.60 | 0.3492 | **Fail** |
| Source-anchor Recall@10 | ≥ 0.25 | 0.3854 | Pass |
| Source-anchor Recall@50 | ≥ 0.35 | 0.3958 | Pass |
| Positive families with a hit at @10 | ≥ 0.50 | 0.6800 | Pass |
| Hard-failure fraction | ≤ 0.01 | 0.0000 | Pass |
| Reranker-fallback fraction | ≤ 0.35 | 0.0667 | Pass |
| Warm p95 | ≤ 2,000 ms | 885.7 ms | Pass |
| Combined cold model load | ≤ 15,000 ms | 6,087.2 ms | Pass |
| Summed CUDA allocation | ≤ 1 GiB | 224,311,296 bytes | Pass |

### Profile comparison

Descriptive only; it does not authorize profile selection or tuning from v13. The
selected profile has 366 timing samples; each other profile has 122.

| Profile | Paper nDCG@10 | Evidence nDCG@10 | Source Recall@10 / @50 | Warm p95 |
| --- | ---: | ---: | ---: | ---: |
| BM25 | 0.3873 | 0.2022 | 0.2604 / 0.2708 | 584.9 ms |
| Dense E5 | 0.7474 | 0.2458 | 0.3854 / 0.3854 | 644.2 ms |
| Hybrid E5 | 0.6889 | 0.2589 | 0.3333 / 0.3542 | 713.7 ms |
| MiniLM-over-Hybrid (selected) | 0.6863 | 0.2733 | 0.3854 / 0.3958 | 885.7 ms |
| Fixed-window Dense E5 | 0.7332 | 0.2224 | 0.3646 / 0.3646 | 393.0 ms |

### Baseline context

BM25 paper nDCG@10 (0.3873) and evidence nDCG@10 (0.2022) are both outside the
descriptive reference bands (0.50–0.85 and 0.25–0.75), so the "set difficulty unusual"
flag is set. This is descriptive and changes no gate.

### Limitations and caveats

- Bootstrap intervals and per-category rows exist in the private record but were not
  extracted; they are withheld pending a sanitized extraction, and none are reported
  here.
- Freshness against the spent sets v3–v12 cannot be certified. Some anchor facts were
  already named in the tracked v13 evidence map (ADR-0014 O3(c) caveat).
- The O11 resolution favoured the twice-verified anchors in 9 families' disagreements;
  no human verification is claimed.
- The set is purposive and directional. It measures ranking and retrieval, not
  generated-answer quality, and supports no whole-literature claim.
- Paper and evidence gates failed while warm p95, cold load, CUDA memory, hard-failure
  and fallback gates passed. Do not read item-level v13 data or tune on this result.
