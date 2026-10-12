# Phase 5 — Agent handoff

Updated: 2026-10-12. **Status: in progress; ADR-0030 and ADR-0031 accepted by the owner on 2026-10-12.**
The [plan](phase-5-mcp.md) and map issue
[#169](https://github.com/avsngh-git/RAGpipeline/issues/169) define the cards; the
[owner decisions](../reference/phase-5-owner-decisions.md) record the interview; the
[SDK spike](../reference/phase-5-mcp-sdk-spike.md) records the verified SDK facts.

## How work is picked up

- Each card is a GitHub issue labelled `wayfinder:task`, plus `ready-for-agent` or
  `ready-for-human`, and is a sub-issue of map issue #169. P5-01 to P5-17 are #170 to #186 in
  order. Blockers are recorded as native GitHub dependencies and as a "Blocked by" line.
- Cards run in parallel. Pick any open, unassigned card whose blockers are closed, and claim it
  with `gh issue edit <n> --add-assignee @me`.
- Each card holds its own rules: the branch is `phase5/p5-NN-short-name`, with one pull request
  per card containing `Closes #<issue>`.
- Agent cards are implemented by Codex Luna agents working alone from the card text (owner
  instruction, 2026-10-06). The planning session reviews each pull request before merge.

## Order

1. P5-01 (planning documents) merges first. P5-02 can start at once.
2. Then in parallel: P5-03 (lock), P5-04, P5-05, P5-07, P5-08.
3. P5-06 after P5-04 and P5-05.
4. P5-09 after P5-03, P5-06, P5-07 and P5-08.
5. P5-10, P5-11 and P5-12 in parallel after P5-09.
6. P5-13, P5-14 and P5-15, then P5-16 (gate item 4) and P5-17 (closeout).

## Progress

| Card | State | Commit / PR | Notes |
| --- | --- | --- | --- |
| P5-01 (#170) | done | PR #187 | ADRs 0030–0031, plan, handoff, spike, owner decisions, source of truth 1.41 |
| P5-02 (#171) | done | PR #189 | Stale experiment failed with an interruption note; Ollama recreated. Patched Ubuntu OpenSSL and Miniforge/Conda layers, removed build-only pip from the runtime image, deleted all seven Trivy exceptions; local Trivy 0.70.0 scan with the P5-03 lock is clean without exceptions. OpenSSL upgrade unpinned (owner choice). |
| P5-03 (#172) | done | PR #188 | SDK lock and spike check updated; imports, mypy, locked-version mount, image build, pip audit and local Trivy scan pass. A combined build with P5-02's base refresh is clean without exceptions. |
| P5-04 (#173) | done | PR #191 | `ResearchCapabilities` for retrieval; `AppError` and the citation cursor moved to `services/`; routes are thin adapters. Agent work found committed but unpushed in its worktree; pushed and reviewed |
| P5-05 (#174) | done | PR #192 | Migration 028 `ingestion_permitted`; `ingest_scope_required` is the first refusal rule. Found unpushed; pushed and reviewed |
| P5-07 (#176) | done | PR #190 | `Settings.mcp_text_policy`, `external_text_allowed`, `redact_run_view` |
| P5-08 (#177) | done | PR #193 | `authenticate_authorization`, `require_principal_scope`, `enforce_rate_limit`; `McpAuthGate` reuses `handle_app_error`. Found unpushed, and an uncommitted copy sat in the main checkout on the P5-07 branch (identical; removed) |
| P5-06 (#175) | done | PR #194 | `serving`, `resolve_snapshot`, `start_run`, `get_run`; runs record `ingestion_permitted` from the `ingest` scope. Review: P5-13's import-boundary allowlist made name-limited so `RunNotFound` from `runs.repository` is allowed (card #182 edited) |
| P5-09 (#178) | done | PR #195 | `/mcp` mount, `run_call` runtime, metrics and spans, `mcp/testing.py`. Squash-merged before review; reviewed on `main` (`518cc9f`, CI green): matches the card. The branch `phase5/p5-09-mcp-server` holds an older, unmerged rebase and can be deleted |
| P5-12 (#181) | done | PR #198, fix #199 | Run tools and `research-run://`. Squash-merged before review with a guard that skipped registration when research services were absent at server creation; in the running API they are built later, so the run tools never appeared. #199 always registers them and replaces P5-09's obsolete "tool list is empty" test with a production-shaped one |
| P5-10 (#179) | done | PR #197 | `search_papers`, `search_evidence`; compact items, text withheld by default. Review: a test required its tools to be the only ones; changed to "included" |
| P5-11 (#180) | done | PR #200 | Paper, citation and related tools reusing the HTTP response models; `paper://`. Pushed without a PR; opened and merged |
| — | done | fix #201 | Import cycle: importing any MCP module before `create_app` failed through `research_platform/api/__init__`. `mount_mcp` now imports the gate and server when called; `tests/test_mcp_imports.py` imports each module in a fresh interpreter |
| P5-15 (#184) | done | PR #202 | `docs/operations/mcp.md`, `scripts/mcp_inspector_check.sh` (Inspector 2.8.0), README section. Merged before review; reviewed on `main` |
| P5-13 (#182) | done | PR #203 | **Gate items 1–2.** Parity with HTTP and `ResearchTools`; import boundary. Merged before review; mutation checks on `main`: a forbidden import and an MCP tool bypassing `ResearchCapabilities` both fail the gate tests |
| P5-14 (#183) | done | PR #204 | **Gate item 3.** MCP security suite. Merged before review; mutation checks: text policy leaking text, a skipped scope check and ingestion without `ingest` each fail the suite. `main` at `7c7193a`: 1407 passed, 114 skipped |
| P5-16 (#185) | owner review | gate report PR | Gate item 4 ran 2026-10-12: Inspector session on `main` `7c7193a`; run `0de45d17` started over MCP completed (`answered`) and matches HTTP except withheld quotes. Claude Code demo under owner decision 2; finding #205 (concurrent searches). See `docs/reference/phase-5-gate-report.md` |

## Environment facts

- **Machine:** an 11 GiB WSL VM, 12 CPUs, an RTX 3050 Laptop GPU with 4 GiB. The retrieval
  models use about 1.9 GiB of the GPU beside the generator, which is why MCP runs inside the API
  process.
- **Conda environment:** the local `sci_research_agent` has FastAPI 0.138.0 and Starlette 1.3.1,
  behind the lock (0.141.1 and 1.6.0). CI uses the lock. MCP cards need `mcp` 2.3.0 installed
  locally (`conda install -n sci_research_agent --freeze-installed -c conda-forge mcp=2.3.0`).
- **Agents and pushing:** three of the first four agent cards were committed but never pushed;
  remind each agent to push after its first commit.
- **Node:** 22.23.2 locally; MCP Inspector 2.8.0 needs 22.19 or later.
- **Live services:** the host API serves on `127.0.0.1:8001`; research runs use the database
  `research_phase1_review`. Agent cards never touch them.
- **Integration tests:** new modules are named `test_phase5_*.py`; migration 028 is added to the
  expected list in `tests/integration/test_live_services.py`.
- **Private data:** Phase 5 private data goes under `local-reference/phase5/`. `/tmp` is not
  persistent; agents push their branch after the first commit.
