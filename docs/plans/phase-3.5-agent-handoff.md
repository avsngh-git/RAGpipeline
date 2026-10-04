# Phase 3.5 — Agent handoff

Updated: 2026-10-04. **Status: approved by the owner; implementation in progress.** The owner
accepted ADRs [0022](../adr/0022-phase35-qdrant-search-and-content.md),
[0023](../adr/0023-phase35-index-generations.md) and
[0024](../adr/0024-phase35-online-discovery-and-ingestion.md) on 2026-10-04 and asked for the
cards to be implemented one at a time, with one commit per card.

## How work is picked up

- Each card is a GitHub issue labelled `wayfinder:task` under the map issue
  [#44](https://github.com/avsngh-git/RAGpipeline/issues/44). P35-01 to P35-30 are #45 to #74
  in order.
- Pick the first open card in map order whose "Blocked by" cards are closed. Follow the card
  and the [Phase 3 card rules](phase-3-agent-answers.md#card-rules), with branches named
  `phase3.5/p35-NN-short-name`.
- 2026-10-04: the owner asked the planning agent to implement the cards sequentially on the
  branch `phase3.5/implementation`, committing after each card. Pushing and pull requests
  happen only when the owner asks.
- P35-16 (#60) runs only if the P35-15 parity report fails and the owner approves it.

## Progress

| Card | State | Commit | Notes |
| --- | --- | --- | --- |
| P35-01 (#45) | done | daba634 | ADRs accepted; source of truth 1.35; glossary terms; plan and handoff |
| P35-02 (#46) | done | 256cd10 | Qdrant v1.19.1 pinned; parity possible (IDF corpus filter required); export/import upgrade; Docling not installed locally |
| P35-03 (#47) | done | 9d5f630 | Compose and CI on v1.19.1; four collections exported and imported to volume `qdrant_data_v1_19`, all checks passed; old volume kept; 43 integration tests passed |
| P35-04 (#48) | done | 55040fe | Migration renumbered to 018 (017 is ADR-0025's claim quotes); later card migrations shift to 019–021 |
| P35-05 (#49) | done | 5bfca4e | `generation_index.py`; retrieved dense vectors are in `GenerationMatch.dense` (not a payload key); every point needs a dense vector |
| P35-06 (#50) | done | b045d7e | Generation 1 of `research-corpus` built: 44,277 points, all vectors reused, 0 embedded, 80 s; state `building` until P35-08 |
| P35-07 (#51) | done | this change | `papers` collection synced: 157 papers, 100 indexed in generation 1; dense text is title plus decoded abstract |

## Environment facts

- Phase 2 search is served by Uvicorn in the host Conda environment `sci_research_agent`
  (CUDA and model caches); Compose provides PostgreSQL, Qdrant and Ollama. The packaged API
  image has no PyTorch, so `research-worker` also runs in the host environment. See
  [Phase 2 search operations](../operations/phase-2-search.md).
- The accepted snapshot `4b11fab3-d4a5-4e7a-a58e-8654accf2c6c` (generation 1) lives in the
  database `research_phase1_review`; research runs use the same database.
- The Phase 2 serving dense collection is `phase2-dev-gte-modernbert-base-v1` (44,277 points).
- Compose and CI pin Qdrant v1.19.1 (volume `qdrant_data_v1_19`); the v1.14.1 volume
  `ragpipeline_qdrant_data` is kept for rollback.
- Private Phase 3.5 data goes under `local-reference/phase35/`; `/tmp` is not persistent.
- ADR-0025 (answer quality) changed synthesis prompts, budgets and verification after Phase 3;
  agent-layer cards must read the current `main` versions of the agent modules.
- Integration test modules run in name order, and `test_live_services.py` needs the fresh
  schema left by `test_checkpointing.py`. New integration modules must sort after
  `test_live_services.py`: name them `test_phase35_*.py`. Add each new migration to that
  test's expected migration list.
- Generation collection `research-corpus` is `61cefddc-9fcb-4f75-8280-eae9bce3adf7`; the
  dense generation configuration (`configs/phase35-generation-index.example.json`) is
  `sha256:4cad3111d787948278dd448819a14ee7daa8ec4b7403bc0139cbdd60fd01a2b5`.
- `research-ingest` applies pending migrations to `RESEARCH_PLATFORM_DATABASE_URL`;
  `research_phase1_review` has migrations through 018.
- Phase 2 finding (P35-07): `IndexRepository.load_snapshot_lexical_inputs` reads
  `papers.metadata` without decoding the JSON text, so every BM25S paper index was built
  from titles only (0 of 100 abstracts; 10 accepted papers have OpenAlex abstracts).
  Accepted profile v10 therefore ranks paper metadata by title only. Lexical parity
  (P35-12/P35-15) must reproduce title-only paper text; using abstracts is a ranking
  change that needs evaluation.
