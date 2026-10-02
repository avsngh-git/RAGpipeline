# Phase 3 — Agent handoff

Updated: 2026-10-02. **Status: in progress (8 of 17 cards done).** The owner approved the
[Phase 3 plan](phase-3-agent-answers.md) and ADRs
[0018](../adr/0018-phase3-local-generator-and-serving.md),
[0019](../adr/0019-phase3-research-run-execution.md) and
[0020](../adr/0020-phase3-evaluation-gates.md) on 2026-10-01.

## How work is picked up

- Each module is a GitHub issue labelled `wayfinder:task` under the map issue
  [#2](https://github.com/avsngh-git/RAGpipeline/issues/2). P3-01 to P3-05 are #3 to #7,
  P3-06 is #19, and P3-07 to P3-17 are #8 to #18.
- Pick the first open card in map order whose "Blocked by" cards are closed. Cards
  labelled `ready-for-human` are written by the owner with a tutor (P3-03), or paired step
  by step with the planning agent (P3-12, P3-14).
- Follow the card and the plan's "Card rules"; the card holds everything else needed.
- The owner runs implementers in separate sessions and merges pull requests.

## Progress

| Card | State | Pull request | Notes |
| --- | --- | --- | --- |
| P3-01 (#3) | done | #20 | plan, ADRs, source-of-truth 1.31 |
| P3-02 (#4) | done | #22 | Ollama 0.35.0; text-only GGUF loads with thinking, no vision; 2,251 MiB loaded |
| P3-03 (#5) | done | #26 | adapter passed a live Ollama probe |
| P3-05 (#7) | done | #23 | shared contracts |
| P3-06 (#19) | done | none (377604b on main) | pushed without a PR; its missing migration-list update was fixed in #27 |
| P3-07 (#8) | done | #21 | LangGraph 1.2.9, checkpointer 3.1.2; host env still needs the packages (`p3-lock` has them) |
| P3-08 (#9) | done | #24 | related papers |
| P3-09 (#10) | done | #25 | typed tools and fakes |

Next unblocked: P3-04 (#6) fitness check and P3-10 (#11) prompts. P3-11 (#12) follows P3-10.

## Environment facts

- Phase 2 search is served by Uvicorn in the host Conda environment (CUDA and model
  caches); Compose provides PostgreSQL, Qdrant and, from P3-02, Ollama. The packaged API
  image has no PyTorch. See [Phase 2 search operations](../operations/phase-2-search.md).
- The accepted snapshot `4b11fab3-d4a5-4e7a-a58e-8654accf2c6c` lives in the database
  `research_phase1_review`; research runs use the same database.
- WSL memory is raised to 12 GB by the owner (`%UserProfile%\.wslconfig`).
- Private Phase 3 data goes under `local-reference/phase3-runs/`.
