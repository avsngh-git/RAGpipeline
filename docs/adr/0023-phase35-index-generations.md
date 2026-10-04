---
status: accepted
date: 2026-10-04
---

# Phase 3.5: index generations, publication and run pinning

Accepted by the project owner on 2026-10-04, after the Phase 3.5 planning interview,
with the instruction to begin implementation.
Elaborates the source-of-truth section 8.6 snapshot rules and ADR-0002 finalization
without weakening them. Depends on ADR-0022.

## Context

- Qdrant point IDs are `uuid5(snapshot_id:evidence_id)`, so every snapshot copies every
  point.
- Online ingestion (ADR-0024) grows the corpus in small batches, and research runs must
  stay reproducible while it grows.
- Sparse-vector IDF in Qdrant is computed per shard by default. From Qdrant 1.19 the
  `idf` search parameter takes a separate corpus filter that limits the population.
- The compose stack pins Qdrant 1.14.1.

## Decision

1. **Generation.** A generation is a numbered, finalized snapshot, so ADR-0002 validation
   applies unchanged.
   - Generation 1 is the accepted 100-paper snapshot
     `4b11fab3-d4a5-4e7a-a58e-8654accf2c6c`.
   - Each later generation is its parent's members plus newly ingested papers, linked
     with recorded lineage. Benchmarks stay pinned to generation 1.
2. **Point lifecycle.** Each point carries `added_generation` and an optional
   `retired_generation`. Generation N is the points with `added_generation ≤ N` and
   `retired_generation` absent or `> N`. Both the retrieval filter and the IDF corpus
   filter use this condition, so a run sees exactly its generation's rarity statistics.
3. **Registry.** Generations belong to one row of the existing `collections` table (the
   corpus boundary in spec section 7.2). PostgreSQL records each generation:
   - its snapshot, index configuration and manifest digest;
   - its build state: `building`, `verified`, `published` or `failed`.

   Each collection and index configuration has one published pointer.
4. **Publication.**
   1. Preserve the artifacts.
   2. Commit the intent.
   3. Freeze the manifest.
   4. Upsert the new points.
   5. Verify:
      - exact point IDs and `text_sha256` values against the manifest;
      - required vectors are present;
      - sample filtered searches return results.
   6. Move the pointer in a short transaction, only if the current pointer equals the
      expected predecessor.

   Points of an unpublished generation are invisible, because every query filters by a
   published generation. One build worker per configuration is enforced by the existing
   job lease.
5. **Run pinning.** A run stores its generation at creation and uses it for every search.
   The one exception is the recorded switch after the run's own ingestion completes
   (ADR-0024). Pinned generations are recorded in run provenance.
6. **New configuration, new collection.** A changed embedding model, analyzer or BM25
   parameter creates a new collection. It also does so when the corpus average length
   drifts more than 10% from the configuration's fixed value.
7. **Retirement.** Retired points and old collections are purged only when no active run
   pins a generation that includes them. Run evidence copies are kept regardless.
8. **Qdrant version.** Pin the latest stable Qdrant at or above 1.19 after the P35-02
   compatibility spike. Keep the `httpx` adapter; do not add `qdrant-client`.

## Consequences

- No point copying between generations. Publishing a batch writes only new and retired
  points.
- The published collection receives writes while it serves. Correctness rests on the
  generation filter and the pointer check, so both need tests.
- Purging is a tracked operation, separate from retirement.
- A Qdrant upgrade and a one-time rebuild of generation 1 are required.

## Alternatives considered

- **A physical collection pair per release.** Simple isolation, but every release copies
  every point. It is unnecessary once the IDF corpus filter exists.
- **Generations replacing snapshots.** It would discard ADR-0002 validation and the
  benchmark pinning.
- **A moving Qdrant alias resolved per call.** Runs could change corpus mid-run, and a
  second publication mechanism would compete with the SQL pointer.
