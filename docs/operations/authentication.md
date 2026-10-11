# API keys, authentication and rate limits

The HTTP API authenticates callers with hashed API keys ([ADR-0027](../adr/0027-phase4-authentication-and-rate-limits.md)).
Keys live in the `api_keys` table (migration 026); only a SHA-256 hash and a short prefix
are stored.

## Modes

`RESEARCH_PLATFORM_AUTH_MODE` selects the mode:

| Mode | Default when | Behaviour |
| --- | --- | --- |
| `api_key` | every environment except `test` | each request needs `Authorization: Bearer <key>` |
| `disabled` | `test` | every request runs as principal `local` with all scopes |

`disabled` is refused at startup in `production` or when `RESEARCH_PLATFORM_API_BIND_HOST`
is not a loopback address (`127.0.0.1`, `localhost`, `::1`). The host API therefore needs a
key, or `RESEARCH_PLATFORM_AUTH_MODE=disabled` on loopback during development.

## Scopes

| Scope | Allows |
| --- | --- |
| `read` | search, evidence search, papers, citations, reading own research runs |
| `research` | starting research runs |
| `ingest` | collection ingestion and its status |
| `admin` | every scope, and reading other principals' runs |

A run belongs to the principal that started it. Another principal gets 404 for it unless
its key has `admin`.

## Managing keys

`research-keys` uses `RESEARCH_PLATFORM_DATABASE_URL`.

```bash
research-keys create --principal alice --scope read --scope research
research-keys list
research-keys revoke KEY_ID
```

`create` prints the key once, as `api_key` in its JSON output. Store it then; it cannot be
shown again. Principal names are lower-case letters, digits, `.`, `_` and `-`, at most 63
characters. `list` shows prefixes and scopes, never keys.

Evaluation suites that call the API (`agent-dev`) send `RESEARCH_PLATFORM_API_KEY`.

## Errors

| Status | Code | Cause |
| --- | --- | --- |
| 401 | `authentication_required` | no `Bearer` header |
| 401 | `invalid_api_key` | unknown or revoked key |
| 403 | `insufficient_scope` | key lacks the route's scope |
| 413 | — | request body above the limit |
| 429 | `rate_limited` | route-class rate limit; see `Retry-After` |
| 429 | `too_many_active_runs` | active-run limit; `Retry-After: 30` |
| 503 | `authentication_unavailable` | the key store is not configured |

Failures are counted in the `research_auth_failures_total` metric by reason
(`missing`, `invalid`, `scope`).

## Rate and size limits

Limits are in-memory token buckets per principal and route class. They reset when the API
restarts and are not shared between processes.

| Route class | Default | Variable |
| --- | --- | --- |
| Start a research run | 20 per hour | `RESEARCH_PLATFORM_RATE_LIMIT_RESEARCH_CREATE` |
| Search and evidence search | 60 per minute | `RESEARCH_PLATFORM_RATE_LIMIT_SEARCH` |
| Paper, citation and reference reads | 120 per minute | `RESEARCH_PLATFORM_RATE_LIMIT_PAPER_READ` |
| Ingestion | 10 per hour | `RESEARCH_PLATFORM_RATE_LIMIT_INGEST` |
| Run status reads | 120 per minute | `RESEARCH_PLATFORM_RATE_LIMIT_RUN_READ` |

Each variable takes `capacity/seconds`, for example `60/60`. Other limits:

- `RESEARCH_PLATFORM_MAX_ACTIVE_RUNS_PER_KEY` (default 2): a principal with that many
  queued, running or waiting-for-ingestion runs gets 429.
- `RESEARCH_PLATFORM_MAX_BODY_BYTES` (default 65,536): larger bodies get 413.
