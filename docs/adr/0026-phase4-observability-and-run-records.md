---
status: proposed
date: 2026-10-06
---

# Phase 4: observability, run records and provenance version 2

Proposed on 2026-10-06 after the Phase 4 planning interview, in which the owner chose
every option recorded here ([owner decisions](../reference/phase-4-owner-decisions.md),
Q1–Q4, Q12–Q14). Implemented by the cards under map issue
[#77](https://github.com/avsngh-git/RAGpipeline/issues/77).

This ADR elaborates LOCKED source-of-truth sections 14.1 (one trace per request) and 6.1
(Langfuse-compatible tracing). It does not change a LOCKED decision. It sets the retention
periods that open decision 14 left open for run data.

## Context

- **Logs.** The JSON formatter keeps only a fixed list of field names and drops the rest.
  As a result, `research_run_finished` loses its run ID, mode, duration and usage, and
  `llm_call` loses its token counts. `research-worker` logs plain text. The request ID does
  not reach the background run task.
- **Tracing and metrics.** There is no tracing or metrics code. `research_runs.trace_id`
  holds the run ID.
- **Model calls and claims.** Prompts, outputs, token counts and timings are not saved, and
  rejected claims survive only as counts. A failed answer cannot be explained from stored
  data.
- **Configuration hash.** `configuration_id` hashes prompt version labels, not prompt
  text. It also omits the seed, the context size, the model timeout, the tool schemas and
  the generation configuration, so two runs with different effective settings can share an
  ID.
- **Langfuse resources.** Self-hosted Langfuse v4 runs a web app, a worker, PostgreSQL,
  ClickHouse, Redis and MinIO, and recommends 4 cores and 16 GiB of RAM. The development
  machine's WSL VM has 11 GiB beside Ollama, the retrieval models, Qdrant and PostgreSQL.

## Decision

1. **Tracing API.** Application code uses the OpenTelemetry API, through one module
   (`observability/tracing.py`) that owns the tracer provider and every span and
   attribute name. Exporters:
   - a JSON Lines file per service under `local-reference/traces/`, on by default outside
     tests;
   - OTLP/HTTP to self-hosted Langfuse v4, only when `RESEARCH_PLATFORM_OTLP_ENDPOINT` is
     set (Compose profile `observability`);
   - in memory, for tests.

   Spans carry Langfuse's attribute names (`langfuse.observation.type=generation`,
   `gen_ai.request.model`, `gen_ai.usage.*`, `langfuse.observation.input/output`,
   `langfuse.session.id`), so Langfuse renders model calls as generations. Each run is one
   trace whose root span is `research_run`. A resumed run starts a new trace with the same
   session ID.
2. **Content levels.** `RESEARCH_PLATFORM_TRACE_CONTENT` is `none`, `ids` or `full`:
   - `none`: names, timings, statuses and counts only;
   - `ids`: plus identifiers and scores;
   - `full`: plus prompts, model output and thinking, tool arguments and query text.

   The default is `full` in development and `ids` elsewhere, and `full` is refused in
   production. Logs never contain question, passage, prompt or answer text at any level.
   `full` is permitted locally because the loopback Langfuse and the JSONL file hold the
   same private data PostgreSQL already holds under the private local permission.
3. **PostgreSQL run records are authoritative.** Traces are diagnostic telemetry, and the
   Phase 4 gate never depends on Langfuse running. New records:
   - `run_configurations`: each effective configuration once, keyed by its
     `configuration_id`;
   - `llm_calls`: one row per model call (kind, prompt version and fingerprint, options,
     attempts, tokens, duration, status, trace and span IDs);
   - `llm_call_payloads`: messages, output and thinking, written only at content `full`;
   - `draft_claims`: every drafted claim with its verdict (`kept`, `unknown_handle`,
     `not_shown`, `failed_checks` with the failed check names);
   - `research_runs.synthesis`: what the synthesis call saw and decided, without text.
4. **Provenance version 2.** The hashed effective configuration adds:
   - SHA-256 fingerprints of each prompt rendered from fixed placeholders;
   - a digest of the tool JSON schemas;
   - the decoding settings sent to the model (seed, context tokens, timeout, temperature);
   - the generation configuration ID.

   A CI test fails when a prompt's text changes without a new version label. Runs keep
   their stored version-1 provenance. A run that started before the change and resumes
   after it fails with `configuration_changed`.
5. **Metrics.** One `prometheus-client` registry defines every metric with the `research_`
   prefix:
   - HTTP requests by route template;
   - runs by mode, status and failure category;
   - tool calls, model calls and tokens;
   - search stage durations and fallbacks;
   - claim verdicts;
   - the ingestion backlog;
   - authentication failures and rate-limited requests.

   The API serves `/metrics`; `research-worker` serves its own on `127.0.0.1:9101`.
   Prometheus runs in the `observability` profile. There is no Grafana in Phase 4.
6. **Retention.** `research-maintenance retention` is a dry run unless `--apply` is given,
   and nothing runs automatically.
   - Checkpoints of completed runs are deleted after 7 days, and of failed runs after
     30 days.
   - Model-call payloads are deleted after 90 days.
   - Retired Qdrant points are purged through the existing `purge_retired`, which keeps
     anything an unfinished run can read.
   - Points of failed or unpublished generations are reported, not deleted: deleting them
     safely needs generation-numbering rules that do not exist yet (backlog issue
     [#115](https://github.com/avsngh-git/RAGpipeline/issues/115)).
   - Run rows, tool calls, model-call metadata, claims and drafted claims are kept.
   - Local Langfuse data is not authoritative and may be wiped.

## Consequences

- A developer can explain a run from PostgreSQL alone. The span tree adds the timing of
  every stage, including those inside a tool call.
- At `full`, prompt and thinking text is stored twice: in PostgreSQL and in the trace
  files. That is tens of kilobytes per run.
- Langfuse may not fit in memory during live sweeps. It stays opt-in, and the P4-02 spike
  decides when it may run.
- Changing a prompt now requires a new version label and a fingerprint update.
- `research-worker` exposes a metrics port, and the JSONL trace files need the same care
  as other private data under `local-reference/`.

## Alternatives considered

- **Langfuse SDK directly.** It is built on OpenTelemetry, but it would tie application
  code to one backend.
- **Jaeger or Tempo as the main viewer.** Lighter, but it lacks the LLM-specific views that
  the spec's Langfuse requirement asks for.
- **Text only in traces, metadata only in PostgreSQL.** This avoids duplicate text, but
  explaining a run would then depend on a trace file surviving.
- **Never storing text.** Diagnosis would lose the prompt and the model's reasoning, which
  are the main evidence for generation and planning failures.
- **OpenTelemetry metrics over OTLP, or Grafana dashboards.** Both add moving parts without
  a measured need.
