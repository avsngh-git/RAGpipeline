# ADR-0003: Ingestion persistence and migration safety

- Status: Accepted for Phase 1 implementation
- Date: 2026-09-23

## Context

Phase 1 needs durable paper and document identity, acquisition provenance,
versioned extraction evidence, unresolved citation endpoints, resumable stage
attempts, immutable finalized snapshots, and rebuildable index state. The
Phase 0 schema has basic papers, documents, chunks, jobs, and resolved citations,
but it cannot represent those relationships or preserve multiple extraction
versions. The existing `001_initial.sql` migration is already applied in some
installations and must remain unchanged.

## Decision

Keep PostgreSQL as the authority for metadata and pipeline state. Add these
capabilities with a new additive migration rather than editing `001_initial.sql`:

- normalized verified external identifiers and a separate unresolved-citation
  table, so an unknown cited work is not represented as a fabricated paper;
- document-level published/preprint classification and unique SHA-256 artifact
  records, with acquisition permissions and source provenance recorded on the
  document/artifact association;
- extraction rows keyed by document and effective configuration, with sections,
  chunks, evidence locations, structured table JSON and normalized evidence
  units linked to a specific extraction;
- stage-attempt records with input fingerprints, outputs, failures, timing and
  resource measurements;
- draft snapshots and fixed paper/document/extraction membership, with database
  triggers preventing mutation after finalization;
- explicit index configuration and reconciliation state, while treating Qdrant
  as a rebuildable derived store.

Apply each SQL migration and its version record in one PostgreSQL transaction.
Serialize migration processes with a session-level advisory lock. This keeps a
failed migration retryable and prevents two processes from applying the same
migration concurrently.

## Consequences

The new relationships make lineage and recovery inspectable in SQL and retain
multiple extraction attempts without overwriting evidence. Artifact deduplication
uses content hashes while keeping source/permission facts per acquisition. The
application must finalize a snapshot only after validating its members and index;
the database trigger enforces immutability after that decision but does not
replace the application validation. JSONB is used for parser-shaped table data
and source coordinates because those payload details depend on the selected
extractor; stable identities and relational links remain columns.

The migration runner now requires permission to acquire PostgreSQL advisory
locks. Operators should run migrations before starting the application. The
implementation remains limited to one active ingestion process; the job lease
fields support stale-owner detection but do not introduce a background worker.

## Implementation decisions recorded under this ADR (2026-09-23)

- Each extraction references the exact `document_artifacts` association that
  supplied its source PDF; indexing requires storage and indexing permission on
  that same association and its immutable permission-evidence record.
- Each Qdrant collection is assigned to one complete embedding configuration. A
  collection can contain points for several snapshots, with snapshot membership
  in payload. Point IDs are deterministic per snapshot/evidence ID. Rebuild and
  finalization compare the exact sorted evidence-ID fingerprint and count against
  PostgreSQL. This avoids cross-configuration mixing and detects same-count
  membership drift.
- PostgreSQL permits one active ingestion job lease. Expired leases mark running
  attempts as retryable failures; an old owner cannot commit after recovery.
- Snapshot finalization records the reviewer and validates the evidence/index
  state in the same transaction that freezes membership. The Phase 1 acceptance
  CLI defaults to at least 100 members; a smaller threshold remains available for
  the separately reviewed 10-paper comparison.

A per-snapshot Qdrant collection was considered but would duplicate vectors for
shared evidence. Named vectors for multiple embedding models in one collection
were also considered, but require more complex rebuild and query configuration.
The selected one-collection-per-embedding-configuration rule keeps the index
replaceable and makes incompatibility explicit. The exact embedding model remains
OPEN until P1-08/P1-10 pilot measurements.
