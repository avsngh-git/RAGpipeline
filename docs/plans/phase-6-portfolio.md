# Phase 6 — Release, small mode and portfolio

Status: planned with the owner on 2026-10-13. The decisions are in two ADRs:

- [ADR-0032](../adr/0032-phase6-public-cc-by-demo-collection.md): the accepted 100-paper
  snapshot becomes a public CC BY demo collection, after a per-document display check.
- [ADR-0033](../adr/0033-phase6-delivery-without-hosting.md): no hosted environment; a serving
  lock; GHCR images and releases; the demo bundle; the reviewer small mode; `GET /v1/serving`;
  the thin UI; the gate.

The interview is in the [owner decisions](../reference/phase-6-owner-decisions.md); the
[handoff](phase-6-agent-handoff.md) records card progress. Section 21 of the
[source of truth](../agents/scientific-research-platform-source-of-truth.md) records the phase.

## Goal

A reviewer can clone, run a small mode, inspect tests and results, and understand the production
design without private knowledge (section 21 gate). A recruiter watches a short video recorded on
the owner's laptop.

## Gate

Defined in ADR-0033 decision 8:

1. The `demo-smoke` workflow follows the README quickstart on a fresh GitHub runner and passes
   (P6-10, run in P6-17).
2. A cold-reviewer agent with only the public repository reports every point that needed private
   knowledge; each is fixed or recorded as a limitation (P6-17).
3. The owner accepts the recorded video (P6-18).

Answer quality is not part of this phase (owner decision Q1; backlog
[#115](https://github.com/avsngh-git/RAGpipeline/issues/115)); the failure analysis reports it.

## Design in one picture

```text
 laptop (owner, GPU)                          GitHub                         reviewer (CPU)
 ───────────────────                          ──────                         ──────────────
 research_phase1_review ──research-demo export──▶ Release demo-data-v2 ──▶ scripts/demo_load.sh
   + showcase runs (principal demo)               research-demo-v2.tar        │ research-migrate
 live runs for the video                                                      │ research-demo load
                                                                              │ research-demo fetch-models
 main ──CI──▶ ghcr.io/avsngh-git/ragpipeline:sha-… ──tag vX.Y.Z──▶ :vX.Y.Z, :latest ──▶ docker compose up
                                                                              ▼
                                                     http://127.0.0.1:8000/  (UI, /v1, /mcp)
```

## How the work is organized

- Map issue [#209](https://github.com/avsngh-git/RAGpipeline/issues/209) holds the card table,
  decisions and fog. Cards are its sub-issues, labelled `wayfinder:task`, with native blocked-by
  links. P6-01 to P6-19 are issues #210 to #228 in order.
- **Implementers:** `ready-for-agent` cards are written for Codex Luna agents working alone and in
  parallel, with exact files, names, steps, tests and a done list. `ready-for-human` cards need the
  Conda solve, the review database, the GPU, publishing a release or the owner.
- **Workflow:** one branch (`phase6/p6-NN-short-name`) and one pull request per card; the planning
  session reviews each pull request before merge.
- **Live data:** agent cards never touch `research_phase1_review`, live Qdrant collections or Ollama.

| Card | Type | Delivers | Blocked by |
| --- | --- | --- | --- |
| P6-01 | human | ADRs 0032–0033, plan, handoff, owner decisions, source of truth 1.43 | — |
| P6-02 | human | Serving lock with CPU PyTorch; image built from it and able to load the models | P6-01 |
| P6-03 | agent | GHCR push from `main`; `release.yml` retags and creates the release | P6-01 |
| P6-04 | agent | Migrations in the image; `research-migrate`; `RESEARCH_PLATFORM_MIGRATIONS_DIR` | P6-02 |
| P6-05 | agent | `GET /v1/serving` | P6-01 |
| P6-06 | agent | `research_platform.demo.database`: allowlist export and load of PostgreSQL rows | P6-04 |
| P6-07 | agent | Bundle: Qdrant snapshots, manifest, attribution, `research-demo` CLI, `fetch-models` | P6-06 |
| P6-08 | agent | Compose small mode and `scripts/demo_load.sh` | P6-02, P6-04, P6-07 |
| P6-09 | agent | Thin UI at `/` | P6-05 |
| P6-10 | agent | `scripts/demo_smoke.py` and `demo-smoke.yml` | P6-05, P6-08 |
| P6-11 | human | Display records, showcase runs, bundle export, release `demo-data-v1` | P6-07, P6-08 |
| P6-12 | agent | README rewrite and `docs/history.md` | P6-08, P6-09 |
| P6-13 | agent | `docs/architecture/overview.md` | P6-01 |
| P6-14 | agent | `docs/reference/benchmarks.md` and `docs/reference/failure-analysis.md` | P6-01 |
| P6-15 | agent | `docs/operations/deployment.md` | P6-03, P6-08 |
| P6-16 | agent | `docs/demo/video-script.md` | P6-09 |
| P6-17 | human | Gate items 1–2: release `v0.6.0`, `demo-smoke`, cold reviewer, fixes, gate report | P6-03, P6-10, P6-11, P6-12, P6-13, P6-14, P6-15 |
| P6-18 | human | Gate item 3: the owner records and accepts the video | P6-16, P6-17 |
| P6-19 | human | Closeout, `v1.0.0`, source of truth | all |

## Product UI (ADR-0034)

Added on 2026-10-23 after the owner's UI interview ([owner decisions](../reference/phase-6-owner-decisions.md),
entry 2). [ADR-0034](../adr/0034-phase6-product-ui.md) amends ADR-0033 decisions 4, 7 and 8: the
page at `/` becomes a usable research UI (search with filters, paper pages, run form, run history,
run page with the run record, model-call text and cancel), built from plain ES modules with no build
step, over five new owner-scoped routes. P6-18 waits for these cards. P6-21 to P6-32 are
issues #257 to #268 in order, sub-issues of map issue #209.

| Card | Type | Delivers | Blocked by |
| --- | --- | --- | --- |
| P6-21 | human | ADR-0034, this section, handoff, owner decisions entry 2, source of truth 1.44 | — |
| P6-22 | human | Throwaway UI prototype on fake payloads; the owner approves the layout | P6-21 |
| P6-23 | agent | `GET /v1/research` (list) and `GET /v1/me` | P6-21 |
| P6-24 | agent | `GET /v1/research/{run_id}/record` and `GET /v1/research/{run_id}/model-calls/{ordinal}` | P6-23 |
| P6-25 | agent | `POST /v1/research/{run_id}/cancel` and failure category `cancelled_by_principal` | P6-23 |
| P6-26 | agent | UI as ES modules with a hash router: search with filters, paper pages, layout | P6-22 |
| P6-27 | agent | UI run views: run form, history, run page, run record panels, model text, cancel | P6-23, P6-24, P6-25, P6-26 |
| P6-28 | human | `pytest-playwright` in the test lock; Chromium in CI | P6-21 |
| P6-29 | agent | Playwright journeys in PR CI on fakes | P6-27, P6-28 |
| P6-30 | human | Bundle `research-demo-v2` with showcase payloads, release `demo-data-v2`; `demo_load.sh` points at it | P6-24 |
| P6-31 | agent | `demo-smoke` checks for the new routes; README and UI docs; video script segments 4–5 | P6-27, P6-30 |
| P6-32 | human | Re-run gate items 1–2 on `v0.6.1` with bundle v2; update the gate report | P6-29, P6-31 |

P6-18 is then blocked by P6-32. The showcase payloads expire about mid-January 2027, so P6-30 should
run well before then.

## Risks and fallbacks

| Risk | Detection | Response |
| --- | --- | --- |
| conda-forge has no `pytorch-cpu` 2.14 build that solves with the lock | P6-02 | Take the nearest solving 2.x with the same transformers and sentence-transformers; record the difference |
| The bundle misses a table the runtime reads | P6-11 load and `demo-smoke` | Add the table to the allowlist in a fix card; re-export |
| A paper's terms page does not confirm CC BY | P6-11 | It blocks the export; the owner decides to drop it (a new snapshot) or keep text withheld |
| The GitHub runner runs out of disk with a 4 GB image and the bundle | P6-17 | Free runner space first (remove preinstalled toolchains) |
| CPU retrieval is too slow for the smoke checks | P6-17 | Raise the smoke timeouts; record the CPU latency in the README |
| Hugging Face revisions disappear | `fetch-models` | Pinned revisions fail loudly; the README says so |

## Not in Phase 6

- any hosted environment, OAuth or public demo key;
- a frontend framework or build step, streaming model output, a metrics dashboard in the UI, key
  management in the UI, or the new run routes over MCP (ADR-0034);
- answer-quality work, the planner, the `answered` definition and the rest of backlog #115;
- the worker image and Docling in the image;
- a per-paper public-display reader in the access policy.
