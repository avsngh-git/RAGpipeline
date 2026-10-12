# Phase 5 — MCP

Status: accepted by the owner on 2026-10-12 (owner decision 4). Planned with the owner on 2026-10-12. The decisions are in two ADRs:

- [ADR-0030](../adr/0030-phase5-mcp-adapter.md): the shared capability service, SDK and
  protocol version, mounting, transport, authentication, tools and resources, errors,
  telemetry, ingestion scope, the gate.
- [ADR-0031](../adr/0031-phase5-external-passage-exposure.md): which evidence text an
  external client may receive.

The owner's interview answers are in the [owner decisions](../reference/phase-5-owner-decisions.md);
the SDK facts are in the [SDK spike](../reference/phase-5-mcp-sdk-spike.md); the
[handoff](phase-5-agent-handoff.md) records card progress. Section 21 of the
[source of truth](../agents/scientific-research-platform-source-of-truth.md) records the phase.

## Goal

An external MCP client and the internal LangGraph agent use the same core research capability
without duplicated business logic (section 21 gate). The other Phase 5 deliverables:

- one MCP server over existing services;
- selected tools and resources;
- local and remote transport configuration (Streamable HTTP only; stdio set aside, ADR-0030);
- protocol-level tests, authentication and a usage example.

## Gate

Defined in ADR-0030 decision 11:

1. CI: MCP tool results match the HTTP routes and `ResearchTools` on the same fake services (P5-13).
2. CI: the import boundary of `research_platform.mcp` and the capability service (P5-13).
3. CI: the MCP security suite (P5-14).
4. Live, development stack: an MCP Inspector CLI session reviewed by the owner; a Claude Code
   session reported, not gated (P5-16).

Answer quality is not part of this phase (owner decision Q1; backlog
[#115](https://github.com/avsngh-git/RAGpipeline/issues/115)).

## Design in one picture

```text
external client ──HTTP──▶ /mcp  (McpAuthGate → SDK Streamable HTTP app → tool modules)
                                                                      │
HTTP client ────HTTP──▶ /v1/... (FastAPI routes)                      │
                                   │                                  │
                                   ▼                                  ▼
                    services.capabilities.ResearchCapabilities  (deadline, errors, cursor,
                                   │                             snapshot, run start)
LangGraph agent ──▶ ResearchTools ─┤
                                   ▼
             search / paper / citation / related services, run store and executor
```

## How the work is organized

- Map issue [#169](https://github.com/avsngh-git/RAGpipeline/issues/169) holds the card table,
  the decisions and the fog. The cards are issues #170 to #186 (P5-01 to P5-17 in order),
  labelled `wayfinder:task`, sub-issues of #169, with native blocked-by links.
- **Implementers:**
  - `ready-for-agent` cards are written for Codex Luna agents working alone and in parallel.
    Each card has its rules, exact files and signatures, numbered steps, named tests and a done
    list, plus the verified SDK facts it needs;
  - `ready-for-human` cards need the Conda lock, live services, private data or the owner.
- **Workflow:** one branch (`phase5/p5-NN-short-name`) and one pull request per card; the
  planning session reviews each pull request before merge; blockers keep cards that edit the
  same functions in sequence. Each MCP tool group has its own module, so P5-10, P5-11 and P5-12
  run in parallel.
- **Migration:** 028 `research_runs.ingestion_permitted` (P5-05).
- **Live data:** agent cards never touch `research_phase1_review`, live Qdrant or Ollama.

| Card | Issue | Type | Delivers | Blocked by |
| --- | --- | --- | --- | --- |
| P5-01 | #170 | human | ADRs, plan, handoff, SDK spike, owner decisions, source of truth 1.41 | — |
| P5-02 | #171 | human | Housekeeping: Trivy exceptions before 2026-11-06, stale experiment, Ollama recreate | — |
| P5-03 | #172 | human | `mcp==2.3.0` in the Conda lock | P5-01 |
| P5-04 | #173 | agent | `ResearchCapabilities` for retrieval; `AppError` and cursor moved; routes refactored | P5-01 |
| P5-05 | #174 | agent | Migration 028 `ingestion_permitted`; `ingest_scope_required` refusal | P5-01 |
| P5-06 | #175 | agent | Run capabilities: served snapshot, run start and read; research routes refactored | P5-04, P5-05 |
| P5-07 | #176 | agent | Text exposure policy setting and run-view redaction | P5-01 |
| P5-08 | #177 | agent | Shared auth and rate-limit helpers; `McpAuthGate`; principal context | P5-01 |
| P5-09 | #178 | agent | MCP server, `/mcp` mount, tool runtime (access, limits, span, metrics, errors) | P5-03, P5-06, P5-07, P5-08 |
| P5-10 | #179 | agent | `search_papers`, `search_evidence` | P5-09 |
| P5-11 | #180 | agent | `get_paper`, `get_citations`, `get_references`, `find_related_papers`, `paper://` | P5-09 |
| P5-12 | #181 | agent | `start_research_run`, `get_research_run`, `research-run://` | P5-09 |
| P5-13 | #182 | agent | Gate items 1 and 2: parity and import boundary | P5-10, P5-11, P5-12 |
| P5-14 | #183 | agent | Gate item 3: MCP security suite | P5-10, P5-11, P5-12 |
| P5-15 | #184 | agent | `docs/operations/mcp.md`, Inspector check script, README | P5-12 |
| P5-16 | #185 | human | Gate item 4: Inspector session, Claude Code demo, gate report | P5-02, P5-03, P5-13, P5-14, P5-15 |
| P5-17 | #186 | human | Closeout | all |

## Risks and fallbacks

| Risk | Detection | Response |
| --- | --- | --- |
| The lock's FastAPI 0.141 or Starlette 1.6 differ from the spike's 0.138 and 1.3 | P5-03 CI, P5-09 tests | Fix in P5-09; record the difference in the spike report |
| The SDK resolves a package import named `mcp` inside `research_platform.mcp` wrongly | P5-09 mypy and tests | Absolute imports resolve the top-level SDK; if not, rename the package `research_platform.mcp_server` and record it |
| A refactored route changes an HTTP response | Existing API tests in P5-04 and P5-06 | The card stops; never edit an existing assertion |
| The Trivy scan flags a new SDK dependency | P5-03 CI | Upgrade, or the owner approves a dated exception |
| A client cannot send a bearer header | P5-16 | Document the client; OAuth stays out of scope until Phase 6 |
| Trivy exceptions expire on 2026-11-06 mid-phase | P5-02 | Resolve or renew before the date |

## Not in Phase 5

- answer-quality work, the planner, the `answered` definition and the rest of backlog #115;
- stdio transport, OAuth, MCP prompts, the tasks extension;
- exposing `discover_papers` or `request_ingestion`;
- per-paper public display;
- deployment and a UI (Phase 6).
