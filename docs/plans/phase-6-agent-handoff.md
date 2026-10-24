# Phase 6 — Agent handoff

Updated: 2026-10-23. **Status: in progress.** ADR-0034 (product UI) accepted by the owner on
2026-10-23 adds cards P6-21 to P6-32 ahead of the video. ADR-0032 and ADR-0033 accepted by the owner on
2026-10-13. The [plan](phase-6-portfolio.md) and map issue
[#209](https://github.com/avsngh-git/RAGpipeline/issues/209) define the cards; the
[owner decisions](../reference/phase-6-owner-decisions.md) record the interview.

## How work is picked up

- Each card is a GitHub issue labelled `wayfinder:task`, plus `ready-for-agent` or
  `ready-for-human`, and is a sub-issue of map issue #209. P6-01 to P6-19 are #210 to #228 in
  order; P6-21 to P6-32 are #257 to #268 in order. Blockers are native GitHub dependencies
  and a "Blocked by" line.
- Cards run in parallel. Pick any open, unassigned card whose blockers are closed, and claim it
  with `gh issue edit <n> --add-assignee @me`.
- Branch `phase6/p6-NN-short-name`, one pull request per card containing `Closes #<issue>`.
- Agent cards are implemented by Codex Luna agents working alone from the card text (owner
  instruction, 2026-10-06). The planning session reviews each pull request before merge.

## Order

1. P6-01 (planning documents) merges first.
2. In parallel: P6-02 (serving lock, human), P6-03, P6-05, P6-13, P6-14.
3. P6-04 after P6-02; P6-09 after P6-05.
4. P6-06 after P6-04; then P6-07.
5. P6-08 after P6-02, P6-04 and P6-07; P6-16 after P6-09.
6. P6-10, P6-11, P6-12 and P6-15 when their blockers close.
7. P6-17 (gate items 1–2).
8. Product UI ([ADR-0034](../adr/0034-phase6-product-ui.md), added 2026-10-23): P6-21, then P6-22
   (prototype, owner approval), P6-23 and P6-28 in parallel; P6-24 and P6-25 after P6-23 (they
   reuse its `owned_run`); P6-26 after P6-22;
   P6-27 after P6-23 to P6-26; P6-29 after P6-27 and P6-28; P6-30 after P6-24; P6-31 after P6-27
   and P6-30; P6-32 (gate items 1–2 again, `v0.6.1`) after P6-29 and P6-31.
9. P6-18 (video) after P6-32, then P6-19 (closeout).

## Progress

| Card | State | Commit / PR | Notes |
| --- | --- | --- | --- |
| P6-01 (#210) | merged | c472286 / [PR #229](https://github.com/avsngh-git/RAGpipeline/pull/229) | Hosted CI run [#38407311684](https://github.com/avsngh-git/RAGpipeline/actions/runs/38407311684) passed |
| P6-02 (#211) | merged | PR #230 | Serving lock (CPU PyTorch); image 4.22 GB loads both pinned models on CPU. Hub 1.33.0 pinned by hash in `requirements-serving.txt` (its Conda build conflicts with `mcp=2.3.0`). CPU reranks in fp32; the guard that refused fp16 on CPU was removed, resolved by P6-20, which records the actual device and precision per run |
| P6-03 (#212) | merged | PR #233 | Merged before review; reviewed on `main`: matches the card. Main CI pushed `sha-6d1d9847734d` |
| P6-04 (#213) | merged | PR #234 | Merged before review; reviewed on `main`: matches the card |
| P6-05 (#214) | merged | PR #235 | Merged before review; reviewed on `main`: matches the card |
| P6-13 (#222) | merged | PR #232 | Links resolve; no private data |
| P6-14 (#223) | merged | PR #231 | Links resolve; spot-checked numbers match the v14 report; caveats stated beside passes |
| P6-06 (#215) | merged | PR #239 | Merged before review; reviewed on `main`: the 35 allowlisted queries and 22 exclusions match the card. Load also disables the two snapshot immutability triggers inside its transaction (needed to load items of a finalized snapshot) |
| P6-09 (#218) | merged | PR #238 | Merged before review; reviewed on `main`: DOM built with `textContent` only, CSP as specified, assets shipped as package data |
| P6-07 (#216) | merged | PR #241 | Merged before review; reviewed on `main`: matches the card; also rejects manifest paths outside the bundle and checks Qdrant collections before any database write. A failed Qdrant restore after the PostgreSQL load needs `demo_load.sh --reset` |
| P6-08 (#217) | merged | PR #243, fix #244 | Merged before review. Review: the key-creation `docker compose run` lacked `-T`, so in an interactive terminal stderr merged into the captured JSON; fixed in #244 |
| P6-16 (#225) | merged | PR #240 | 4:30 over seven segments; two `TODO(owner)` items for after P6-17 |
| P6-20 (#237) | merged | PR #242 | Added in review of PR #230. Runs record `reranker_runtime`; older payloads keep their hashes; `reproduce` reads it back |
| P6-12 (#221) | merged | `1e2579c` / [PR #245](https://github.com/avsngh-git/RAGpipeline/pull/245) | Exact-head CI [#38561647884](https://github.com/avsngh-git/RAGpipeline/actions/runs/38561647884) passed; issue #221 closed |
| P6-10 (#219) | merged | PR #246 | Reviewed on `main`: stdlib-only smoke script and workflow match the card; first real run in P6-17 |
| P6-15 (#224) | merged | PR #247 | Reviewed on `main`: ten sections, links resolve, no private data |
| P6-11 (#220) | done | fixes #248, #249 | 100 display decisions (all CC BY; 11 via Crossref); 8 showcase runs by principal `demo` (2 answered, 5 partially supported, 1 insufficient evidence); bundle 35 tables, 288,407 rows, 354 MB, privacy-scanned clean; fresh-clone load 634 s and 6/6 smoke checks; release `demo-data-v1` |
| P6-17 (#226) | done | #250, #251, #252 | `v0.6.0` released (`977e7aa`); demo-smoke run 38576130251 passed 6/6 on a fresh runner; cold review passed, findings fixed or filed (#253, #254). See `docs/reference/phase-6-gate-report.md` |
| P6-21 (#257) | merged | `782a590` / PR #269 | ADR-0034, plan section, owner decisions entry 2, source of truth 1.44 |
| P6-25 (#261) | merged | PR #274, merge commit `78a7c418b80457177fcf1fc3f226836764b63cb2` | Exact-head CI [#39998594754](https://github.com/avsngh-git/RAGpipeline/actions/runs/39998594754) passed (1,628 tests), including PostgreSQL cancellation and migration checks; issue closed |
| P6-23 (#259) | merged | PR #272 | Merged before review; reviewed on `main`: matches the card (owner-scoped keyset list, `/v1/me` states, cached Ollama probe, Langfuse traces URL) |
| P6-24 (#260) | merged | PR #273 | Merged before review; reviewed on `main`: matches the card; withheld model text never loads payloads; `recorded_at` excluded from equality |
| P6-26 (#262) | merged | PR #271 | Merged before review; reviewed on `main` in headless Chromium on fakes: search, paper pages, phone width, no console errors. Three search-page defects (duplicate status pill, raw status value, evidence kinds shown for paper search) moved into P6-27 step 7 |
| P6-27 (#263) | merged | PR #276, merge commit `ef89099c1487d6fe7b3a27be1b4c3df6e5d852a5` | Exact-head CI [#40005630677](https://github.com/avsngh-git/RAGpipeline/actions/runs/40005630677) passed. Focused local UI/cancel tests passed (21); local full pytest was incomplete; CI installed and launched Chromium |
| P6-28 (#264) | merged | PR #270, `01bd124` | `pytest-playwright` 0.9.0; Chromium launched in CI; security bumps (brotli, certifi, OpenTelemetry 1.45.1; Pillow 13.0.0 in the serving lock) with every other locked package unchanged |
| P6-25 review | — | — | Reviewed on `main`: executor cancellation and shutdown behave as the card says; cancelled runs record `plan_rounds=0`, fixed in P6-27 step 7 |
| P6-22 (#258) | done | branch `prototype/p6-22-ui` (`9047560`, not for `main`) | Owner chose layout B, Report (owner decisions entry 3); P6-26 and P6-27 written against it |
| P6-28 (#264) | in review | branch `phase6/p6-28-playwright-lock` | `pytest-playwright` 0.9.0 in the test lock; OpenTelemetry 1.45.1, brotli 1.2.1 and certifi 2026.10.19 in both locks (pip-audit advisories of 2026-10-23); every other package unchanged; Chromium installed and launched in CI |

## Environment facts

- **Machine:** an 11 GiB WSL VM, 12 CPUs, an RTX 3050 Laptop GPU with 4 GiB.
- **Two environments:** CI tests use `environment-linux-64.lock` (no PyTorch). The image is
  built from `environment-serving-linux-64.lock` after P6-02. The host `sci_research_agent`
  environment has torch 2.14.0 (CUDA 13.0), transformers 5.17.0, sentence-transformers 6.1.0,
  huggingface-hub 1.33.0 and docling 2.130.0 outside the lock.
- **Served corpus:** snapshot `4b11fab3-d4a5-4e7a-a58e-8654accf2c6c` (100 papers, 44,277 chunks),
  collection `research-corpus` (`61cefddc-9fcb-4f75-8280-eae9bce3adf7`) generation 1, Qdrant
  collections `research-passages-gte-bm25-v1` and `research-papers-gte-bm25-v1`, profile
  `frozen-profile-v10-qdrant.toml`.
- **Agents and pushing:** remind each agent to push after its first commit.
- **Live services:** the host API serves on `127.0.0.1:8001`; research runs use the database
  `research_phase1_review`. Agent cards never touch them.
- **Integration tests:** new modules are named `test_phase6_*.py`.
- **Private data:** Phase 6 private data goes under `local-reference/phase6/`.
- **Browser tests locally:** Chromium needs system libraries that WSL lacks (`libnspr4`, `libnss3` and others). Install them once with `sudo "$(conda run -n sci_research_agent which python)" -m playwright install-deps chromium`, then `python -m playwright install chromium`.
