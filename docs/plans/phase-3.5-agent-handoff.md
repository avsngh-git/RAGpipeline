# Phase 3.5 — Agent handoff

Updated: 2026-10-05. **Status: approved by the owner; implementation in progress.** The owner
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
| P35-07 (#51) | done | 8b002b6 | `papers` collection synced: 157 papers, 100 indexed in generation 1; dense text is title plus decoded abstract |
| P35-08 (#52) | done | e3c7b93 | Generation 1 verified (44,277 of 44,277; 0 missing, unexpected, hash or field failures; probes passed) and published; purge dry run 0 |
| P35-09 (#53) | done | 8bc79e0 | `RESEARCH_PLATFORM_CONTENT_SOURCE=qdrant` serves all four modes from generation content; generation dense search is exact (see findings) |
| P35-10 (#54) | done | 7da9f27 | **Gate A passed** (see below); runs pin the published generation; `generations rebuild` added |
| P35-11 (#55) | done | b9666f9 | Migration 019 vocabulary; sparse weights reproduce BM25S Lucene scores on a scientific corpus (oracle test) |
| P35-12 (#56) | done | e8a7b33 | Lexical configuration `sha256:3130e408…` (`configs/phase35-generation-index-lexical.example.json`): generation 1 built with copied dense vectors and `scientific_bm25` vectors, verified and published; evidence average 43.297 tokens over 44,277 chunks, paper average 11.69 over 100 titles |
| P35-13 (#57) | done | 8cf7da5 | `lexical_branches.py`: async protocol, BM25S adapters (`asyncio.to_thread`) and Qdrant evidence/paper branches; serving still uses BM25S. Live test is `test_phase35_qdrant_lexical_live.py` (naming rule below): top-20 IDs and scores equal BM25S, with generation-2 points and a metadata-only paper outside the IDF corpus |
| P35-14 (#58) | done | a8a6909 | `frozen-profile-v10-qdrant.toml` (profile `sha256:d4d26d26…`; inactive, pointer stays on v10). `RESEARCH_PLATFORM_LEXICAL_ENGINE=qdrant` needs `RESEARCH_PLATFORM_CONTENT_SOURCE=qdrant` and `RESEARCH_PLATFORM_GENERATION_CONFIGURATION=configs/phase35-generation-index-lexical.example.json`; other published generations serve all modes. Live: all four modes served; 48 synthetic requests (4 modes, evidence and paper, 3 queries, with and without a year filter) gave hit lists identical to BM25S v10. This is not the parity decision (P35-15) |
| P35-15 (#59) | done | a6d4316 | **Parity: pass** under ADR-0022 item 7 as amended by the owner on 2026-10-05 (tie-aware, 1e-6 relative); strict reading fails on 37 of 200 sampled queries through float32 tie order only. Development: 84/84 lexical, 336/336 end to end. See the [parity report](../reference/phase-3.5-lexical-parity-report.md) |
| P35-16 (#60) | not needed | — | Parity passed |
| P35-17 (#61) | done | this change | **Gate B passed.** Active pointer is `frozen-profile-v10-qdrant.toml`; defaults are Qdrant content and lexical engine with the lexical generation configuration. Deleted `phase2-dev-gte-modernbert-base-v1`, `research-passages-gte-v1` and `research-papers-gte-v1` after checking no run was queued or running (registry rows kept). Host API restarted on the defaults: 3 development queries × 4 modes × evidence and paper, 24/24 returned 200 with results and no fallback |
| P35-18 (#62) | done | 5049e84 | Migration 020 adds catalog metadata revisions, discovery spend, and checked abstract evidence. OpenAlex upserts resolve identity and persist authors without creating documents or snapshot membership |
| P35-19 (#63) | done | abac8f4 | Budgeted OpenAlex discovery, catalog and paper-vector upserts, dense question ranking; 26 focused tests pass. Live check: 25 works fetched, 5 ranked candidates, one `search_request` spend row at $0.001; snapshot membership and generation pointers unchanged. Private record: `local-reference/phase35/p35-19-live-check.json` |

| P35-20 (#64) | done | 5a7c70a | Deep discovery action, mode and tool-budget guards, labelled abstract evidence, and dense plus frozen sparse runtime wiring. Focused tests, deep graph and scripted regression: 127 passed; Ruff and mypy pass. Owner approved the evidence header and deep-graph test edits omitted from the card file list |

| P35-21 (#65) | done | this change | Semantic related-paper basis uses Qdrant recommend with pinned generation and source exclusion. Quick runs store up to five metadata-only candidates after evidence collection; threshold 0.5 is uncalibrated and recorded in provenance. Failures are logged without query/title text and do not fail the run. 141 focused and scripted regression tests passed; Ruff, format and mypy passed. Disposable PostgreSQL check confirmed storage and resume/completion retention; private record `local-reference/phase35/p35-21-persistence-check.json`. Owner approved adjacent runtime/store files |

## Environment facts

- Phase 2 search is served by Uvicorn in the host Conda environment `sci_research_agent`
  (CUDA and model caches); Compose provides PostgreSQL, Qdrant and Ollama. The packaged API
  image has no PyTorch, so `research-worker` also runs in the host environment. See
  [Phase 2 search operations](../operations/phase-2-search.md).
- The accepted snapshot `4b11fab3-d4a5-4e7a-a58e-8654accf2c6c` (generation 1) lives in the
  database `research_phase1_review`; research runs use the same database.
- The Phase 2 dense collection `phase2-dev-gte-modernbert-base-v1` (44,277 points) was deleted at
  the P35-17 cutover; serving reads `research-passages-gte-bm25-v1`.
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
  `research_phase1_review` has migrations through 020 (applied for the P35-19 live check).
- Phase 2 finding (P35-07): `IndexRepository.load_snapshot_lexical_inputs` reads
  `papers.metadata` without decoding the JSON text, so every BM25S paper index was built
  from titles only (0 of 100 abstracts; 10 accepted papers have OpenAlex abstracts).
  Accepted profile v10 therefore ranks paper metadata by title only. Lexical parity
  (P35-12/P35-15) must reproduce title-only paper text; using abstracts is a ranking
  change that needs evaluation.
- P35-09 findings for the Gate A parity check (P35-10):
  - Qdrant's JSON parsing can change the last bit of stored floats (bounding boxes
    differ by one ulp). Text and hashes are exact; compare coordinates with a relative
    tolerance of 1e-12.
  - The Phase 2 dense branch used approximate HNSW search, and HNSW graphs differ between
    collections even for identical vectors. On 24 test requests (dense, hybrid,
    reranked; 3 queries, with and without a year filter) 6 top-10 lists differed in one or
    two items. Generation dense search now uses exact search, so parity is checked as
    exact search over the old collection against exact search over the generation, and
    the report records how far v10's approximate results were from exact.

- **Gate B (2026-10-05), P35-15 and P35-17:** lexical parity passed under the tie-aware
  rule (ADR-0022 item 7, amended by the owner); see the
  [parity report](../reference/phase-3.5-lexical-parity-report.md). `v10-qdrant` serves by
  default and inherits the Phase 2 acceptance. BM25S remains the fallback
  (`RESEARCH_PLATFORM_LEXICAL_ENGINE=bm25s` with the v10 manifest) and the parity oracle.
- Serving collections are now `research-passages-gte-bm25-v1` and
  `research-papers-gte-bm25-v1` (configuration `sha256:3130e408…`). The deleted Phase 2
  collection's vectors remain in `local-reference/phase35/qdrant-export/`.
- **Gate A (2026-10-04), P35-10:**
  - Content parity (`scripts/phase35_content_parity.py`): 44,277 of 44,277 evidence units
    give identical search hits from PostgreSQL hydration and from Qdrant payloads.
  - Dense ranking: exact search over the Phase 2 collection equals exact search over the
    generation for 20 of 20 development queries. Phase 2's approximate search matched
    exact search in the top 10 for all 20 (mean overlap at 50: 49.9 of 50).
  - Rebuild from PostgreSQL alone (`generations rebuild`, no vector reuse): 44,277
    passages re-embedded in 15 min 25 s; inspection found no differences.
  - Correct counts with wrong IDs fail verification (unit test).
- P35-15 findings for the cutover (P35-17):
  - The dense branch has no evidence-ID tie-breaker. Duplicate chunks with identical
    embeddings come back from Qdrant's exact search in a collection-dependent order:
    v10 served from `research-corpus` and from `research-passages-gte-bm25-v1` differs in
    18 of 336 development responses. Cutting over changes some rankings among duplicates.
  - The comparison collection `research-passages-qdrant-bm25-v1` (built-in `Qdrant/bm25`,
    `avg_len` 31.10) is disposable; it is not part of any profile.
  - The reviewed labels for q11–q19 are lost; only 12 development families have judgments.
- Re-embedding is not bit-identical to the stored Phase 2 vectors: scores differ by up to
  5.6e-4 and the top-10 order changed for 3 of 20 development queries. The served
  generation therefore keeps the original vectors (rebuilt with
  `--reuse-dense-configuration`; parity 20 of 20 again). Keep the vector export
  (`local-reference/phase35/qdrant-export/`) as the recovery source for exact vectors.
