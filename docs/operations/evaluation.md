# Evaluation suites and run diagnosis

`research-eval` runs evaluation suites and keeps one experiment record per run
([ADR-0028](../adr/0028-phase4-experiment-records-and-gate.md), migration 025).
`research-runs explain` and `reproduce` diagnose and rebuild single research runs. All
commands read `RESEARCH_PLATFORM_DATABASE_URL`; development runs use
`research_phase1_review`.

The integration tests do not use these databases; they need disposable PostgreSQL and
Qdrant services ([integration test services](../../README.md#integration-test-services)).

## Suites

| Suite | Needs | What it measures |
| --- | --- | --- |
| `scripted-regression` | nothing live | the 33 scripted cases in `benchmarks/phase3/regression-cases-v2.json`; CI runs the same cases |
| `retrieval-dev` | the search services | paper and evidence NDCG@10, MRR@10, judged recall and judgment coverage on development calibration sets |
| `agent-dev` | the running API, worker and model | the 21 development tasks in both modes: outcomes, kept claims, durations |
| `security-live` | the model, with fake retrieval | the eight live injection and tool-abuse cases |

```bash
research-eval run scripted-regression
research-eval run retrieval-dev \
  --option profile_id=PROFILE_ID \
  --option datasets=CALIBRATION.json:ALIGNMENT.json
research-eval run agent-dev --option api=http://127.0.0.1:8001
research-eval run security-live
```

Options use `--option KEY=VALUE`; `--notes` adds free text to the record.

- **`retrieval-dev`:** `profile_id` is required. `datasets` takes comma-separated
  `CALIBRATION:ALIGNMENT` path pairs; `mode` (default `reranked`) and `limit` (default 10)
  are optional.
- **`agent-dev`:** `tasks` defaults to `local-reference/phase3-runs/dev-tasks-v1.json`;
  `modes` must list both `quick` and `deep_research`; `run_timeout_seconds` defaults to
  3,600; `resume_items` continues an interrupted sweep from its items file. It sends
  `RESEARCH_PLATFORM_API_KEY` (see [authentication](authentication.md)). A sweep of 42
  runs takes several hours on the RTX 3050.

Per-item results, which may contain question and answer text, are written only to
`local-reference/experiments/<experiment_id>/items.jsonl`. The database record keeps the
dataset, code revision, configuration, component versions, hardware, metrics and failures.

## Inspecting and comparing

```bash
research-eval list --suite agent-dev --limit 10
research-eval show EXPERIMENT_ID
research-eval compare BASELINE_ID CANDIDATE_ID --with-stages \
  --output local-reference/phase4/compare.md
```

`compare` requires the same suite and dataset. It reports metric deltas with a seeded
paired bootstrap, configuration differences and, with `--with-stages`, diagnosis-stage
counts. Its output path must be under `local-reference/`.

An interrupted sweep keeps the status `running`. Resuming with `resume_items` starts a new
experiment that skips the task and mode pairs already in the items file.

## Diagnosing one run

```bash
research-runs explain RUN_ID --spans local-reference/traces/research-api.jsonl
research-runs explain RUN_ID --json
```

`explain` names the stage where the run lost its answer: `planning`, `retrieval`,
`evidence`, `generation`, `verification`, `model`, `budget`, `ingestion` or
`infrastructure`, or `none` for an answered run and `in_progress` for an unfinished one.
It also lists findings such as `model_declared_insufficient`,
`planner_never_discovered` or `failed_check:quote_found`. `--spans` adds span timings from
the JSONL traces.

## Reproducing one run

```bash
research-runs reproduce RUN_ID
```

`reproduce` recomputes the stored configuration hash, rebuilds the effective
configuration with the current code and prints a recipe: the run's `git_checkout`,
environment, mode, filters and seed. It exits 0 only when the hash and the rebuilt
configuration both match. Settings added after a run (for example
`max_synthesis_attempts` or the sampling values) make the rebuild differ, so check out the
recipe's `git_checkout` and run `reproduce` there.
