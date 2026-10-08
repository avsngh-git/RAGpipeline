# Local observability

The observability profile is optional. It adds Prometheus and a self-hosted Langfuse v4 stack.

## Start and stop

The services live in `docker-compose.observability.yml`, so the main file still starts
without any Langfuse secrets. Copy the Langfuse variables from `.env.example` into `.env`,
replace every placeholder, then start the profile from the repository root:

    docker compose -f docker-compose.yml -f docker-compose.observability.yml \
      --profile observability up -d

Stop only the optional observability services while keeping their named data volumes:

    docker compose -f docker-compose.yml -f docker-compose.observability.yml \
      --profile observability stop prometheus langfuse-web langfuse-worker \
      langfuse-clickhouse langfuse-redis langfuse-minio langfuse-postgres

The Prometheus UI is available at <http://127.0.0.1:9090>; Langfuse is available at
<http://127.0.0.1:3000>. Both ports bind to loopback. Configure the generated Langfuse
project public and secret keys in .env to match LANGFUSE_PUBLIC_KEY and
LANGFUSE_SECRET_KEY. The host API sends OTLP traces to RESEARCH_PLATFORM_OTLP_ENDPOINT
when it is set.

## Memory

Langfuse v4 used about 3.0 GiB across its containers in the P4-02 measurement. On the
11 GiB WSL VM, peak used memory reached 9,650 MiB and available memory fell to 2,314 MiB
during two research runs; swap use reached 3,195 MiB. Stop unrelated evaluation and test
containers before starting a live sweep, watch available memory, and stop the observability
profile if it falls below 1 GiB. The spike covered two runs, so long-sweep ClickHouse growth
has not been measured.

## Trace storage

JSONL traces are always written under local-reference/traces/*.jsonl. When
RESEARCH_PLATFORM_OTLP_ENDPOINT is set, traces are also exported to Langfuse. Trace
content is controlled by RESEARCH_PLATFORM_TRACE_CONTENT:

- none omits trace content;
- ids records identifiers and scores;
- full includes content permitted by the local trace policy.

Errors follow the same levels (changed 2026-10-08):
- **Below full,** a failed span records only an ERROR status, with no description, and
  `error.type` (the exception class).
- **At full,** it also records the message as `research.error.message`.
- **Exception events are never recorded.** OpenTelemetry records them by default, with the
  full message and stack trace. A message can hold prompt, model-output or passage text,
  such as a pydantic error's `input_value`, so before this change that text reached the
  JSONL files and Langfuse at every level.

`get_tracer()` returns a `PrivateTracer` that applies this rule to every span.

## Prometheus queries

Request rate by route:

    sum by (route) (rate(research_http_requests_total[5m]))

p95 active run seconds by mode:

    histogram_quantile(0.95, sum by (le, mode) (rate(research_run_active_seconds_bucket[5m])))

p95 model-call duration by kind:

    histogram_quantile(0.95, sum by (le, kind) (rate(research_llm_call_duration_seconds_bucket[5m])))

Failed or rejected tool calls by tool:

    sum by (tool) (rate(research_tool_calls_total{status=~"failed|rejected"}[5m]))

Ingestion backlog:

    research_ingestion_backlog
