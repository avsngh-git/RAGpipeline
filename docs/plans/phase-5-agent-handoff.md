# Phase 5 — Agent handoff

Updated: 2026-10-12. **Status: planned; ADR-0030 and ADR-0031 accepted by the owner on 2026-10-12.**
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
| P5-03 (#172) | implementation complete | — | SDK lock and spike check updated; imports, mypy, locked-version mount, image build, pip audit and local Trivy scan pass. A combined build with P5-02's base refresh is clean without exceptions. Hosted CI pending PR publication. |

## Environment facts

- **Machine:** an 11 GiB WSL VM, 12 CPUs, an RTX 3050 Laptop GPU with 4 GiB. The retrieval
  models use about 1.9 GiB of the GPU beside the generator, which is why MCP runs inside the API
  process.
- **Conda environment:** the local `sci_research_agent` has FastAPI 0.138.0 and Starlette 1.3.1,
  behind the lock (0.141.1 and 1.6.0). CI uses the lock.
- **Node:** 22.23.2 locally; MCP Inspector 2.8.0 needs 22.19 or later.
- **Live services:** the host API serves on `127.0.0.1:8001`; research runs use the database
  `research_phase1_review`. Agent cards never touch them.
- **Integration tests:** new modules are named `test_phase5_*.py`; migration 028 is added to the
  expected list in `tests/integration/test_live_services.py`.
- **Private data:** Phase 5 private data goes under `local-reference/phase5/`. `/tmp` is not
  persistent; agents push their branch after the first commit.
