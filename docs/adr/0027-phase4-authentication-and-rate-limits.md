---
status: proposed
date: 2026-10-06
---

# Phase 4: API-key authentication, run ownership, rate limits and scanning

Proposed on 2026-10-06 after the Phase 4 planning interview, in which the owner chose the
options recorded here ([owner decisions](../reference/phase-4-owner-decisions.md), Q5,
Q10, Q11, Q15). It resolves open decision 9 (authentication) in source-of-truth section 23
and applies the baseline controls of section 15.

## Context

- The API has no authentication, no rate limiting and no request body limit. The only
  backpressure is a run queue capped at 100.
- Ports bind to loopback (ADR-0006), but Phase 6 will deploy the API, and Phase 5's remote
  MCP server must use "the same service-layer authorization as the HTTP API" (section
  11.3).
- Research runs are expensive: synthesis takes minutes on the RTX 3050. One caller could
  occupy the single run worker for hours.
- CI runs `pip-audit` but scans neither the container image nor the repository for
  secrets.
- An enterprise identity platform is a LOCKED non-goal (section 3.2).

## Decision

1. **API keys.**
   - A key is `rsk_` followed by 43 URL-safe random characters.
   - Only its SHA-256 and an 8-character prefix are stored, in `api_keys`, with a principal
     name, scopes and a revocation time.
   - Keys are created, listed and revoked with the `research-keys` CLI. The plain key is
     shown once.
   - A plain SHA-256 is enough because the keys are high-entropy random values.
2. **Scopes.** `read` (papers, evidence, own runs), `research` (start runs), `ingest`
   (collection ingestion) and `admin` (all scopes; reads every run).
3. **Transport.** Keys are sent as `Authorization: Bearer <key>`.
   - A missing key returns 401 `authentication_required` with `WWW-Authenticate: Bearer`.
   - A bad or revoked key returns 401 `invalid_api_key`.
   - A missing scope returns 403 `insufficient_scope`.
   - `/health`, `/ready`, `/metrics` and the OpenAPI documents stay public.
4. **Disabled mode.** `RESEARCH_PLATFORM_AUTH_MODE=disabled` is accepted only in
   development or test, with a loopback bind host (`RESEARCH_PLATFORM_API_BIND_HOST`). The
   app refuses to start otherwise. In disabled mode the caller is the `local` principal,
   with every scope.
5. **Run ownership.**
   - `research_runs.principal` records who started a run.
   - Reading another principal's run returns the same 404 as a missing run, so run IDs
     cannot be probed.
   - `admin` reads every run.
   - Runs created before this change belong to `legacy-local`.
6. **Rate limits.** Token buckets are kept in memory per key and route class:

   | Route class | Limit |
   | --- | --- |
   | research run creation | 20 per hour |
   | search and evidence search | 60 per minute |
   | paper reads | 120 per minute |
   | ingestion | 10 per hour |
   | run and ingestion-request reads | 120 per minute |

   - A key may have at most 2 queued or running runs.
   - Over a limit, the API returns 429 with `Retry-After`.
   - A request body over 64 KiB returns 413.
   - Every limit is a setting.
   - In-memory buckets are correct for one API process; more replicas would need a shared
     store (Phase 6).
7. **Scanning.** CI runs Trivy:
   - The built image fails CI on a HIGH or CRITICAL vulnerability that has a fix.
   - The repository fails CI on any detected secret.
   - Accepted findings go in `.trivyignore`, each with a reason and an expiry date; a test
     rejects entries without them.

## Consequences

- Every client of `/v1` needs a key. The evaluation scripts read `RESEARCH_PLATFORM_API_KEY`.
- Phase 5 can verify MCP callers with the same key store. Whether remote MCP also needs
  OAuth is a Phase 5 decision.
- Tests default to disabled mode, so existing API tests keep working. New tests cover the
  key mode.
- A restart resets the rate-limit buckets. That is acceptable for one local process.

## Alternatives considered

- **One static token from the environment.** It cannot tell callers apart or scope them,
  and revoking it means rotating it for everyone.
- **OAuth or OIDC.** It approaches the excluded enterprise identity platform, without a
  current need.
- **A slow password hash (bcrypt, argon2) for keys.** Unnecessary for 256-bit random keys,
  and it costs time on every request.
- **Rate limits stored in PostgreSQL or Redis.** They add writes on every request, or a new
  service, before more than one API process exists.
