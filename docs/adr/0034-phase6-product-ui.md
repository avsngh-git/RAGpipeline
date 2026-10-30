---
status: accepted
date: 2026-10-23
---

# Phase 6: a usable research UI over the run record

Accepted by the project owner on 2026-10-23 in the Phase 6 UI interview
([owner decisions](../reference/phase-6-owner-decisions.md), entry 2). It amends
[ADR-0033](0033-phase6-delivery-without-hosting.md) decisions 4, 7 and 8. Section 3.2's LOCKED
non-goal ("an elaborate frontend that competes with the retrieval and systems work") is unchanged:
the owner and the assistant read this UI as within it, because it adds no framework, no build step
and no product logic, only views over existing services.

## Context

- The P6-09 page at `GET /` searches papers or evidence and opens one run from `#run=<run_id>` with
  a manual refresh. It cannot start a run, list runs, cancel a run or show what a run did. The
  recruiter video (P6-18) therefore starts the live run and shows its diagnosis in a terminal.
- The owner wants a frontend that anyone who runs the stack can use for their own work, not only for
  a few showcase runs, and wants the run's observability, including model-call text, in it.
  "Anyone" means a person who clones and runs the stack (CPU small mode, live runs with a GPU); no
  hosted environment is added (ADR-0033 decision 1 stands).
- The run record already holds what such a view needs: `tool_calls` (name, validated arguments,
  status, duration, error category, ordinal), `llm_calls` (kind, model, prompt version, attempts,
  tokens, thinking characters, duration, trace and span IDs), `draft_claims` with verdicts, budgets
  and usage, and `diagnose()` in `research_platform.runs.diagnosis`. The HTTP run view returns only
  usage counts.
- `llm_call_payloads` (messages, output, thinking) are written only at trace content `full`, the
  default when `RESEARCH_PLATFORM_ENVIRONMENT=development`, which Compose small mode sets; `full` is
  refused in production; payloads are deleted after 90 days (ADR-0026). ADR-0033 decision 4 keeps
  them out of the demo bundle.
- `/ready` does not report the LLM: the API is ready without Ollama, which CPU small mode relies on.
  The UI cannot tell whether a started run can execute.
- No route cancels a run; a mistaken `deep_research` run holds one of the principal's two active-run
  slots and the GPU for up to its 1,800 s budget. Section 7.4 asks for safe cancellation.
- Run reads are limited to 120 per minute per key (ADR-0027).

## Decision

1. **Views.** The page at `/` offers, behind the existing API-key prompt:
   - paper and evidence search with year-range and evidence-kind filters;
   - paper pages (metadata, abstract, references, citing papers) linked from every hit and claim;
   - a run form (question, `quick` or `deep_research`, year range), disabled with the reason when
     the key lacks `research` or research runs cannot execute;
   - run history: the principal's runs, newest first, paginated;
   - the run page: status, answer, claims with their quotes and papers, provenance, read-only
     ingestion status and proposed papers (`uningested_candidates`), and a Cancel button;
   - the run record on the run page: a timeline of tool calls and model calls, budgets against
     their limits, the drafted claims with their verdicts, the diagnosis, model-call text, and a
     link to the Langfuse trace when a Langfuse URL is configured.
   A running run is polled about every 3 s (run view and record, about 40 reads a minute).
2. **Technology.** Plain JavaScript ES modules and one stylesheet served from package data under
   `/ui/`, with an allowlist of file names; no build step, no framework, no vendored library, no
   new runtime dependency. The CSP stays `script-src 'self'`. Retrieved and model text is inserted
   with `textContent` only. The layout is settled by a throwaway prototype the owner approves (P6-22)
   before the cards are fixed.
3. **Routes.** Five HTTP routes, each scoped to the run's owner and implemented through
   `ResearchCapabilities` so that MCP could expose them later without new logic. They are not added
   to MCP in Phase 6.

   | Route | Scope | Returns |
   | --- | --- | --- |
   | `GET /v1/research?limit&cursor` | `read` | the principal's runs, newest first: run ID, status, mode, outcome, question, timestamps |
   | `GET /v1/research/{run_id}/record` | `read` | tool calls, model-call metadata, drafted claims and verdicts, limits and usage, diagnosis, `trace_id` |
   | `GET /v1/research/{run_id}/model-calls/{ordinal}` | `read` | messages, thinking and output of one model call (decision 4) |
   | `POST /v1/research/{run_id}/cancel` | `research` | the run view after cancellation (decision 5) |
   | `GET /v1/me` | `read` | principal, scopes, whether research runs can execute, the Langfuse UI URL if configured |

   The route is named after the glossary's **run record**; no "activity" term is added. `/ready`
   is unchanged.
4. **Model-call text.** Served to the run's owner only when the payload was stored and the server's
   evidence access profile is `trusted_private_local`, the condition under which the HTTP API
   already returns passage text. Otherwise the route answers with an explicit `not_recorded` or
   `withheld` state, and the UI says why. Text appears after each model call finishes; thinking is
   not streamed.
5. **Cancellation.** Cancelling a queued, running or waiting run ends it as `failed` with the new
   failure category `cancelled_by_principal`, releases its active-run slot and keeps the partial run
   record (tool calls, model calls, drafted claims). Cancelling a finished run is a conflict, not a
   change.
6. **Bundle v2.** A new bundle `research-demo-v2` (release `demo-data-v2`) adds `llm_call_payloads`
   for the showcase runs only, after the bundle privacy scan, so a reviewer without a GPU sees the
   model text of showcase runs. Everything else excluded by ADR-0033 decision 4 stays excluded. The
   export must run before the payloads expire (90 days after the showcase runs, about mid-January
   2027). This reverses the "no model-call payloads" part of Phase 6 owner decision Q10.
7. **Tests and gate.** Browser journeys run in pull-request CI with Python Playwright
   (`pytest-playwright`) against the app wired to in-memory fakes: search, paper page, start a run,
   watch its timeline to completion, a dropped drafted claim, cancel, and the disabled run form. The
   `demo-smoke` workflow (ADR-0033 gate item 1) adds API checks against the real small-mode stack:
   the run list, a showcase run record with drafted claims, showcase model text, and `/v1/me`
   reporting that research runs cannot execute on CPU. Gate items 1 and 2 are re-run on release
   `v0.6.1` with bundle v2, and the video script's live-run and diagnosis segments move into the
   browser before P6-18.

## Alternatives set aside

- **A framework with a build step (React, Vite, TypeScript):** Node in CI and the image and a new
  dependency tree to pin and scan, for six views over five endpoints; against the non-goal.
- **A vendored component library without a build (Preact with htm):** one third-party file to track
  for little gain at this size.
- **A hosted UI for anyone on the internet:** reopens ADR-0033 (cost, public key, abuse limits).
- **Streaming thinking tokens live:** changes the Ollama adapter, run execution and storage for a
  display effect; the video can speed up the wait.
- **A system metrics dashboard in the UI:** Prometheus already serves `/metrics`; a run-level view
  shows the engineering better.
- **Key management in the UI:** admin endpoints and security surface for an operator task the
  `research-keys` CLI already does.
- **A separate `inspect` scope or any-principal access to model text:** a new scope to manage, or
  exposure beyond the run's owner.
- **An LLM entry in `/ready`:** CPU small mode would report not ready and fail `demo-smoke`.
- **Playwright against the real stack on the runner:** more disk and flakiness on a runner already
  holding a 4 GB image, for little evidence beyond the API checks.

## Consequences

- The test lock gains `pytest-playwright`, and CI downloads Chromium.
- The demo bundle grows by the showcase payloads; `scripts/demo_load.sh` points at `demo-data-v2`.
- ADR-0033 decision 7 now describes the views above; decision 4 has the showcase-payload exception;
  decision 8 item 1 has the added checks.
- `FailureCategory` gains `cancelled_by_principal`; explain and the evaluation reports treat it as
  a principal action, not a system failure.
- Section 21's Phase 6 cards gain P6-21 to P6-32, and P6-18 waits for them.
