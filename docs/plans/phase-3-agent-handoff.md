# Phase 3 — Agent handoff

Updated: 2026-10-01. **Status: planned, not started.** The owner approved the
[Phase 3 plan](phase-3-agent-answers.md) and ADRs
[0018](../adr/0018-phase3-local-generator-and-serving.md),
[0019](../adr/0019-phase3-research-run-execution.md) and
[0020](../adr/0020-phase3-evaluation-gates.md) on 2026-10-01.

## How work is picked up

- Each module is a GitHub issue labelled `wayfinder:task` under the map issue
  [#2](https://github.com/avsngh-git/RAGpipeline/issues/2). Cards P3-01 to P3-17 are issues
  #3 to #18 in order, except P3-06, which is #19.
- Pick the first open card in map order whose "Blocked by" cards are closed. Cards
  labelled `ready-for-human` are written by the owner with a tutor (P3-03), or paired step
  by step with the planning agent (P3-12, P3-14).
- Follow the card and the plan's "Card rules"; the card holds everything else needed.
- The owner runs implementers in separate sessions and merges pull requests.

## Progress

| Card | State | Pull request | Notes |
| --- | --- | --- | --- |
| P3-01 (#3) | in review | phase3/p3-01-plan | plan, ADRs, source-of-truth 1.31 |

## Environment facts

- Phase 2 search is served by Uvicorn in the host Conda environment (CUDA and model
  caches); Compose provides PostgreSQL, Qdrant and, from P3-02, Ollama. The packaged API
  image has no PyTorch. See [Phase 2 search operations](../operations/phase-2-search.md).
- The accepted snapshot `4b11fab3-d4a5-4e7a-a58e-8654accf2c6c` lives in the database
  `research_phase1_review`; research runs use the same database.
- WSL memory is raised to 12 GB by the owner (`%UserProfile%\.wslconfig`).
- Private Phase 3 data goes under `local-reference/phase3-runs/`.
