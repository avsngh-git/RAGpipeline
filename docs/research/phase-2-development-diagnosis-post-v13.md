# Phase 2 development diagnosis after the v13 failure

**Status:** complete · **Reviewer:** assistant (assistant-reviewed; not human-verified) · **Date:** 2026-09-29
**Required by:** [ADR-0014](../adr/0014-phase2-acceptance-method.md) point 9 (aggregate-only diagnosis before any new set)
**Snapshot:** 4b11fab3-d4a5-4e7a-a58e-8654accf2c6c · **Profile:** frozen v9 (`sha256:959e24b6…`), unchanged

The v13 held-out set is sealed. This note uses development data only: calibration q01–q10, development q11–q19
and the two v13 development families. It reports only v13 held-out aggregates that are already published. It
contains no held-out questions, labels, rankings or per-family results. q20 and q21 stay excluded.

## Why a new development baseline was needed

Earlier development scores were not comparable with held-out scoring:

- The calibration families had one or two judgments each, so almost all returned results counted as zero-gain
  unjudged results. The 0.928 paper nDCG@10 reported for the selected profile in P2-14 rested on that sparse pool.
- The q11–q19 labels were attached to chunk candidates rather than to source anchors, so the v13 scorer could not
  count them.
- A tracked calibration record gives the wrong extraction ID for one paper. Its table anchors could never match a
  returned hit, so that family's evidence always scored zero. The unified set corrects the ID; the tracked file is
  unchanged.

The unified development set rebuilds all 21 families in the v13 calibration format:

- The existing q11–q19 labels became derived anchors (self-check: 0 mismatches). Four source-only prose anchors
  that could not be aligned were dropped; this makes source recall slightly easier.
- All five declared profiles were pooled with the v13 procedure (top 20 papers and top 50 evidence per query).
- 901 blind top-up cards were reviewed. A first review pass was rejected because its labels were scripted and
  templated and it judged paper cards from titles alone. The accepted second pass judged each card individually,
  using paper digests and PDF checks for exact-value calls.
- The final set has 1,531 judged anchors. Judgment coverage is 100% of paper results at top 10 and 20 for every
  profile. Evidence coverage is 92–96% for four profiles and about 87% for fixed-window. Unjudged results count as
  zero gain, so evidence scores are slightly conservative.

## Development baseline (macro means, 21 families; MRR and recall over 17 positive families)

| Profile | Paper nDCG@10 | Paper MRR@10 | Paper R@20 | Evidence nDCG@10 | Evidence MRR@10 | Evidence R@20 | Source R@10 / @50 |
|---|---:|---:|---:|---:|---:|---:|---:|
| BM25 | 0.557 | 0.621 | 0.824 | 0.260 | 0.198 | 0.109 | 0.109 / 0.132 |
| Dense E5 | 0.674 | 0.814 | 0.971 | 0.364 | 0.464 | 0.485 | 0.485 / 0.485 |
| Hybrid E5 | 0.700 | 0.822 | 0.971 | 0.385 | 0.360 | 0.445 | 0.439 / 0.445 |
| Selected (MiniLM over Hybrid) | 0.717 | 0.820 | 0.971 | 0.517 | 0.653 | 0.607 | 0.569 / 0.607 |
| Fixed-window dense | 0.660 | 0.843 | 0.971 | 0.331 | 0.554 | 0.394 | 0.394 / 0.394 |

Selected-profile results by subset (gates: paper nDCG ≥ 0.80; evidence nDCG, direct MRR ≥ 0.45; evidence R@20 ≥ 0.60):

| Subset | Paper nDCG@10 | Evidence nDCG@10 | Evidence MRR@10 | Evidence R@20 |
|---|---:|---:|---:|---:|
| Calibration q01–q10 | 0.810 | 0.643 | 0.667 | 0.722 |
| Development q11–q19 | 0.685 | 0.414 | 0.586 | 0.402 |
| v13 development (n = 2) | 0.395 | 0.357 | 1.000 | 1.000 |
| v13 held-out (published) | 0.686 | 0.273 | 0.283 | 0.349 |

Paired family bootstrap intervals (10,000 resamples, seed 20260930), Selected minus the other profile:

| Other profile | Paper nDCG@10 delta [95% CI] | Evidence nDCG@10 delta [95% CI] |
|---|---|---|
| BM25 | +0.160 [+0.086, +0.242] | +0.257 [+0.145, +0.379] |
| Dense | +0.042 [−0.048, +0.133] | +0.153 [+0.086, +0.224] |
| Hybrid | +0.016 [−0.032, +0.056] | +0.132 [+0.078, +0.193] |
| Fixed-window | +0.057 [−0.042, +0.168] | +0.187 [+0.090, +0.283] |

## Findings

1. **The calibration families likely inflated the gates.** Measured the v13 way, the selected profile clears the
   paper gate only on calibration q01–q10. On q11–q19, it scores 0.685 on paper nDCG, essentially matching v13's
   0.686, and it also fails the evidence nDCG and recall gates. The v13 failure is consistent with the system's
   level on non-calibration development questions. It need not reflect an unusually hard held-out set. The
   acceptance limits were chosen from development baselines dominated by the sparse calibration pool.
2. **Paper ranking loss is in ordering, not recall.** Paper Recall@20 is 0.971 and direct MRR@10 is 0.820. The gap to
   the 0.80 nDCG gate comes from how papers after the first relevant one are ordered.
3. **The reranker helps evidence, not papers.** Selected beats every baseline on evidence nDCG, and every interval
   excludes zero. On paper nDCG it is not distinguishable from Dense or Hybrid. BM25 is clearly weakest, and adding
   it to fusion does not help paper ranking.
4. **Evidence quality falls from calibration to harder questions.** Selected evidence nDCG is 0.643 on calibration
   q01–q10, 0.414 on q11–q19 and 0.273 on v13 held-out. On q11–q19, source recall at 10 (0.310) and at 50 (0.402)
   stay low. A large share of direct evidence never reaches the top 50, so reordering within the pool cannot fix it.

## Development-only improvement experiments

These experiments re-ranked papers offline within the union of pooled papers. Every pooled paper is judged, so the
reordered lists are fully judged. Ten variants were tried on 21 families. The intervals below are unadjusted, so the
best variant is optimistically biased.

| Variant | Paper nDCG@10 (all) | q11–q19 | Delta vs Selected [95% CI] |
|---|---:|---:|---|
| Papers ordered by best reranked-evidence rank (proxy) | 0.791 | 0.728 | +0.075 [+0.021, +0.132] |
| RRF of Selected paper rank and best-evidence rank, k = 10 (proxy) | 0.792 | 0.729 | +0.075 [+0.024, +0.129] |
| RRF of Dense and Selected paper lists, k = 10 | 0.761 | 0.714 | +0.045 [−0.009, +0.102] |
| RRF of Hybrid and Selected paper lists (any k) | 0.699 | 0.671 | −0.017 [−0.039, 0.000] |

The pooled records keep only final ranks, so fusion-weight and true reranker-score variants could not be built.
The proxies used the final evidence rank. The earlier paper-RRF constant sweep gained at most +0.016.

The most promising change orders papers by their strongest *reranked* passage. It stays within the frozen
strongest-passage rule and is the leading candidate for any future profile. On point estimates it does not reach
0.80 overall, and it reaches only 0.73 on q11–q19. Evidence gaps come from recall, not ordering (finding 4), and
none of these experiments addresses them.

## Decision under the owner's stop rule

The owner set the rule on 2026-09-29: build a replacement set only if a development variant clears the paper and
evidence gates on point estimates. No variant does. No replacement set (v14) is built. The work moves to owner change
control under [ADR-0014](../adr/0014-phase2-acceptance-method.md) point 9. The proposal is
[ADR-0015](../adr/0015-phase2-acceptance-gate-revision.md). The frozen profile, snapshot and 14 gate thresholds
are unchanged.

## Private artifacts

Raw records are mode 0600 and git-ignored, under
`local-reference/phase2-runs/benchmark-v13/dev-unified/`. They are the unified dataset v2, the pools, the review
batches (the rejected v1 pass is retained separately), `dev-baseline-metrics-v1.json` and
`paper-rank-experiments-v1.json`, each with a SHA-256 sidecar.
