# Phase 4 spike: dependencies, version pins, Langfuse memory and rendering (P4-02)

**Date:** 2026-10-06 · **Card:** [#79](https://github.com/avsngh-git/RAGpipeline/issues/79) ·
**Decisions:** [ADR-0026](../adr/0026-phase4-observability-and-run-records.md),
[ADR-0027](../adr/0027-phase4-authentication-and-rate-limits.md)

This report gives the pins and facts that cards P4-09, P4-11, P4-12 and P4-29 follow.
Private measurement files are in `local-reference/phase4/p4-02/`.

## 1. Dependencies

The four packages were added from conda-forge with exact pins in `environment.yaml` and
`pyproject.toml`:

| Package | Version |
| --- | --- |
| `opentelemetry-api` | 1.45.0 |
| `opentelemetry-sdk` | 1.45.0 |
| `opentelemetry-exporter-otlp-proto-http` | 1.45.0 |
| `prometheus_client` | 0.26.0 |

How `environment-linux-64.lock` was regenerated:

1. Build a scratch environment from the previous lock.
2. `conda install --freeze-installed` the four packages into it.
3. Export it with `conda list --explicit`.

The lock gained only the new packages and their dependencies:
- the OpenTelemetry exporter, proto and semantic-convention packages;
- `protobuf` 7.35.1, `googleapis-common-protos`, `libabseil`;
- `wrapt`, `deprecated`, `backoff`, `importlib-metadata`, `zipp`.

The one upgrade is `openssl` 3.6.4 → 3.6.5, a patch release. The same install into the
development environment `sci_research_agent` (which also has Docling and torch) left
`pip check` clean, and both new modules import.

## 2. Pins for P4-11 and P4-29

| Component | Reference |
| --- | --- |
| Langfuse release | `v4.52.0` (2026-10-06, latest) |
| Langfuse web | `docker.io/langfuse/langfuse:4.52.0@sha256:084985a93da19e390420aae249b77a03e42f79a16dfcd39d5b80e47aab1075e5` |
| Langfuse worker | `docker.io/langfuse/langfuse-worker:4.52.0@sha256:b0d77970f505ba9cd5cd16c5310448f55628a6c1c9596eaede444598a82e89b0` |
| ClickHouse | `docker.io/clickhouse/clickhouse-server:25.12@sha256:8a790dd3468db22b1d4e7b18a176f378ff5ff6053b9c48dd4ea1fa71a24c5ba6` |
| MinIO | `cgr.dev/chainguard/minio:latest@sha256:a05a4497e8dce3cb7a7a1bf1872ba5d30ea988f1e8c22c9e0920503761c4b5f1` |
| Redis | `docker.io/redis:7@sha256:4fa24486b8bcca8eec45ee0eb166edc674795e53a2b53d1a9ef263eecebaac85` |
| Langfuse PostgreSQL | `docker.io/postgres:17@sha256:ae69c452f483507a6b99fb654cf93aad7fe156ffd2c56247707eef4e36d3c12b` |
| Prometheus | `docker.io/prom/prometheus:v3.15.0@sha256:efd719c99d83b060d9daefdcf00360461adf279f45ef5391f8d111892118753e` |
| Trivy action | `aquasecurity/trivy-action@ed142fd0673e97e23eac54620cfb913e5ce36c25` (tag `v0.36.0`) |

The Langfuse services, their variables and the `LANGFUSE_INIT_*` headless setup come from
`docker-compose.yml` at tag `v4.52.0`. Facts for P4-11:

- **Port 9090 clash.** That file publishes MinIO on host port `9090`, which clashes with
  Prometheus's `9090`. P4-11 publishes only `langfuse-web`, so the clash goes away.
- **Port 5432 clash.** It publishes its PostgreSQL on `127.0.0.1:5432`, which clashes with
  the research database. P4-11 removes that port, and Langfuse's PostgreSQL stays a
  separate service.
- **Images verified.** All images were pulled by digest and the stack came up healthy in
  25 s.
- **Restart policy.** Set `restart` to `"no"` for the opt-in profile, so the stack never
  starts by itself after a reboot.

## 3. Prometheus networking

Docker here is Docker Desktop with WSL integration. Two probes against a test server bound
to WSL `127.0.0.1:8099`:

| Container network | Target | Result |
| --- | --- | --- |
| `network_mode: host` | `127.0.0.1:8099` | refused: Docker Desktop's host network is not the WSL distribution's |
| default bridge with `extra_hosts: ["host.docker.internal:host-gateway"]` | `host.docker.internal:8099` | reachable, even though the server binds only to `127.0.0.1` |

**Method for P4-11:**
- Prometheus runs on the default Compose bridge network with
  `extra_hosts: ["host.docker.internal:host-gateway"]`.
- Its UI is published as `127.0.0.1:9090:9090`.
- Scrape targets:
  - `host.docker.internal:8001`: host API;
  - `host.docker.internal:9101`: host worker;
  - `api:8000`: Compose API, on the same network.

## 4. Memory with and without Langfuse

**Setup:**
- Host API on `127.0.0.1:8001`, the Phase 3 configuration, `research_phase1_review`, with
  Ollama, Qdrant and PostgreSQL in Compose.
- Each condition ran one `quick` and one `deep_research` run with the operations-guide
  example question. `free -m` was sampled every 5 s; it covers the whole WSL VM, Docker
  Desktop included.
- Unrelated containers also running, about 270 MiB in total: `p2_eval_20260927-*` and
  `ragpipeline-phase2-test-*`.

| Condition | Idle peak used | Peak used during runs | Lowest available | Peak swap used | Runs |
| --- | ---: | ---: | ---: | ---: | --- |
| Without Langfuse | 6,908 MiB | 7,966 MiB | 3,999 MiB | 2,318 MiB | quick answered (246 s active); deep partially supported (193 s) |
| With Langfuse v4.52.0 | 9,405 MiB | 9,650 MiB | 2,314 MiB | 3,195 MiB | quick answered (239 s); deep partially supported (184 s) |

The VM has 11,965 MiB of RAM and 4,096 MiB of swap. During the runs, the Langfuse
containers used about 3.0 GiB in all:

| Container | Memory |
| --- | ---: |
| ClickHouse | 993 MiB |
| web | 987 MiB |
| worker | 801 MiB |
| MinIO | 138 MiB |
| PostgreSQL | 93 MiB |
| Redis | 17 MiB |

Swap use grew by about 0.9 GiB, and run durations did not get worse.

**Recommendation:** Langfuse may run during live sweeps (P4-34), on these conditions:
- stop the unrelated `p2_eval_20260927-*` and `ragpipeline-phase2-test-*` containers
  first;
- watch available memory, and stop the `observability` profile if it falls below 1 GiB.

The JSONL trace files and the PostgreSQL run records do not depend on it (ADR-0026). One
sweep is about 42 runs over 3–4 hours. This spike measured two runs, not a sweep, so
ClickHouse growth over a long sweep is unmeasured.

## 5. Langfuse rendering of the planned attributes

A synthetic two-span trace was sent to `/api/public/otel/v1/traces` with Basic auth from
the project keys and `x-langfuse-ingestion-version: 4`. Reading it back through the API:

| Attribute sent | Result in Langfuse |
| --- | --- |
| `langfuse.observation.type=generation` | the observation type is `GENERATION` |
| `gen_ai.request.model` | `model` is set |
| `gen_ai.usage.input_tokens` / `output_tokens` | `usageDetails` `{input, output, total}` (total computed) |
| `langfuse.observation.input` / `output` | `input` / `output` are stored as given |
| `langfuse.session.id` on the root span | the root observation's `sessionId` |
| `langfuse.trace.name` | the trace name |
| `research.*` attributes | kept as observation metadata (`attributes.research.run_id`, and so on) |
| resource `service.name` | metadata `resourceAttributes.service.name` |

Every planned attribute rendered; none needs to change. Facts for later cards:

- **v4 read endpoints.** Langfuse v4 runs in "events_only" mode, where the v1 read
  endpoints `/api/public/traces` and `/api/public/observations` return 404. Reads use
  `/api/public/v2/observations`. The application only writes over OTLP, so this matters
  only to people inspecting data through the API rather than the UI.
- **Session ID.** It appears on the observation that carried the attribute (the root
  span). Child observations show an empty `sessionId` but share the trace.
