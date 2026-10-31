# 12. Observability and security

## Observability

The platform produces three kinds of signal, and none of them is the only source of truth ([ADR-0026](../adr/0026-phase4-observability-and-run-records.md)).

| Signal | What it holds | Where |
| --- | --- | --- |
| **Run records** | What a run did: configuration, tool calls, model calls, drafted claims and verdicts, outcome | PostgreSQL. These are authoritative. |
| **Traces** | One trace per request, with nested spans for validation, each agent node, each tool call, lexical and dense search, fusion, reranking, model calls, verification and persistence | JSONL files (development default), optionally exported over OTLP to a self-hosted Langfuse |
| **Logs** | Structured JSON events with timestamp, level, logger, request ID and safe HTTP metadata | Standard output (`docker compose logs api`) |
| **Metrics** | Request rate, errors and latency per route; run active time per mode; model-call duration per kind; tool calls by status; authentication failures; ingestion backlog | Prometheus at `/metrics`; the worker on `127.0.0.1:9101` |

Every HTTP request gets an `X-Request-ID`, returned in headers and error bodies and attached to logs. Runs record their `trace_id`, so a run, its logs and its trace can be joined.

### Trace content levels

Traces can hold prompts and passages, so their content is controlled by `RESEARCH_PLATFORM_TRACE_CONTENT`:

| Level | Contents |
| --- | --- |
| `none` | Span names, timings and counts |
| `ids` | Plus identifiers and scores (default outside development) |
| `full` | Plus prompts, model output and query text (default in development; refused in production) |

Logs never hold text at any level. Exception events, which OpenTelemetry records by default with full messages and stack traces, are never recorded. Below `full`, a failed span records only its error class. The rule is applied to every span by the `PrivateTracer` wrapper.

### Optional stack

`docker-compose.observability.yml` adds Prometheus (`127.0.0.1:9090`) and a self-hosted Langfuse v4 (`127.0.0.1:3000`). Langfuse uses about 3 GiB of memory, which matters on a small machine. See the [observability guide](../operations/observability.md) for the setup and example Prometheus queries.

## Security

### Model

| Control | Implementation |
| --- | --- |
| Authentication | API keys stored as SHA-256 hashes with a short prefix; bearer header only ([ADR-0027](../adr/0027-phase4-authentication-and-rate-limits.md)) |
| Authorization | Scopes `read`, `research`, `ingest`, `admin`; enforced on routes, MCP tools and run-triggered ingestion alike |
| Ownership | A run belongs to its principal; others get `404` |
| Rate limits | Per-principal token buckets per route class, and an active-run cap |
| Input limits | 64 KiB bodies, 2,000-character queries and questions, bounded result limits, tamper-checked cursors |
| Network | Compose ports bind to `127.0.0.1`; MCP `Host` and `Origin` allow-lists |
| Errors | One envelope with a code and request ID; no exception text or stack traces |
| Secrets | Environment only; `.env` is git-ignored; CI scans the repository for secrets |
| Supply chain | Conda locks and hash-pinned wheels; `pip check` and `pip-audit` in CI; Trivy scans the image for HIGH and CRITICAL vulnerabilities, with time-limited exceptions in `.trivyignore` |
| Data exposure | Evidence text needs a server-side access profile; external clients get only publicly displayable text by default ([ADR-0031](../adr/0031-phase5-external-passage-exposure.md)) |

### Prompt injection and tool abuse

The system assumes that retrieved documents can contain malicious instructions. Retrieved text is labelled as evidence, never instruction, and the controls that matter are enforced in code rather than in the prompt:

- Tools accept only typed arguments; there is no SQL, URL, file or code access.
- Budgets, repetition, citation depth and ingestion permission are checked outside the model.
- The model sees run-local handles, and unknown or unshown handles are rejected, so a passage cannot inject a fabricated citation.
- Claims survive only if code finds their quotes in the cited passages.
- Ingestion decisions are made by policy code with exact-file permission checks and spend caps.

Tests cover these in `tests/security/`:

- `test_scripted_attacks.py`: scripted injection cases;
- `test_api_attacks.py`;
- `test_mcp_attacks.py`: keys, scopes, rate limits, ownership, request limits, host and origin checks, text exposure and cursor tampering;
- `test_online_surfaces.py`.

The live `security-live` suite runs eight cases against the real model. Over three repeated runs it found one real code gap, where the insufficient-evidence path exposed unverified model text. That gap was fixed. It also found two cases where the small model followed injected text while the code controls held. See the [security report](../reference/phase-4-security-live-report.md).

### Checkpoint deserialization

LangGraph checkpoints are restored with an allow-list of exactly the types the run state can hold. Any other class comes back as raw data and is logged ([GHSA-g48c-2wqr-h844](https://github.com/advisories/GHSA-g48c-2wqr-h844)). `tests/test_checkpoint_allowlist.py` fails if a new state type is missing from the list.

### What is not covered

There is no OAuth, user accounts, multi-tenant isolation or public deployment hardening. The project is a self-hosted, loopback-bound service by design ([ADR-0033](../adr/0033-phase6-delivery-without-hosting.md)). Before exposing it publicly, set the MCP host and origin allow-lists, use `production` mode, and put a TLS-terminating proxy in front.

Next: [Operations](13-operations.md).
