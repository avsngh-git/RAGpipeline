# Phase 3.5 — Qdrant search and online ingestion

Status: approved by the owner on 2026-10-04; implementation in progress. The answer-quality
work it waited for is merged (ADR-0025). The decisions are in three accepted ADRs:

- [ADR-0022](../adr/0022-phase35-qdrant-search-and-content.md): Qdrant search and content.
- [ADR-0023](../adr/0023-phase35-index-generations.md): index generations.
- [ADR-0024](../adr/0024-phase35-online-discovery-and-ingestion.md): online discovery and
  ingestion.

Section 21 of the [source of truth](../agents/scientific-research-platform-source-of-truth.md)
records Phase 3.5; the [handoff](phase-3.5-agent-handoff.md) records card progress.

## Goal

1. Qdrant executes dense and lexical search and serves evidence content.
2. The corpus grows through published generations.
3. A `deep_research` run can find papers online, ingest the permitted ones and answer
   from them.

## Steps and gates

Steps run in order. Each gate must pass before the next step starts.

| Step | Delivers | Gate |
| --- | --- | --- |
| A — Storage split | Qdrant upgrade, generation registry, content payloads, `papers` collection, run pinning | Served text matches PostgreSQL `text_sha256`; generation 1 rebuilds from PostgreSQL and artifacts; a generation with correct counts but wrong IDs or hashes is not published; v10 rankings unchanged with content served from Qdrant |
| B — Lexical engine | `scientific_bm25` sparse vectors, profile `v10-qdrant`, cutover | Parity rule (ADR-0022): lexical top-50 IDs and scores within float32 tolerance and identical end-to-end v10 rankings. Otherwise the full Phase 2 procedure (development comparison, then a fresh 30-family held-out set against the v14 gates). Fallback: in-process BM25S |
| C — Discovery | `discover_papers`, semantic `find_related_papers`, abstract evidence, `quick` reports known-not-ingested papers | Leave-out test on the development families: hide judged relevant papers and report how often discovery ranks them in its top 10. Reported, not gated |
| D — Online ingestion | Outbox, worker service, `request_ingestion`, run waiting, ingest API | Operational, ADR-0020 style (below) |

Gate D:
1. Scripted cases pass in CI:
   - permission refusals and budgets are enforced;
   - a worker crash resumes its job;
   - a pinned run's generation changes only at its recorded switch.
2. On the leave-out development tasks, at least 90% of ingestion-triggering
   `deep_research` runs finish within their wait cap.
3. Every failed run carries a failure category.

Answer quality is reported, not gated, as in Phase 3.

## Decisions

| Topic | Decision | Record |
| --- | --- | --- |
| Ownership | PostgreSQL holds the catalog, citations, permission evidence, evidence text, jobs and runs; Qdrant executes search and serves content | ADR-0022 |
| Lexical | `scientific-en-v1` tokens and BM25 weights computed in Python (`k1=1.5`, `b=0.75`, fixed average length), sparse vector with `idf` modifier, vocabulary table in PostgreSQL. Built-in `Qdrant/bm25` is a development comparison arm only | ADR-0022 |
| Fusion | Application RRF over one Qdrant batch query; component ranks kept | ADR-0022 |
| Profile | `v10-qdrant`; inherits Phase 2 acceptance only through the parity rule | ADR-0022 |
| Collections | One `passages` and one `papers` per index configuration; chunk-based point IDs; `papers` holds every known paper | ADR-0022 |
| Corpus versions | Generations are finalized snapshots; points tagged `added_generation` and `retired_generation`; retrieval and IDF corpus filters use the same condition; generation 1 is the accepted snapshot | ADR-0023 |
| Publication | Verify IDs and hashes against the manifest, then move the SQL pointer only if the predecessor matches; runs pin a generation | ADR-0023 |
| Qdrant | Latest stable release ≥ 1.19, pinned after P35-02; `httpx` adapter kept | ADR-0023 |
| Discovery scope | ML and IR broadly; English and 2020+ defaults unchanged | ADR-0024 |
| Membership | Agent proposes; code enforces permission evidence and budgets; automatic finalization after integrity checks; every decision recorded | ADR-0024 |
| Modes | Only `deep_research` discovers and ingests | ADR-0024 |
| Budgets | Per run: 10 OpenAlex searches, 5 downloads, 5 papers per wait, about 15 minutes of waiting outside the 300-second active budget. Daily OpenAlex spend cap below the free allowance | ADR-0024 |
| Worker | Separate `research-worker` process in the API's environment (host Conda today); outbox with `SKIP LOCKED`; PostgreSQL advisory lock for the GPU | ADR-0024 |
| API | `POST /v1/collections/{collection_id}/ingest` uses the same outbox | ADR-0024 |
| Delegation | As in Phase 2: implementation, calibration and source review delegated to the assistant; labels are assistant-reviewed; the owner approves ADRs and accepts the phase | interview |

## Assumptions to confirm

These are reversible details, recorded here instead of asked:

- **Average length.** The BM25 average length is fixed per index configuration from
  generation 1. A drift above 10% starts a new configuration.
- **Vocabulary.** The vocabulary is append-only. Query tokens missing from it are dropped.
- **Abstract evidence.** It comes from `discover_papers` observations, gets ordinary
  evidence handles and is stored in `research_run_evidence`. It is not added to
  `passages`.
- **Leave-out tasks.** These use a leave-out generation built as a variant of
  generation 1. Re-acquiring a hidden paper reuses its stored original rather than
  downloading it again.

The P35-02 spike must establish these facts before step A builds anything:

- Qdrant's sparse IDF formula, and whether exact BM25S parity is possible.
- The exact Qdrant version to pin.
- Whether the IDF corpus filter accepts the generation condition.
- Whether Docling currently uses the GPU.

## Module map

Each card is one GitHub issue under the map issue
[#44](https://github.com/avsngh-git/RAGpipeline/issues/44), sized for one session (about
300 to 600 changed lines). P35-01 to P35-30 are issues #45 to #74 in order. The issue
holds the interface, files, tests and done list.

| Card | Step | Module | Blocked by |
| --- | --- | --- | --- |
| P35-01 | — | Accept ADRs 0022–0024; source-of-truth and `CONTEXT.md` updates; handoff | owner approval |
| P35-02 | A | Qdrant compatibility spike and report | P35-01 |
| P35-03 | A | Upgrade Qdrant in Compose and CI; restore the Phase 2 serving index | P35-02 |
| P35-04 | A | Migration 018: generation registry, published pointer, run generation | P35-01 |
| P35-05 | A | Generation index configuration and Qdrant adapter | P35-02 |
| P35-06 | A | Build generation 1 passages with content payloads | P35-03, P35-04, P35-05 |
| P35-07 | A | `papers` collection for every known paper | P35-06 |
| P35-08 | A | Generation verification, publication and purge | P35-06 |
| P35-09 | A | Search content served from Qdrant | P35-07, P35-08 |
| P35-10 | A | Generation-aware profiles, run pinning and content parity; **Gate A** | P35-09 |
| P35-11 | B | Migration 019, vocabulary repository and scientific sparse encoder | P35-10 |
| P35-12 | B | Sparse configuration: copy dense vectors, write `scientific_bm25` vectors | P35-11 |
| P35-13 | B | Async lexical protocol and Qdrant lexical branches | P35-12 |
| P35-14 | B | Profile `v10-qdrant` and lexical-engine switch | P35-13 |
| P35-15 | B | Parity evaluation and built-in BM25 comparison report | P35-14 |
| P35-16 | B | Contingency only if parity fails: full re-evaluation | P35-15 |
| P35-17 | B | Cutover to `v10-qdrant`; **Gate B** | P35-15 (or P35-16) |
| P35-18 | C | Migration 020 and catalog upsert for single OpenAlex works | P35-17 |
| P35-19 | C | Online discovery service with budgets and daily cap | P35-18 |
| P35-20 | C | `discover_papers` tool and abstract evidence | P35-19 |
| P35-21 | C | Semantic related papers and the `quick` known-not-ingested note | P35-19 |
| P35-22 | C | Leave-out corpus and discovery report; **Gate C** | P35-20, P35-21 |
| P35-23 | D | Migration 021, ingestion outbox, GPU lock and `research-worker` | P35-22 |
| P35-24 | D | Online ingestion of one paper: acquire, extract, chunk | P35-23 |
| P35-25 | D | Child snapshot, automatic finalization and generation publication | P35-24 |
| P35-26 | D | `request_ingestion` tool and membership policy | P35-25 |
| P35-27 | D | Run waiting, wait cap and generation switch | P35-26 |
| P35-28 | D | `POST /v1/collections/{collection_id}/ingest` | P35-26 |
| P35-29 | D | Scripted CI cases and live leave-out evaluation; **Gate D** | P35-27, P35-28 |
| P35-30 | — | Phase 3.5 closeout | P35-29 |

Card rules follow [Phase 3 card rules](phase-3-agent-answers.md#card-rules), with branches
named `phase3.5/p35-NN-short-name`.

## Risks and fallbacks

| Risk | Detection | Response |
| --- | --- | --- |
| Qdrant IDF differs from Lucene, so parity is impossible | P35-02 | Treat `v10-qdrant` as a ranking change: P35-11b runs the full procedure, and BM25S serves lexical until it passes |
| IDF corpus filter cannot express the generation condition | P35-02 | Fall back to a physical collection per generation for the sparse branch; amend ADR-0023 |
| Concurrent writes affect serving | P35-07 tests | Generation filter and predecessor-checked pointer; unpublished points are never queried |
| Docling and the generator do not fit together on the GPU | P35-02, P35-16 | Advisory lock serializes them; Ollama unloads the model while extraction runs |
| Few discovered papers have permitted full text | P35-15 report | Abstract evidence keeps them useful; the report counts metadata-only outcomes |
| Ingestion waits exceed the cap | P35-20 | Answer from the published generation and list pending papers; tune the cap with evidence |
| OpenAlex costs | Daily cap counter | Refuse further downloads for the day with a recorded reason |

## Not in Phase 3.5

Langfuse, authentication, rate limits, MCP, a UI, answer-quality gates, and changes to
embedding or reranker models. Phase 4 follows.
