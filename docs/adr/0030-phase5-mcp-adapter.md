---
status: accepted
date: 2026-10-12
---

# Phase 5: one MCP server over the shared research capabilities

Accepted by the project owner on 2026-10-12, after the Phase 5 planning interview
([owner decisions](../reference/phase-5-owner-decisions.md), Q1–Q5, Q7–Q10, Q12). It
implements source-of-truth section 11 and resolves open decision 13 (MCP SDK and
transport version). The SDK facts below were checked in a throwaway prototype
([SDK spike](../reference/phase-5-mcp-sdk-spike.md)).

## Context

- Section 21 makes Phase 5 the MCP phase. Its gate: an external MCP client and the internal
  LangGraph agent use the same core research capability without duplicated business logic.
- The agent already reaches retrieval through framework-independent service protocols
  (`ResearchTools`). The HTTP routes call the same services, but each route also holds use-case
  logic: the request deadline, error mapping, response checks, the citation cursor, the
  served-snapshot check and the active-run limit. An MCP adapter that copied that logic would
  fail the gate.
- MCP specification revision 2026-07-28 removed protocol sessions and the `initialize`
  handshake, and deprecated Roots, Sampling and Logging. The official Python SDK `mcp` 2.3.0
  (2026-10-02, on conda-forge) implements it and serves 2025-era clients from the same app.
- The retrieval models use about 1.9 GiB of the RTX 3050's 4 GiB beside the generator. A
  second process would load them again.
- Phase 4 gave the HTTP API hashed API keys with scopes, run ownership and per-key rate
  limits (ADR-0027). A key with the `research` scope can start a `deep_research` run whose
  agent then requests ingestion, although ingestion over HTTP needs the `ingest` scope.

## Decision

1. **One shared capability service.** `research_platform.services.capabilities.ResearchCapabilities`
   holds the use cases: paper and evidence search, paper reads, citation pages, related papers,
   the served snapshot, run start and run read. It owns the deadline, error mapping, response
   checks, cursor encoding, the snapshot check and the active-run limit. The HTTP routes and the
   MCP tools both call it; neither repeats that logic. `AppError` moves to
   `research_platform.services.errors` and `api.errors` re-exports it.
2. **SDK and protocol.** `mcp==2.3.0` from conda-forge, pinned in the lock. The server is the
   SDK's `MCPServer` and targets protocol revision 2026-07-28; the SDK also answers 2025-11-25
   clients. Deprecated features (Sampling, Roots, Logging) and the optional tasks extension are
   not used.
3. **Hosting and transport.** The SDK's Streamable HTTP app is mounted at `/mcp` inside the
   FastAPI process, with `stateless_http=True` and `json_response=True`, so no server-side
   session state exists for either protocol era. The API lifespan runs the SDK session manager.
   The endpoint URL is `http://127.0.0.1:8001/mcp/`; `/mcp` redirects there with 307.
   There is no stdio transport: a stdio server is its own process and would load the retrieval
   models a second time.
4. **Host and origin checks.** The SDK's DNS-rebinding protection is on. Allowed hosts come from
   `RESEARCH_PLATFORM_MCP_ALLOWED_HOSTS` (default `127.0.0.1:*,localhost:*,[::1]:*`) and allowed
   origins from `RESEARCH_PLATFORM_MCP_ALLOWED_ORIGINS` (default empty, so any request carrying an
   `Origin` header is refused). A wrong host gets 421.
5. **Authentication.** The Phase 4 API keys, checked by an ASGI wrapper around the mounted app
   that calls the same header check as the HTTP dependency. A missing or bad key gets the same 401
   JSON error as the HTTP API, with `WWW-Authenticate: Bearer`. The authenticated principal is
   passed to tool code through a context variable. In `disabled` auth mode the caller is the
   `local` principal, as over HTTP. The SDK's `TokenVerifier` path was set aside because it
   requires an OAuth issuer URL and publishes protected-resource metadata naming an authorization
   server that does not exist.
6. **Authorization and limits per tool.** Each tool and resource has a scope and an ADR-0027
   route class, enforced with the same functions as the HTTP routes:

   | Tool or resource | Scope | Route class |
   | --- | --- | --- |
   | `search_papers`, `search_evidence` | `read` | search |
   | `get_paper`, `get_citations`, `get_references`, `find_related_papers`, `paper://{paper_id}` | `read` | paper read |
   | `start_research_run` | `research` | research run creation |
   | `get_research_run`, `research-run://{run_id}` | `read` | run read |

   The 64 KiB body limit applies to `/mcp` as to every route. Run ownership is unchanged: another
   principal's run reads as not found.
7. **Surface.** Eight tools and two resource templates; no prompts.
   - Retrieval uses the served snapshot and its frozen retrieval profile in `reranked` mode, as
     the agent does. `snapshot_id` is optional; another snapshot gets `incompatible_snapshot`.
   - `find_related_papers` uses shared references and co-citations, not embedding similarity.
   - `start_research_run` accepts `quick` and `deep_research` and returns the queued run.
     `get_research_run` returns the run view and `poll_after_seconds` (30 while the run is
     active, absent once it is `completed` or `failed`).
   - `discover_papers` and `request_ingestion` are not exposed; they stay inside `deep_research`
     runs, where code budgets them.
   - Tool results are typed structured output. Search results are compact (IDs, titles, ranks,
     reranker score, page, section and, when the text policy allows it, text), following the
     guidance to return high-signal, token-efficient results. The seven read tools carry
     `readOnlyHint`.
8. **Errors.** An `AppError` becomes an MCP tool error whose text is `<code>: <message>`. Invalid
   arguments are tool errors from the SDK's schema validation. Unexpected exceptions become a
   generic tool error with no internal text. Resource failures raise the SDK `ResourceError` with
   the same text.
9. **Ingestion needs the `ingest` scope everywhere.** A research run records
   `ingestion_permitted` when it is created (migration 028): true only when the starting key has
   the `ingest` scope. When it is false, the membership policy refuses every paper the run proposes
   with the reason `ingest_scope_required`. The check lives in the shared run start, so HTTP and
   MCP behave the same. Prompts and tool lists do not change, so configuration hashes stay
   comparable. Runs created before migration 028 keep `true`.
10. **Telemetry.** Each tool or resource call gets a span named `mcp.<name>` with
    `research.mcp.tool`, `research.mcp.status` and, at content `ids` or `full`,
    `research.mcp.principal`; and the metrics `research_mcp_calls_total{tool,status}` and
    `research_mcp_call_duration_seconds{tool}`. A client's trace context is not used as the
    parent. Arguments are never logged.
11. **Gate.** All in CI except item 4:
    1. Parity: on the same fake services, each MCP tool returns the same identifiers, ranks and
       statuses as the HTTP route and, where the agent has the tool, as `ResearchTools`.
    2. Import boundary: no module in `research_platform.mcp` or
       `research_platform.services.capabilities` imports a database, vector-store, ranking or
       agent module.
    3. Security suite over HTTP: authentication, scopes, rate limits, ownership, body limit, host
       and origin checks, the text policy (ADR-0031) and inert injected arguments.
    4. Live: an MCP Inspector CLI session against the development stack, reviewed by the owner.
       A Claude Code session is reported, not gated.

## Alternatives set aside

- **A separate `research-mcp` process** or a stdio server: loads the retrieval models twice on a
  4 GiB GPU.
- **The SDK `TokenVerifier` with `AuthSettings`:** needs an OAuth issuer that does not exist.
- **OAuth 2.1 with an authorization server:** a non-goal (section 3.2); revisit in Phase 6 only if
  the public demo needs browser clients.
- **The tasks extension or a blocking run tool:** client support for tasks is uneven; a blocking
  call holds a request open for minutes, and the 2026 transport loses in-flight requests on
  disconnect.
- **Prompts** (`literature_review`, `compare_methods`): new prompt engineering with no measured
  value; optional in section 11.2.
- **MCP tools that call `ResearchTools`:** its budgets, evidence handles and depth ledger are
  agent state, not use cases.

## Consequences

- `routes.py` and `research_routes.py` become thin transport adapters; their tests guard the
  refactor.
- The `mcp` SDK and its dependencies (`mcp-types`, `sse-starlette`, `pyjwt`, `httpx2`) enter the
  lock and the Trivy scan.
- A deep run started with a `research`-only key can no longer ingest papers; the owner's local key
  or a key with `ingest` keeps the old behaviour.
- A client must send `Authorization: Bearer <key>`; clients that try OAuth discovery after a 401
  will not find metadata.
- The MCP server is reachable only where the API is; a stopped API stops both.
