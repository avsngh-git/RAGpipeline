# Phase 3 live development evaluation

**Status:** implementation prepared; live evaluation pending. No gate result is claimed
in this draft.

The evaluation uses the 21 approved Phase 2 development families in both `quick` and
`deep_research` modes. It does not use held-out families. Private tasks, run views, tool
calls, evidence-handle registries, answers and source passages remain under ignored
`local-reference/phase3-runs/`; this report contains aggregates only.

## Run record

| Field | Value |
|---|---|
| Evaluation date | Pending |
| Evaluator code revision | Pending |
| Serving code revision | Pending |
| Model identity | Pending |
| Thinking settings | Pending |
| Recorded run budgets | Pending |
| Task count by source | 10 calibration, 9 allowlisted development, 2 v13 development |
| Run count | 42 expected; pending |
| Scripted CI evidence (P3-15) | Pending merge and green CI run |

Latency percentiles use the nearest-rank method: sort the observations and select rank
`ceil(p × n)`, with ranks starting at one. The median is the conventional median.

## Operational gates

| Gate | Limit | Value | Result |
|---|---|---|---|
| Scripted rejection of fabricated or unknown evidence handles | 100% | Pending P3-15 CI | Pending |
| Live citations use registered evidence handles | 0 unknown handles | Pending | Pending |
| Live runs complete within budget | At least 90% in each mode and overall | Pending | Pending |
| Failed runs have a recognized failure category | 100% | Pending | Pending |
| Scripted routing, budget, injection and resume cases | All pass | Pending P3-15 CI | Pending |

Completed runs are also checked against their persisted provenance budgets for tool
calls, plan rounds and active seconds. Any violations will be reported separately and
will not be hidden by changing run status or evaluation thresholds.

## Reported results

Live aggregates, quality observations and failure counts will be added after the run.
Answer quality is reported for Phase 4 planning and is not a Phase 3 gate.

| Measure | `quick` | `deep_research` |
|---|---:|---:|
| Answer outcomes | Pending | Pending |
| Claim support labels | Pending | Pending |
| Mean claims per answer | Pending | Pending |
| Mean citations per claim | Pending | Pending |
| Mean executed tool calls per run | Pending | Pending |
| Mean stored tool-call records per run | Pending | Pending |
| Mean plan rounds per run | Pending | Pending |
| Mean model calls per run | Pending | Pending |
| Active seconds, median / p95 | Pending | Pending |
| Peak GPU memory (MiB) | Pending | Pending |
| Judged-paper spot check | Pending | Pending |
| Unsupported-task outcomes | Pending | Pending |
| Failure counts by category | Pending | Pending |
| Completed runs with budget violations | Pending | Pending |

## Limitations

The sample contains only 21 development families and supports operational conclusions
for this local configuration, not a held-out answer-quality claim. Claim support uses the
configured LLM judge and should be interpreted as a reported diagnostic. The Phase 2
development judgments are assistant-reviewed. Model outputs are nondeterministic, and
the report records the model, prompts, code revision and effective budgets for context.
