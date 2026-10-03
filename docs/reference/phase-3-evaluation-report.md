# Phase 3 live development evaluation

**Status:** assistant-reviewed, 2026-10-03. The live operational gates pass on
the approved development tasks. Answer-quality measurements are diagnostic and
do not gate Phase 3.

The evaluation used 21 approved Phase 2 development families in both `quick`
and `deep_research` modes. It used no held-out families. Private tasks, run
views, tool calls, evidence-handle registries, answers and source passages stay
under ignored `local-reference/phase3-runs/`; this report contains aggregates
only.

## Run record

| Field | Value |
|---|---|
| Evaluation date | 2026-10-03 |
| Task count by source | 10 `calibration-v1`, 9 allowlisted `benchmark-development-questions-v1`, 2 `calibration-v13-development` |
| Evaluator revisions | Original initial segment (21 quick + 8 deep completions; 30th run submitted): `22ebd4368158be3be4d44720e3b3b364bb56f9ba`; original recovery and fully sampled sweep: `fc9806ad0a8e46d85900a945ef2193be6f01e4d4` |
| Serving revision throughout | `22ebd4368158be3be4d44720e3b3b364bb56f9ba` |
| Snapshot | `4b11fab3-d4a5-4e7a-a58e-8654accf2c6c` |
| Retrieval profile | `sha256:52a152db9fb350c91810353650864eaffef0b3fe148fde9781956373d3fe5449` |
| Effective run configurations | 8 unique IDs per sweep (4 per mode); exact IDs are retained in each private run's provenance |
| Generator | Ollama `0.35.0`, `qwen3.5-2b-text:q4_k_m`, `Q4_K_M`, context 16,384 tokens; digest `1157ab146135b648cbc8859201f32bd7d784857d72d45b7e8da9ab81c466335f` |
| Thinking | Planning enabled; evaluate, synthesis and judge disabled |
| Prompt versions | `p3-system-v1`, `p3-plan-v1`, `p3-evaluate-v1`, `p3-synthesize-v1`, `p3-judge-v1` |
| Budgets | 3 plan rounds; 4 actions/plan; 12 tool calls; citation depth 2; 40 evidence passages; 8,000 synthesis tokens; 2 model retries; 300 active seconds; 2 resumes |
| Original recovered sweep | 42 unique task/mode pairs in `eval-issue17-20261003`; 41 completed, one categorized timeout |
| Fully sampled measurement sweep | 42 unique task/mode pairs in `eval-issue17-measured-20261003T174822Z`; all 42 completed |
| P3-15 scripted CI | [Green exact-head CI run 37139685657](https://github.com/avsngh-git/RAGpipeline/actions/runs/37139685657) |

The original sweep submitted 21 quick and 9 deep runs before the evaluator
could no longer retrieve the status of the 30th run. Its last saved view showed
that run as queued; PostgreSQL later recorded it as failed with category
`timeout`. The evaluator logged a `RuntimeError` after that initial view. The
journal sequence makes the first status poll the likely failure point, but the
exception message and underlying transport error were not retained. An
undrained parent-process output pipe is a plausible cause of the API stopping
responding, but remains unconfirmed. Recovery reconciled the existing run by its
saved ID, preserved the timeout, and submitted only the 12 deep task/mode pairs
absent from the journal. An independent audit confirmed 42 unique runs,
task/mode pairs and artifact bundles.

The fully sampled sweep was run separately on the same serving revision,
snapshot, retrieval profile, generator, prompt versions and budgets. It
provides complete GPU sampling for both modes; it is a second nondeterministic
run over the same development tasks, not a held-out evaluation or a formal
variance estimate. The original sweep remains reported alongside it.

Latency percentiles use nearest rank: sort the observations and select rank
`ceil(p × n)`, with ranks starting at one. The median is the conventional
median.

## Operational gates

| Gate | Limit | Original recovered sweep | Fully sampled measurement sweep |
|---|---|---|---|
| Scripted rejection of fabricated or unknown handles | 100% | Pass; P3-15 CI | Pass; same P3-15 CI |
| Live citations use registered evidence handles | 0 unknown handles | 0; pass | 0; pass |
| Live runs complete within budget | At least 90% per mode and overall | Quick 21/21 (100%); deep 20/21 (95.2%); overall 41/42 (97.6%); pass | Quick 21/21, deep 21/21 and overall 42/42 (100%); pass |
| Failed runs have a recognized category | 100% | 1/1 categorized as `timeout`; pass | No failed runs; pass (no failures to classify) |
| Scripted routing, budget, injection and resume cases | All pass | Pass; [P3-15 CI](https://github.com/avsngh-git/RAGpipeline/actions/runs/37139685657) | Pass; same P3-15 CI |

No completed run exceeded its recorded tool-call, plan-round or active-time
budget in either sweep. The original timeout remains a failed run in its gate
denominator; it is not excluded from the completion rate.

## Reported results

### Fully sampled measurement sweep

| Measure | `quick` | `deep_research` |
|---|---:|---:|
| Runs completed | 21/21 | 21/21 |
| Answer outcomes | 1 answered; 9 partially supported; 11 insufficient evidence | 9 partially supported; 12 insufficient evidence |
| Claim support labels | 12 supported; 3 partial | 11 supported; 1 partial |
| Mean claims per answer | 0.714 | 0.571 |
| Mean citations per claim | 1.467 | 1.750 |
| Mean executed tool calls per run | 2.000 | 2.000 |
| Mean stored tool-call records per run | 2.000 | 2.000 |
| Mean plan rounds per run | 0.000 | 1.857 |
| Mean model calls per run | 1.619 | 4.000 |
| Active seconds, median / p95 | 12.94 / 18.63 | 21.80 / 33.39 |
| Peak GPU memory | 2,466 MiB (487 samples) | 2,468 MiB (943 samples) |
| GPU sampler errors | 0 | 0 |
| Judged-paper spot check | 5/10 tasks (50%) | 5/10 tasks (50%) |
| Unsupported-task outcome | 2/2 insufficient evidence | 1/2 insufficient evidence; 1 partially supported |
| Failure counts by category | None | None |
| Completed runs with budget violations | 0 | 0 |

### Original recovered sweep

| Measure | `quick` | `deep_research` |
|---|---:|---:|
| Runs completed | 21/21 | 20/21 |
| Answer outcomes | 1 answered; 9 partially supported; 11 insufficient evidence | 1 answered; 10 partially supported; 9 insufficient evidence |
| Claim support labels | 12 supported; 3 partial | 10 supported; 3 partial |
| Mean claims per completed answer | 0.714 | 0.650 |
| Mean citations per claim | 1.467 | 2.385 |
| Mean executed tool calls per submitted run | 2.000 | 1.619 |
| Mean stored tool-call records per submitted run | 2.000 | 1.619 |
| Mean plan rounds per submitted run | 0.000 | 1.762 |
| Mean model calls per submitted run | 1.619 | 3.857 |
| Active seconds, median / p95 | 8.80 / 14.89 | 20.33 / 46.47 |
| Peak GPU memory | Not recovered; 0 samples | 2,424 MiB (385 samples during resumed runs) |
| Judged-paper spot check | 5/10 tasks (50%) | 5/10 tasks (50%) |
| Unsupported-task outcome | 2/2 insufficient evidence | 1/2 insufficient evidence; 1 partially supported |
| Failure counts by category | None | 1 `timeout` |
| Completed runs with budget violations | 0 | 0 |

The LLM judge dropped unsupported claims before returning answers, but
insufficient-evidence handling was inconsistent on one of two explicitly
unsupported deep tasks in both sweeps. Deep runs returned no `answered` outcome
in the fully sampled sweep. These are reported answer-quality observations, not
Phase 3 gates. The 50% judged-paper spot check is also limited evidence, not a
claim-level correctness score.

## Limitations

The results cover 21 development families only. They do not estimate performance
on unseen tasks, and the second sweep is not an independent labeled benchmark or
a formal variance analysis. The sample is small, support labels come from the
configured LLM judge, and Phase 2 judgments are assistant-reviewed. Model output
is nondeterministic. GPU peaks are system memory observations sampled every
0.5 seconds; the original sweep lacks quick-mode samples because those in-memory
measurements were lost when its evaluator process stopped. The fully sampled
sweep supplies the reported complete per-mode peaks.

The [answer-quality diagnosis](../research/phase-3-answer-quality-diagnosis.md)
(2026-10-04) traces the low `answered` count to the generator's synthesis and support
judging rather than retrieval or JSON output, and records that `deep_research` called only
`search_papers`.
