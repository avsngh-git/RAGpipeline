# 11. Evaluation

Evaluation is a subsystem with its own commands and records, not a one-off demo script. This chapter explains the method, the suites and how to diagnose a single run. Measured results are in [Benchmarks](../reference/benchmarks.md), and known failures in [Failure analysis](../reference/failure-analysis.md).

## Method

### Retrieval

Retrieval was evaluated on the accepted 100-paper corpus under a written [evaluation protocol](../plans/phase-2-evaluation-protocol.md):

- **Question families.** Each family is one information need with paraphrases. They cover paper discovery, specific evidence, tables, cross-paper comparison, filters and questions with no supporting evidence.
- **Separate sets.** Calibration and development families are used to compare approaches and choose settings. Held-out families are assembled before scoring and used **once**; afterwards the set is spent and cannot guide tuning.
- **Labels.** Relevance is judged on the source passage or table cell, independent of chunk boundaries: 0 irrelevant, 1 useful context or incomplete support, 2 direct evidence. Candidates are pooled across methods before judging. The assistant reviewed the labels against the sources; they are not described as human-verified.
- **Metrics.** Paper and evidence nDCG@10, direct-evidence MRR@10, judged Recall@20 and @50, source-anchor recall, unsupported-query behaviour, judgment coverage, hard failures, reranker fallbacks, warm median and p95 latency, cold load and GPU memory.
- **Uncertainty.** Paired bootstrap over families (10,000 resamples, 95% percentile intervals) is reported beside point estimates. Gates are judged on point estimates.

The history is part of the result. Earlier held-out assessments (v3, v12, v13) failed and stay failed. After v13, the owner lowered three quality thresholds using development data only ([ADR-0015](../adr/0015-phase2-acceptance-gate-revision.md)) and raised the latency limit ([ADR-0016](../adr/0016-phase2-warm-latency-5000ms.md)). A fresh 30-family set (v14) then passed all 16 gates ([acceptance report](../reference/phase-2-acceptance-report.md)), with three gates by margins inside sampling noise.

### Agent and answers

Agent behaviour was gated on **operational** properties ([ADR-0020](../adr/0020-phase3-evaluation-gates.md)):

- fabricated or unknown evidence handles are rejected in scripted cases;
- at least 90% of live runs finish within budget;
- every failed run has a failure category;
- scripted routing, budget, injection and resume cases pass in CI.

Answer quality was measured and reported, but never gated, because no independent answer-quality benchmark exists for this corpus. Measurements use 21 development tasks in both modes.

## Suites

`research-eval` runs a suite and stores one *experiment record*: dataset and version, code revision, configuration, component versions, hardware, metrics and failures ([ADR-0028](../adr/0028-phase4-experiment-records-and-gate.md)). Per-item results, which can contain question and answer text, are written only under `local-reference/experiments/<id>/`.

| Suite | Needs | Measures |
| --- | --- | --- |
| `scripted-regression` | Nothing live | 33 scripted cases (`benchmarks/phase3/regression-cases-v2.json`) for routing, budgets, unknown handles, injection and resume. CI runs the same cases. |
| `retrieval-dev` | Search services and private development sets | nDCG@10, MRR@10, judged recall and judgment coverage |
| `agent-dev` | The running API, worker and model | The 21 development tasks in both modes: outcomes, kept claims, durations. A 42-run sweep takes several hours on an RTX 3050. |
| `security-live` | The model, with fake retrieval | Eight live injection and tool-abuse cases |

```bash
research-eval run scripted-regression
research-eval run retrieval-dev --option profile_id=PROFILE_ID --option datasets=CAL.json:ALIGN.json
research-eval run agent-dev --option api=http://127.0.0.1:8001
research-eval list --suite agent-dev --limit 10
research-eval compare BASELINE_ID CANDIDATE_ID --with-stages --output local-reference/compare.md
```

`compare` requires the same suite and dataset. It reports metric deltas with a seeded paired bootstrap, configuration differences and, with `--with-stages`, how many runs failed at each diagnosis stage. The private development datasets are not in the public repository, so only `scripted-regression` runs from a clean clone. See the [evaluation operations guide](../operations/evaluation.md).

## Diagnosing a run

```bash
research-runs explain RUN_ID
research-runs explain RUN_ID --json --spans local-reference/traces/research-api.jsonl
```

`explain` is deterministic and reads only text-free records ([`diagnosis.py`](../../src/research_platform/runs/diagnosis.py)). It attributes the run to one stage:

| Run state | Stage |
| --- | --- |
| Queued, running or waiting | `in_progress` |
| Completed and `answered` | `none` |
| Completed, but no evidence was collected | `retrieval` |
| Completed, and the model declared the evidence insufficient | `evidence` |
| Completed, and some drafted claim was not kept as written | `verification` |
| Completed otherwise short of `answered` | `generation` |
| Failed: `model_unavailable`, or a model call timed out | `model` |
| Failed: `invalid_model_output` in a plan or evaluate call | `planning` |
| Failed: `invalid_model_output` in synthesis | `generation` |
| Failed: `budget_exhausted`, or another timeout | `budget` |
| Failed: `retrieval_error` | `retrieval` |
| Failed: `resume_exhausted`, `configuration_changed` or `internal` | `infrastructure` |

It also lists findings, which carry identifiers and counts but never text:

- `no_evidence_collected`, `model_declared_insufficient` and `drafts_rejected`;
- `planner_never_discovered` (a `deep_research` run, short of `answered`, that never called `discover_papers`);
- `ingestion_wait_cap`;
- `tool_rejections`, `llm_repairs` and `omitted_evidence`.

`--spans` adds timings from the JSONL traces.

## Reproducing a run

```bash
research-runs reproduce RUN_ID
```

`reproduce` recomputes the stored configuration hash, rebuilds the effective configuration with the current code, and prints a recipe: the run's git checkout, environment, mode, filters and seed. It exits 0 only when both match. Settings added after a run, such as `max_synthesis_attempts`, make the rebuild differ; in that case check out the recorded commit and run `reproduce` there. Exact output is not promised, because model inference is nondeterministic, but the inputs and configuration are recoverable.

## The Phase 4 gate as an example

The Phase 4 gate required that a developer can explain a failed answer from trace evidence and reproduce its configuration. Five live development failures were each attributed to a stage (evidence, retrieval and verification), and the owner reviewed one. All five reproduced with matching configuration hashes. See the [Phase 4 gate report](../reference/phase-4-gate-report.md).

Next: [Observability and security](12-observability-and-security.md).
