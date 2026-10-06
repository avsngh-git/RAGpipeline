# Qdrant and PostgreSQL — Tailored Design

**Date:** 4 October 2026
**Status:** Superseded on 2026-10-04 by the [Phase 3.5 plan](../plans/phase-3.5-qdrant-search.md)
and ADRs 0022–0024. Kept for history: those replace this note's per-release collections
and in-process BM25S weights with generations and Qdrant-executed scientific BM25.
**Adapts:** [qdrant-postgres-design-changes.md](qdrant-postgres-design-changes.md) to this
repository's existing schema, frozen retrieval profile v10 and Phase 3 agent.

The original note's split is kept: **Qdrant executes search and serves evidence content;
PostgreSQL owns the catalog, citation graph, permissions, jobs, publication state and research
runs.** This version changes three things:

1. **BM25S stays the lexical scorer.** Qdrant stores BM25S's precomputed term weights as a
   sparse vector and executes the lexical query. Qdrant's native BM25 encoder and IDF modifier
   are not used.
2. **Fusion stays in the application**, because search hits must keep component ranks and
   scores (spec §9.2).
3. **The corpus grows online.** Papers found through OpenAlex are ingested in batches and
   published as new releases (section 9).

## 1. Responsibilities

| Responsibility | Owner | Notes |
| --- | --- | --- |
| Paper identity, identifiers, metadata, authors | PostgreSQL | Existing `papers`, `paper_identifiers`, `authors`, `paper_authors` |
| Citation edges, unresolved references, coverage | PostgreSQL | Existing `citations`, `unresolved_citations` |
| Collections, snapshot membership | PostgreSQL | Existing `collections`, `snapshots`, `snapshot_items`, `snapshot_item_chunks` |
| Permission evidence and display restrictions | PostgreSQL | Existing `document_permission_evidence` |
| Authoritative evidence text and offsets | PostgreSQL | Existing `evidence_units`; spec §8.3 unchanged |
| Original PDFs, extraction outputs | Artifact storage | Existing `artifacts`, `document_artifacts` |
| Jobs, outbox, release registry, published pointer | PostgreSQL | Partly new (section 7) |
| Research runs, tool events, used evidence | PostgreSQL | Existing migration 016 tables |
| Dense and lexical **search execution** | **Qdrant** | Passage and paper collections, per release |
| Evidence **content serving** (text, section, location, table context) | **Qdrant** | Payload copy of `evidence_units`; no SQL text fetch on the search path |
| Known-paper discovery and semantic related papers | **Qdrant** | `catalog_papers` collection (section 9) |
| Fusion, reranking, deduplication, evidence selection | Application | Unchanged profile v10 code |

PostgreSQL remains authoritative and every Qdrant collection remains rebuildable (spec §8.3,
§22). Payload copies are display and filter snapshots, never edited in Qdrant.

## 2. What already exists

Most of the original note's table groups are already in the schema. The new work is smaller
than the original implies.

| Original table group | Existing equivalent | Gap |
| --- | --- | --- |
| `papers`, `paper_identifiers` | Same names | None |
| `paper_revisions` | None | Add when online discovery can refresh metadata for a known paper |
| `authors`, `authorships` | `authors`, `paper_authors` | None |
| `citation_edges`, `unresolved_references` | `citations`, `unresolved_citations`, `unresolved_citation_metadata` | Add observation time to edges |
| `corpora`, `corpus_memberships` | `collections`, `snapshots`, `snapshot_items` | None |
| `documents`, `document_versions`, `artifacts` | `documents`, `extractions`, `artifacts` | None |
| `chunk_manifests` | `snapshot_item_chunks` | None |
| `index_releases` | `index_configurations`, `snapshot_index_states` | Physical collection names, build state, published pointer |
| `outbox_events`, `index_jobs` | `ingestion_jobs`, job leases (migration 010) | Outbox table |
| `research_runs`, `tool_events`, `run_evidence` | Migration 016 tables | Pinned release column |

## 3. Qdrant collections

Each **release** is an immutable pair of physical collections built from one finalized
snapshot: `passages_rNNN` and `papers_rNNN`. One additional mutable collection,
`catalog_papers`, holds every known paper (section 9).

| Collection | Point | Vectors | Purpose |
| --- | --- | --- | --- |
| `passages_rNNN` | One evidence unit in the release's snapshot | `dense` (profile v10 embedding), `bm25s` (sparse) | Evidence search and content serving |
| `papers_rNNN` | One ingested paper in the snapshot | `dense`, `bm25s` over title/abstract | Paper search; mirrors the existing paper-role BM25S index |
| `catalog_papers` | Any known paper, including metadata-only records | `dense` over title/abstract | Discovery, ingestion selection, semantic related papers |

### Passage payload

`evidence_id`, `paper_id`, `document_version`, `snapshot_id`, `release_id`, `evidence_kind`,
`text`, `section_title`, `start_offset`, `end_offset`, `source_location`, table context
(headers, units, footnotes), `title`, `publication_year`, `version_kind`, `display_permitted`,
`text_sha256`, `index_configuration_id`.

### Point IDs

`uuid5(evidence_id, index_configuration_id)`. This replaces the current
`uuid5(snapshot_id:evidence_id)` ([indexing.py](../../src/research_platform/ingestion/indexing.py)),
so a chunk keeps one identity across releases and dense vectors can be reused from cache.

### Payload indexes

Create these before bulk upsert: `paper_id`, `publication_year`, `evidence_kind`,
`version_kind`, `display_permitted`. Do not index text fields.

## 4. Lexical search: BM25S weights, served by Qdrant

BM25S with the `lucene` method precomputes a document-by-term score matrix at index time.
Today the query sums the matrix columns for the query tokens (`engine.get_scores`), which is
a dot product. Qdrant sparse search computes the same dot product exactly.

- **Build.** Index the release's evidence units with BM25S 0.3.11, the `scientific-en-v1`
  analyzer and the frozen scoring settings. Export each document row as a sparse vector:
  indices are vocabulary IDs, values are the precomputed weights. Store the vocabulary as a
  checksummed release artifact.
- **Query.** Tokenize with the same analyzer, map tokens to vocabulary IDs, and send each
  ID with weight equal to its count in the token list passed to `get_scores` today. Drop
  out-of-vocabulary tokens, as BM25S does.
- **Consequence.** IDF is baked into the stored weights, so the weights change whenever the
  corpus changes. This is why releases are separate physical collections (section 7).
- **Parity gate.** Before Qdrant serves lexical search, compare it with in-process BM25S on
  the development families plus sampled queries: identical top-50 IDs and scores within
  float32 tolerance, then identical profile v10 end-to-end rankings. Do not use spent
  held-out sets. If parity holds, this is an implementation change, not a ranking change,
  and needs no new held-out evaluation. If it does not hold, stop: it would be an
  unapproved ranking change.
- **Retained.** The BM25S index stays as the build step and the parity oracle in tests. It
  stops serving production queries.

The query-weight rule assumes the current call passes duplicate tokens unchanged; the parity
test confirms it.

## 5. Fusion and reranking stay in the application

Qdrant's fused prefetch result does not return per-branch ranks, which spec §9.2 requires.
Use one Qdrant batch query to run the dense and `bm25s` branches with the same eligibility
filter, then fuse with the existing RRF code (`rank_constant` 60, top-k 50/50/50). Use a
Qdrant count with the same filter for the eligible-record count. The reranker, deduplication
and evidence selection are unchanged.

## 6. Reads

**Evidence search.**

1. Resolve the run's pinned release and validate filters.
2. Encode the query (dense and BM25S tokens).
3. Run one batch query against `passages_rNNN` with eligibility filters applied to both
   branches.
4. Fuse in the application.
5. Check candidates against permission evidence and snapshot membership in PostgreSQL. Do
   not re-fetch text.
6. Rerank and select evidence.
7. Record used evidence with text hashes in the run.

**Citation-led search.** PostgreSQL resolves the paper and its stored edges, then intersects
them with the release's papers. The bounded `paper_id` set becomes the Qdrant filter. An
empty set returns no eligible records and never broadens to the whole corpus. Coverage
(unresolved references, metadata-only targets, traversal limits) is returned with the
result. Multi-hop traversal uses bounded SQL with depth, fan-out and cycle limits.

**Permissions.** Validation uses existing permission evidence and display restrictions.
This project has one private local user, so there are no per-user grants (spec §3.2,
§23 item 9).

## 7. Releases and publication

A release is the physical Qdrant index of one finalized snapshot. The accepted Phase 2
snapshot becomes release `r001`, and benchmarks keep running against it.

1. **Preserve content first.** Artifacts and extractions are stored and checksummed (the
   existing pipeline).
2. **Commit intent.** In one SQL transaction, record the accepted papers and documents and
   an outbox row requesting a release.
3. **Freeze the manifest.** Create and finalize the snapshot: exact members, chunk IDs,
   configuration digests.
4. **Build.** One build worker per collection, enforced by the existing job lease. Fill
   fresh `passages_rNNN` and `papers_rNNN`: reuse cached dense vectors by point ID, compute
   BM25S weights for the release corpus.
5. **Verify.** Check exact point IDs and text hashes against the manifest (counts alone are
   insufficient), required vectors, sample filtered searches and a lexical parity spot
   check.
6. **Publish.** In a short transaction, move the collection's published pointer only if the
   current pointer equals the expected predecessor. A superseded build cannot publish.
7. **Pin.** A research run stores its release at creation and uses it for every search. A
   switch is allowed only at the defined ingestion point (section 9), and is recorded as a
   run event.
8. **Retire.** Delete a release's collections only when no active run pins it and the run
   evidence records are retained.

The original note's multi-worker machinery (attempt tokens, lease-expiry abandonment) is
deferred until more than one build worker exists. The predecessor check gives
superseded-build protection now.

**Size.** Releases duplicate unchanged points. At about 44k passages this is expected to be
small for a laptop, but measure disk and RAM with one live and one staged release before
scaling.

## 8. Recovery

Back up PostgreSQL (`pg_dump`), artifact storage, and each retained release's manifest and
vocabulary. Qdrant collections can be rebuilt from these; Qdrant snapshots are optional
acceleration. After a restore, verify a release against its manifest before serving it. The
Phase 1 rebuild requirement already covers the rebuild path; extend its test to releases.

## 9. Online discovery and ingestion

**Goal:** a research question can find papers online, ingest the permitted ones, and answer
from them.

1. **Local first.** The agent searches the pinned release.
2. **Discover.** If coverage is insufficient, a new `discover_papers` tool queries OpenAlex
   within a per-run request budget. Metadata goes to PostgreSQL. Title/abstract embeddings
   are upserted into `catalog_papers` (dense only, so no IDF dependency; mutable). Candidates
   are ranked by similarity to the question.
3. **Request ingestion.** A new `request_ingestion` tool accepts a bounded set of paper IDs.
   Code, not the model, enforces exact-file permission evidence through the existing
   acquisition adapters (ADR-0007), a per-run paper and cost budget, and no recursive
   acquisition. Papers without a permitted source stay metadata-only records. Each selection
   is recorded with its reason.
4. **Ingest in the background.** Download, Docling extraction (about 85 s per paper in the
   Phase 1 pilot), chunking, embedding, snapshot finalization after automated integrity
   checks, and a release build (section 7). Docling and the generator take turns on the GPU.
5. **Resume.** The run waits in a `waiting_for_ingestion` state on its LangGraph checkpoint
   (ADR-0019), switches to the new release as a recorded event, searches again and answers.

`catalog_papers` also backs a semantic mode of `find_related_papers` (Qdrant recommend
over paper vectors) beside the existing citation-based relations. Discovery ranking and
semantic relatedness are new behavior with no frozen profile, so they need their own
development evaluation before any quality claim.

## 10. Consistency contract

| Situation | Behavior |
| --- | --- |
| Paper accepted for ingestion | Pending until a verified release includes it |
| Metadata corrected after publication | Catalog lookup shows the latest value; search filters and display use the pinned release |
| Parser, chunker or embedding change | New snapshot and release |
| Permission withdrawn | Rejected by live SQL validation, including saved run evidence |
| PostgreSQL unavailable | Fail closed for research reads |
| Qdrant unavailable | Catalog reads continue; search reports unavailable, with no fallback to another release |

## 11. Not adopted from the original note

| Item | Reason |
| --- | --- |
| Qdrant native BM25 and IDF modifier | BM25S scoring stays (section 4) |
| Fusion inside Qdrant | Component ranks required (spec §9.2) |
| Passage text authority moved out of PostgreSQL | `evidence_units` already holds it; spec §8.3 |
| Per-user grants, revocation, tenant partitions | Single private user; spec §3.2 non-goal; auth OPEN |
| Multi-worker attempt tokens and lease abandonment | One build worker; revisit when that changes |
| Separate joint-backup checkpoint protocol | Rebuild from PostgreSQL and artifacts suffices at this scale |

## 12. Source-of-truth changes

Each needs an ADR, owner approval where LOCKED, and a source-of-truth update in the same
change set.

- **ADR A, Qdrant serving.** BM25S weights in Qdrant, content in the payload, fusion in the
  application, parity gate. Changes the §5 diagram and §8.4. No ranking change if parity
  holds.
- **ADR B, Releases.** Per-release physical collections, chunk-based point IDs, published
  pointer, run pinning. Elaborates the §8.6 snapshot rules without weakening them.
- **ADR C, Online discovery and ingestion.** Changes LOCKED §8.6 (run-triggered ingestion,
  automated membership policy and finalization) and LOCKED §10.4 (two new tools); resolves
  part of open decision 8.

New glossary terms for `CONTEXT.md`: **Release**, **Catalog paper**.

## 13. Build order and checks

1. Build release `r001` from the accepted snapshot with dense and BM25S sparse vectors.
   Prove lexical and end-to-end parity.
2. Serve evidence and paper search from Qdrant. Keep in-process BM25S as the test oracle.
3. Add `catalog_papers`, `discover_papers` and semantic related papers.
4. Add the outbox, release worker, published pointer and run pinning.
5. Add `request_ingestion` and the agent's wait-and-resume loop.

Required checks:

- Lexical parity: same top-50 IDs and scores within tolerance. Profile v10 end-to-end
  rankings unchanged.
- Search returns text from Qdrant without SQL text fetches, and the text hash matches
  `evidence_units`.
- A release with correct counts but wrong IDs or hashes is not published. A superseded
  build cannot publish.
- Publishing a release does not change a running run's release except at the recorded
  ingestion switch.
- An empty citation-derived paper set returns no eligible records.
- Ingestion refuses papers without permission evidence and respects the per-run budgets.
- A crash after the SQL commit leaves the release request recoverable. Replaying a build
  produces the same point IDs.
- Restore from PostgreSQL and artifacts rebuilds a release that passes verification.
