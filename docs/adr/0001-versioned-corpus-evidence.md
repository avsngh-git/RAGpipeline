---
status: accepted
date: 2026-09-22
---

# Preserve versioned evidence in manually produced corpus snapshots

Scientific results must remain traceable across document and extraction changes,
while local storage and compute are limited. We chose manually triggered,
versioned snapshots containing reusable text and table evidence, with one logical
paper linked to identifiable document versions, rather than relying solely on
whole-PDF interpretation for each question. The initial extraction comparison
will determine whether structured conversion, a local vision model, or a
combination produces that evidence reliably.

## Considered options

- Prose-only ingestion would omit important scientific comparisons; tables are required.
- Query-time PDF interpretation can supplement later research, but alone does not
  provide the agreed reusable index, stable evidence references and rebuild path.
- Continuous collection updates and background workers add operational complexity
  before the manually operated pilot has established quality and resource costs.
- Keeping every intermediate version indefinitely improves historical coverage
  but conflicts with the user's storage-efficiency priority.

## Consequences

Retain unique originals once, share artifacts between collections, compress
extraction outputs, and remove disposable intermediates. Protect versions needed
by retained snapshots or research runs; explicitly retiring those references can
reduce historical reproducibility. Qdrant remains derived and rebuildable.
Published versions take preference, with eligible preprints as fallback and
uncertain identity matches left separate. Source permissions and public passage
display are recorded separately.

Authoritative scope and constraints are in [Section 8.6 of the source of truth](../agents/scientific-research-platform-source-of-truth.md#86-phase-1-corpus-policy--locked).
Execution and acceptance are in the [Phase 1 plan](../plans/phase-1-corpus-ingestion.md).
