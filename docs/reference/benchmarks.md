# Benchmarks

This page summarizes the repository's retrieval and agent measurements. It reports
development experiments separately from the one-time held-out assessment. These
results describe one accepted corpus and do not establish performance on scientific
literature in general.

## How to read these numbers

The Phase 2 and Phase 3 measurements use the accepted 100-paper snapshot with 44,277
selected chunks. Phase 6 plans to package the 100 CC BY papers for the public demo;
the bundle's per-document display review is a separate release check. See the
[Phase 2 acceptance report](phase-2-acceptance-report.md) and the
[Phase 6 plan](../plans/phase-6-portfolio.md).

Phase 2 separates calibration and development families, used to compare approaches,
from a held-out set assembled before its single scoring run. The v14 held-out set has
30 families and is spent: it must not guide tuning. Retrieval labels use a 0–2 scale:
0 is irrelevant, 1 is useful context or incomplete support, and 2 is direct evidence.
New labels and judgments are assistant-reviewed; they are not described as human
verified. See the [evaluation protocol](../plans/phase-2-evaluation-protocol.md),
[ADR-0014](../adr/0014-phase2-acceptance-method.md), and the
[v14 acceptance report](phase-2-acceptance-report.md).

The v14 table reports point estimates. Paired intervals resample families 10,000
times and use percentile 95% bounds. Gates are judged on point estimates, not on
whether an interval crosses a threshold. This purposive sample and its intervals
support directional conclusions, not precise estimates for the wider literature.
See the [v14 method and caveats](phase-2-acceptance-report.md).

## Retrieval

### Held-out profile comparison

The v14 comparisons used a result limit of 10; source-anchor recall is also reported
at rank 50. The selected profile is the reranked gte hybrid. Dense gte had better
paper nDCG@10 than the selected profile, while the selected profile had better
evidence nDCG@10. The rows are descriptive comparisons from this spent set.

| Profile | Paper nDCG@10 | Evidence nDCG@10 | Source recall @10 / @50 | Warm p95 | Source |
| --- | ---: | ---: | ---: | ---: | --- |
| BM25 lexical | 0.4264 | 0.2482 | 0.3095 / 0.3810 | 634.1 ms | [v14 report](phase-2-acceptance-report.md) |
| Dense gte | 0.7183 | 0.3610 | 0.5476 / 0.5556 | 710.9 ms | [v14 report](phase-2-acceptance-report.md) |
| Hybrid gte, before reranking | 0.6523 | 0.3644 | 0.5556 / 0.6587 | 799.3 ms | [v14 report](phase-2-acceptance-report.md) |
| Reranked gte hybrid, selected | 0.6522 | 0.4074 | 0.5714 / 0.6508 | 1,016.1 ms | [v14 report](phase-2-acceptance-report.md) |
| Fixed-window dense E5 | 0.6672 | 0.2380 | 0.3730 / 0.3810 | 423.3 ms | [v14 report](phase-2-acceptance-report.md) |

Paired deltas for reranked gte hybrid versus the same hybrid before reranking were:
evidence nDCG@10 +0.0430 (95% interval [+0.0095, +0.0752]), evidence direct MRR@10
+0.2036 (interval [+0.0964, +0.3177]), and evidence judged Recall@20 +0.0787 (interval
[+0.0159, +0.1468]). Paper nDCG@10 changed by −0.0001 (interval [−0.0265,
+0.0238]). These are v14 held-out comparisons and cannot be used to tune that set.
See the [paired differences](phase-2-acceptance-report.md).

The development comparison also tested two embedding candidates. Dense E5 was faster
than dense BGE and scored higher on evidence nDCG@10 in that run; hybrid E5 had higher
source recall at ranks 20 and 50 than hybrid BGE. The 19-family development sample
was used to make profile choices, so it is not independent confirmation.

| Development profile | Paper nDCG@10 | Evidence nDCG@10 | Source recall @10 / @20 / @50 | Warm median / p95 | Source |
| --- | ---: | ---: | ---: | ---: | --- |
| Dense E5 | 0.873 | 0.456 | 0.226 / 0.290 / 0.452 | 550 / 704 ms | [development report](../research/phase-2-development-report.md) |
| Dense BGE | 0.857 | 0.308 | 0.226 / 0.258 / 0.516 | 595 / 745 ms | [development report](../research/phase-2-development-report.md) |
| Hybrid E5 | 0.879 | 0.261 | 0.226 / 0.355 / 0.581 | 876 / 1,037 ms | [development report](../research/phase-2-development-report.md) |
| Hybrid BGE | 0.822 | 0.199 | 0.226 / 0.323 / 0.613 | 929 / 1,046 ms | [development report](../research/phase-2-development-report.md) |

The development study reranked the same 50-candidate Hybrid E5 pool. MiniLM reranked
the full pool in 13 of 19 attempts; the other 6 used the complete hybrid ordering as
the explicit fallback. BGE reranking succeeded for 6 of 19 attempts and used fallback
for 13. This development result informed the later profile; it is not the v10 or v14
held-out result. See the [reranker measurements](../research/phase-2-development-report.md).

### Chunking and result limits

On the paired development audit, section-aware and fixed-window chunking had equal
source-anchor recall at ranks 5, 20, and 50; section-aware found 7 of 27 anchors at
rank 10 and fixed-window found 6. The audit did not support changing the selected
section-aware strategy. The fixed-window setup used 480-token windows with 64-token
overlap and kept table chunking constant. See the
[fixed-window report](phase-2-fixed-window-chunking.md).

The development result-limit comparison kept 154, 281, and 337 of 450 dense-E5
results at per-paper evidence caps of 1, 3, and 5. Source-anchor Recall@10 was 0.065,
0.129, and 0.226, respectively; cap 5 preserved the unbounded top-10 score. The
serving profile therefore retained a cap of 5. See the
[selection measurements](../research/phase-2-development-report.md).

### v14 acceptance gates

All 16 gates passed on point estimates. Three quality gates passed by small margins
whose 95% intervals include their thresholds. The thresholds for paper nDCG@10,
evidence nDCG@10, and evidence judged Recall@20 were lowered after v13 failed; the
v13 result remains failed under its original thresholds. Dense gte alone ranked
papers better than the selected hybrid profile. See the
[v14 report](phase-2-acceptance-report.md), [ADR-0015](../adr/0015-phase2-acceptance-gate-revision.md),
and [ADR-0016](../adr/0016-phase2-warm-latency-5000ms.md).

| Gate | Threshold | v14 result | Margin | 95% interval | Result and source |
| --- | ---: | ---: | ---: | ---: | --- |
| Paper nDCG@10 | ≥ 0.65 | 0.6522 | +0.0022 | [0.5592, 0.7420] | Pass; [v14 report](phase-2-acceptance-report.md) |
| Paper direct MRR@10 | ≥ 0.70 | 0.7811 | +0.0811 | [0.6683, 0.8846] | Pass; [v14 report](phase-2-acceptance-report.md) |
| Paper judged Recall@20 | ≥ 0.90 | 0.9499 | +0.0499 | [0.9082, 0.9850] | Pass; [v14 report](phase-2-acceptance-report.md) |
| Evidence nDCG@10 | ≥ 0.40 | 0.4074 | +0.0074 | [0.3417, 0.4710] | Pass; [v14 report](phase-2-acceptance-report.md) |
| Evidence direct MRR@10 | ≥ 0.45 | 0.5887 | +0.1387 | [0.4434, 0.7260] | Pass; [v14 report](phase-2-acceptance-report.md) |
| Evidence judged Recall@20 | ≥ 0.50 | 0.5122 | +0.0122 | [0.3759, 0.6513] | Pass; [v14 report](phase-2-acceptance-report.md) |
| Source-anchor Recall@10 | ≥ 0.25 | 0.5714 (72/126) | +0.3214 | — | Pass; [v14 report](phase-2-acceptance-report.md) |
| Source-anchor Recall@50 | ≥ 0.35 | 0.6508 (82/126) | +0.3008 | — | Pass; [v14 report](phase-2-acceptance-report.md) |
| Positive source families with a hit at @10 | ≥ 0.50 | 0.8462 (22/26) | +0.3462 | — | Pass; [v14 report](phase-2-acceptance-report.md) |
| Hard-failure fraction | ≤ 0.01 | 0.0000 | 0.0100 | — | Pass; [v14 report](phase-2-acceptance-report.md) |
| Reranker-fallback fraction | ≤ 0.35 | 0.0000 | 0.3500 | — | Pass; [v14 report](phase-2-acceptance-report.md) |
| Warm p95 | ≤ 5,000 ms | 1,016.06 ms | 3,983.94 ms | — | Pass; [v14 report](phase-2-acceptance-report.md) |
| Combined cold model load | ≤ 15,000 ms | 6,517 ms | 8,483 ms | — | Pass; [v14 report](phase-2-acceptance-report.md) |
| Summed CUDA allocation | ≤ 1 GiB | 634,404,864 B | 439,336,960 B | — | Pass; [v14 report](phase-2-acceptance-report.md) |
| Paper nDCG@10 gain over BM25, 95% lower bound | > 0 | 0.1690 (mean +0.2258) | +0.1690 | [0.1690, 0.2853] | Pass; [v14 report](phase-2-acceptance-report.md) |
| Evidence nDCG@10 gain over BM25, 95% lower bound | > 0 | 0.0961 (mean +0.1592) | +0.0961 | [0.0961, 0.2221] | Pass; [v14 report](phase-2-acceptance-report.md) |

## Latency and resources

The accepted v14 retrieval profile had a measured warm median of 789.9 ms across
366 requests and a warm p95 of 1,016.06 ms. Cold model load was 6,517 ms; full runtime
startup was 10,424.9 ms. Summed model-load CUDA allocation was 634,404,864 bytes.
These are retrieval-profile measurements on the RTX 3050 Laptop GPU, not CPU small-mode
latency. See the [v14 timing and resource report](phase-2-acceptance-report.md).

| Measurement | Result | Source |
| --- | ---: | --- |
| v14 warm median / p95 | 789.9 / 1,016.06 ms | [v14 report](phase-2-acceptance-report.md) |
| v14 combined cold model load | 6,517 ms | [v14 report](phase-2-acceptance-report.md) |
| v14 full runtime startup | 10,424.9 ms | [v14 report](phase-2-acceptance-report.md) |
| v14 summed CUDA allocation at model load | 634,404,864 B | [v14 report](phase-2-acceptance-report.md) |
| Phase 3 peak GPU memory, quick / deep research | 2,466 / 2,468 MiB | [Phase 3 evaluation](phase-3-evaluation-report.md) |
| Phase 3.5 peak GPU memory, natural / forced ingestion | 2,622 / 3,912 MiB | [Phase 3.5 evaluation](phase-3.5-evaluation-report.md) |

The Phase 3.5 forced-ingestion run used the API, worker, and Ollama together; its GPU
peak was 3,912 MiB. It does not measure CPU small-mode latency. See the
[Phase 3.5 evaluation](phase-3.5-evaluation-report.md) and [Phase 6 plan](../plans/phase-6-portfolio.md).

## Agent and answer measurements

The Phase 3 operational sweeps used 21 development families in both modes. In the
recovered sweep, 41 of 42 runs completed within budget, including one categorized
timeout; the fully sampled sweep completed 42 of 42. Neither sweep had an unknown
evidence handle or a completed-run budget violation. These operational results passed
their gates; answer quality was diagnostic only. See the
[Phase 3 evaluation](phase-3-evaluation-report.md) and [ADR-0020](../adr/0020-phase3-evaluation-gates.md).

| Fully sampled Phase 3 outcomes | Quick | Deep research | Source |
| --- | ---: | ---: | --- |
| Completed within budget | 21/21 | 21/21 | [Phase 3 evaluation](phase-3-evaluation-report.md) |
| Answered / partially supported / insufficient evidence | 1 / 9 / 11 | 0 / 9 / 12 | [Phase 3 evaluation](phase-3-evaluation-report.md) |
| Unknown evidence handles | 0 | 0 | [Phase 3 evaluation](phase-3-evaluation-report.md) |
| Completed runs with budget violations | 0 | 0 | [Phase 3 evaluation](phase-3-evaluation-report.md) |
| Peak GPU memory | 2,466 MiB | 2,468 MiB | [Phase 3 evaluation](phase-3-evaluation-report.md) |

After the synthesis changes in [ADR-0025](../adr/0025-verified-quote-synthesis-with-thinking.md),
assistant review found 86% of kept claims supported and relevant with thinking, compared
with 50% without thinking; median synthesis time was 215 seconds. These are replay
measurements, not acceptance gates or human review. See [ADR-0025](../adr/0025-verified-quote-synthesis-with-thinking.md).

The later 42-run `agent-dev` sweep recorded 5 answered, 25 partially supported, and
12 insufficient-evidence outcomes, with a median of 1.5 kept claims. On review, 57 of
131 synthesis calls declared insufficient evidence even though none of 69 reviewed
contexts were labeled insufficient. These sets and measures have different units; the
counts are not combined. See the [answer-quality methods report](../research/answer-quality-methods-2026-10-11.md)
and [ADR-0029](../adr/0029-claim-scope-words-and-prompt-trials.md).

## Security measurements

The live `security-live` suite has 8 synthetic cases and uses fake retrieval. Three
repeated runs completed all cases. Three of the seven checked cases were marked as
violations in each run; review found one code-control gap and two cases of model
susceptibility while code controls held. The code gap was filed and fixed. This is a
three-run observation, not a general reliability estimate. See the
[Phase 4 security report](phase-4-security-live-report.md).

The scripted Phase 3 routing, budget, injection, and resume cases passed CI. The Phase 5
MCP security suite also passed CI as part of the Phase 5 gate; its coverage includes
keys, scopes, rate limits, run ownership, request limits, host/origin checks, text
exposure, and cursor tampering. See the [Phase 3 evaluation](phase-3-evaluation-report.md)
and [Phase 5 gate report](phase-5-gate-report.md).

## Reproduce

The repository documents these commands for inspecting stored evaluations and run
diagnoses:

```bash
research-eval list --suite agent-dev --limit 10
research-eval show EXPERIMENT_ID
research-runs explain RUN_ID --json
research-runs reproduce RUN_ID
```

The first two commands inspect experiment records. `explain` reports the diagnosis
stage, while `reproduce` recomputes the stored configuration hash and prints the
recorded checkout and settings. Older runs can require their recorded code checkout.
Private question text, answers, passages, and per-item outputs are not published. See
the [evaluation operations guide](../operations/evaluation.md).
