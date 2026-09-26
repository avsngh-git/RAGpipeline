---
status: accepted
date: 2026-09-23
---

# Finalize only validated corpus snapshots

A partially processed corpus must remain inspectable without being mistaken for
accepted research evidence. We chose draft snapshots for processing/inspection
and explicit finalization after membership, document/extraction versions,
configuration and evidence/index integrity are validated. Normal research uses
finalized snapshots; unresolved extraction quality failures prevent a paper from
counting as successfully ingested.

## Alternatives and consequences

Publishing each successful fragment immediately would provide earlier access,
but obscure whether a paper's important table evidence had failed. Keeping drafts
separate preserves that distinction and makes later research reproducible.
Retries and reviewed corrections preserve intermediate outputs and provenance;
exclusions/replacements remain explicit selection decisions. Finalized references
are fixed, so changed evidence/configuration requires a new snapshot. A finalized
snapshot smaller than 100 papers does not satisfy the Phase 1 pilot target.

One active ingestion process initially limits resource contention and recovery
complexity; bounded download concurrency and controlled model batches remain
possible. Preserve unresolved external citation identifiers without inventing
complete metadata or recursively downloading related papers.

The authoritative constraints are in
[Section 8.6](../agents/scientific-research-platform-source-of-truth.md#86-phase-1-corpus-policy--locked).
Execution and acceptance are in the [Phase 1 plan](../plans/phase-1-corpus-ingestion.md).
