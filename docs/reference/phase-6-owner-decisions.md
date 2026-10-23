# Phase 6 owner decisions

**Status:** record of the owner's judgement calls during Phase 6, kept for later analysis.
Each entry gives the date, what was decided, the evidence it rested on, the alternatives
set aside, and what to re-examine later.

## Owner decisions

### 1. Planning interview (2026-10-13)

The owner answered 17 questions over four rounds and accepted the assistant's recommendation on
each, except Q4 (cost) and Q16 (hosting), where the owner ruled out any bill and made the public
demo optional. [ADR-0032](../adr/0032-phase6-public-cc-by-demo-collection.md) and
[ADR-0033](../adr/0033-phase6-delivery-without-hosting.md) record the design; the
[plan](../plans/phase-6-portfolio.md) lists the cards.

Evidence available at the time:
- **Spec:** section 21 Phase 6 deliverables and gate; section 3.1 goal 16 and section 22 require a
  deployed environment; section 18.2 allows a local-model demonstration paired with a hosted subset.
- **Rights:** all 103 permission records of the 102 documents in `research_phase1_review` are
  `cc-by`; display was off by choice. The NC-ND and personal-use files sit outside every snapshot.
- **Hosting (checked 2026-10-13 against official pages):** Hugging Face Docker Spaces need PRO
  ($9/month) and block outbound ports other than 80, 443 and 8080; Oracle Always Free gives
  2 Arm OCPUs and 12 GB but needs a card; Cloud Run's free tier has no hard spend cap; Qdrant Cloud
  free clusters are deleted after four idle weeks; Render, Koyeb, Fly and Railway are too small or
  not free; GHCR is free for public packages.
- **Code:** CI never pushes images; the locked environment lacks PyTorch, transformers and
  sentence-transformers, which the host environment has outside the lock; migrations are not in
  the image; the API starts and reports ready without Ollama.

| # | Topic | Decision | Alternatives set aside |
| --- | --- | --- | --- |
| Q1 | Scope | Deployment and portfolio only. Backlog #115, the unmerged local candidates and the 100K context stay out; the failure analysis reports the answer-quality gap | Taking #115 items into Phase 6 |
| Q2 | Public corpus | A public CC BY demo collection with passage display (ADR-0032) | Text withheld; deploying the private corpus |
| Q3 | Environment shape | A hosted backend subset with runs computed on the laptop (later superseded by Q16) | On-demand GPU; CPU generation; laptop tunnel |
| Q4 | Cost | No bills at all: "this is only a showcase project" | About €20/month for a VM |
| Q5 | UI | One static HTML page served by FastAPI | No UI; Streamlit or Gradio |
| Q6 | Images and releases | GHCR; `sha-` images from `main`; `vX.Y.Z` retags the tested digest; GitHub Releases | Rebuilding on tag |
| Q7 | Documentation | README rewritten as the portfolio front page; phase log to `docs/history.md`; architecture, benchmarks, failure analysis and operations documents | Appending to the current README |
| Q8 | Which corpus | The accepted 100-paper snapshot itself, after a per-document CC BY check | A 10–30 paper subset |
| Q9 | Public access | A published read-only demo key (dropped with Q16) | Anonymous read; keys on request |
| Q10 | Showcase runs | 6–10 runs on `main`, both modes, including the reference question and an insufficient-evidence run, started by principal `demo`; no model-call payloads | — |
| Q11 | Building the bundle | Allowlist export into a versioned bundle attached to a GitHub Release | `pg_dump` with deletions; re-ingesting |
| Q12 | Small mode | `scripts/demo_load.sh`, `docker compose up`, UI on CPU; live runs optional with the `llm` profile and a GPU | — |
| Q13 | Gate | `demo-smoke` workflow, cold-reviewer pass, owner review (the post-deploy check dropped with Q16) | — |
| Q14 | Video | A 3–5 minute recording by the owner from an agent-written script | — |
| Q15 | Hosted observability | JSON logs only (dropped with Q16) | — |
| Q16 | Hosting | **No hosted environment.** "Make this public demo thing optional. I do not want any bills. Just a video demonstration for recruiters would be enough which can be done just using my laptop." Changes LOCKED goal 16 (ADR-0033) | Oracle Always Free; Cloud Run with Neon and Qdrant Cloud; Hugging Face PRO |
| Q17 | ML stack in the image | A second, serving lock with CPU PyTorch and the host's model library versions; CI keeps the slim lock | One lock with everything; leaving the image unable to serve |

Re-examine later: whether a free host appears that fits; whether the CPU image's rankings match
the GPU host closely enough to say so in the README.

### 2. UI interview (2026-10-23)

The owner asked for a frontend before recording the video: "I cannot have a video of this project
working if I don't have a front end", and then "we need a frontend that anyone can use if they like,
not just for a few runs". The owner answered 17 questions over six rounds, accepting the assistant's
recommendation on each except Q3 (general use rather than a video prop), Q6 (observability added)
and Q7 (model-call text added). [ADR-0034](../adr/0034-phase6-product-ui.md) records the design;
the [plan](../plans/phase-6-portfolio.md) lists cards P6-21 to P6-32.

Evidence available at the time:
- **UI:** the P6-09 page searches papers or evidence and opens one run by `#run=`; it cannot start,
  list or cancel runs or show tool calls. The video script starts the live run in a terminal.
- **Run record:** `tool_calls`, `llm_calls`, `draft_claims` and `diagnose()` hold the timeline,
  verification and diagnosis; the HTTP run view returns only usage counts. `list_runs` exists in the
  run store without a route.
- **Model text:** `llm_call_payloads` are written at trace content `full` (the development default,
  which small mode uses), refused in production, deleted after 90 days, and kept out of bundle v1.
- **Operations:** `/ready` ignores the LLM; no run can be cancelled; run reads are limited to 120 a
  minute per key.

| # | Topic | Decision | Alternatives set aside |
| --- | --- | --- | --- |
| Q1 | Placement | New Phase 6 cards that block P6-18 | A new Phase 7 |
| Q2 | Video needs | Start runs from the UI, live progress, provenance panel, visual polish; paper pages | Run list (later taken in Q6) |
| Q3 | Purpose | **A frontend anyone who runs the stack can use, not only for a few runs** | A video-only prop |
| Q4 | Who builds | A throwaway prototype approved by the owner, then Codex Luna cards | Cards straight away; this session implements |
| Q5 | "Anyone" | Whoever clones and runs it; no hosting (ADR-0033 stands) | A hosted public UI |
| Q6 | Scope | Run history, filters, paper pages, capability awareness, read-only ingestion status, **and observability** | Driving ingestion from the UI; key management |
| Q7 | Observability | Timeline, budgets, drafted-claim verdicts, diagnosis, Langfuse link **and model-call text** | A system metrics dashboard |
| Q8 | Technology | Vanilla ES modules, no build step | Preact with htm vendored; React, Vite and TypeScript |
| Q9 | Tests | Python Playwright journeys in PR CI on fakes | Route tests only; JS unit tests under Node |
| Q10 | Model-text access | The run's owner with `read`, only when stored and under `trusted_private_local` | A new `inspect` scope; any principal |
| Q11 | Showcase model text | Bundle v2 with the showcase payloads, privacy-scanned | Keep payloads out (Phase 6 Q10) |
| Q12 | Live text | After each model call finishes; no streaming | Streaming thinking tokens |
| Q13 | API | Five owner-scoped routes in one ADR, within the section 3.2 non-goal | Revising the non-goal; an LLM entry in `/ready` |
| Q14 | Cancel | `POST /v1/research/{run_id}/cancel`, category `cancelled_by_principal` | Waiting out the budget |
| Q15 | Naming | `/record`, after the glossary's run record | A new "run activity" term |
| Q16 | Video | Live-run and diagnosis segments move into the browser; MCP stays in Claude Code | Keep the terminal segments |
| Q17 | Gate | `demo-smoke` API checks for the new routes; re-run gate items 1–2 on `v0.6.1` | Playwright on the real stack; gate unchanged |

Re-examine later: whether streaming thinking is worth its cost once the rest works; whether the
model-call route should reach MCP; that the bundle v2 export ran before the showcase payloads expire
(about mid-January 2027).

### 3. UI layout (2026-10-23, P6-22)

The owner reviewed the throwaway prototype (branch `prototype/p6-22-ui`, commit `9047560`,
`docs/demo/ui-prototype.html`) with three layouts on invented data: A Workbench (sidebar, run page
split into answer and run-record tabs), B Report (top navigation, the run reads as a document) and
C Console (waterfall timeline, inspector, claims ledger). Decision: **B Report**. "It looks best and
user friendly. The others are just overwhelming with information on one screen."

Consequences for P6-26 and P6-27: one reading column with top navigation; the run page is a document
in this order: question and status, answer with claim markers, claims with quotes and sources, "How
this answer was made" (a narrative timeline, model-call text behind a disclosure), "What verification
removed", diagnosis, budgets and provenance. The paper page shows the metadata the API serves (no
authors, venue or abstract: `GET /v1/papers/{paper_id}` is metadata only) with references, citing
papers and a search limited to the paper.

Re-examine later: whether long runs (many tool calls) need the timeline collapsed by planning round.
