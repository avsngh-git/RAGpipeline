# Phase 3 — Agent handoff

Updated: 2026-10-03. **Status: all implementation and evaluation cards are complete;
Phase 3 owner acceptance is pending.** The owner approved the
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
- For the remaining Phase 3 work, the owner delegated to Luna high workers, one issue per
  worker with at most three concurrent; the parent/root reviews and merges. That explicit
  delegation overrides the historical `ready-for-human` labels on completed cards.

## Progress

| Card | State | Pull request | Notes |
| --- | --- | --- | --- |
| P3-01 (#3) | done | #20 | plan and ADRs |
| P3-02 (#4) | done | #22 | Ollama 0.35.0; text-only GGUF loads with thinking, no vision; 2,251 MiB loaded |
| P3-03 (#5) | done | #26 | adapter passed a live Ollama probe |
| P3-04 (#6) | done | #29 | generator fitness check and ADR-0018 results |
| P3-05 (#7) | done | #23 | shared contracts |
| P3-06 (#19) | done | none (377604b on main) | pushed without a PR; its missing migration-list update was fixed in #27 |
| P3-07 (#8) | done | #21 | LangGraph 1.2.9 and checkpointer 3.1.2 installed in the host `sci_research_agent` env |
| P3-08 (#9) | done | #24 | related papers |
| P3-09 (#10) | done | #25 | typed tools and fakes |
| P3-10 (#11) | done | #34 | evidence registry, packing and versioned prompts |
| P3-11 (#12) | done | #35 | answer synthesis and citation verification |
| P3-12 (#13) | done | #36 | quick graph and run lifecycle |
| P3-13 (#14) | done | #37 | research API, executor and startup resume |
| P3-14 (#15) | done | #38 | deep research graph |
| P3-15 (#16) | done | #39 | scripted regression CI; exact-head run 37139685657 passed |
| P3-16 (#17) | done | #40 | live development report; both sweeps passed operational gates |
| P3-17 (#18) | documentation ready | — | owner acceptance pending |
| P3-18 (#30) | done | #32 | dense index copy into the main serving stack |
| P3-19 (#31) | done | #33 | native tool-call planning |

The two supplemental issues (#30 and #31) are closed. P3-16 exact-head CI 37143367662 passed on revision
`e6dc3dcd2ae1417ba524be0316060810b17d19c5`; main CI 37143652344 passed on merged main
revision `fd16a97d21aec4dfb974bbc9ad437c86947af788`. Issue #18 records the P3-17 docs-only
CI evidence and the owner's acceptance decision. The [evaluation report](../reference/phase-3-evaluation-report.md)
contains aggregate gate results and limitations. Phase 3 acceptance remains pending the
owner's decision on issue #18.

## Environment facts

- Phase 2 search is served by Uvicorn in the host Conda environment (CUDA and model
  caches); Compose provides PostgreSQL, Qdrant and, from P3-02, Ollama. The packaged API
  image has no PyTorch. See [Phase 2 search operations](../operations/phase-2-search.md).
- The accepted snapshot `4b11fab3-d4a5-4e7a-a58e-8654accf2c6c` lives in the database
  `research_phase1_review`; research runs use the same database.
- WSL memory is raised to 12 GB by the owner (`%UserProfile%\.wslconfig`).
- Private Phase 3 data goes under `local-reference/phase3-runs/`.
