---
status: accepted
date: 2026-10-04
---

# Phase 3.5: Qdrant executes search and serves evidence content

Accepted by the project owner on 2026-10-04, after the Phase 3.5 planning interview,
with the instruction to begin implementation. Item 7 amended by the owner on
2026-10-05 (tie-aware lexical parity; see the
[parity report](../reference/phase-3.5-lexical-parity-report.md)).
Amends source-of-truth sections 5, 8.4 and 9.4 and refines ADR-0010 and ADR-0017; it
does not change the accepted Phase 2 gates.

## Context

- Qdrant only runs dense search today. Lexical search runs in-process with BM25S, and
  search results fetch passage text from PostgreSQL `evidence_units`.
- Profile v10 (ADR-0017) passed v14 by 0.002–0.012 on three quality gates. All held-out
  sets are spent. ADR-0010 requires a new development comparison and fresh held-out
  validation for any lexical library or analyzer change.
- The `scientific-en-v1` analyzer keeps numbers, compounds and operators, with no stemming
  or stopwords. Qdrant's built-in `Qdrant/bm25` is a general English encoder.
- BM25S Lucene scoring is a sum of per-document term weights, which a sparse dot product
  reproduces. Qdrant's sparse `idf` modifier applies term rarity at query time.
- Spec section 9.2 requires every hit to keep its component ranks and scores. Qdrant's
  fused results do not return them.

## Decision

1. **Ownership.** PostgreSQL stays authoritative for the catalog, citations, permission
   evidence, evidence text, jobs and runs. Qdrant executes dense and lexical search and
   serves evidence content.
2. **Content in the payload.** Passage points carry the evidence text, section, offsets,
   source location and spans, filter fields and `text_sha256`. Search reads content from
   Qdrant. PostgreSQL validates permission evidence and membership in one batch query but
   does not re-fetch text. Structured table context stays in PostgreSQL
   (`evidence_tables`) and is attached as today.
3. **Lexical engine.** Python tokenizes with `scientific-en-v1` and computes each
   document's BM25 term weights (`k1=1.5`, `b=0.75`, average length fixed per index
   configuration). Qdrant stores them as a sparse vector `scientific_bm25` with the
   `idf` modifier and executes the query.
   - Term IDs come from an append-only PostgreSQL vocabulary table, not from hashing.
   - Query tokens missing from the vocabulary are dropped.
   - Qdrant's built-in `Qdrant/bm25` is evaluated on development data only, as a
     comparison arm.
4. **Fusion stays in the application.** The dense and sparse branches are separate Qdrant
   queries under the same filter. They may be combined into one batch query only if the
   latency measurement requires it. The existing RRF code fuses them (`rank_constant` 60).
   A Qdrant exact count gives the eligible-record count. Reranking and evidence selection
   are unchanged. The lexical branch becomes asynchronous; the BM25S retriever is wrapped
   in an async adapter so both engines satisfy one protocol.
5. **Collections.** One `passages` and one `papers` collection per index configuration.
   - Point IDs are `uuid5(evidence_id, index_configuration_id)`, or
     `uuid5(paper_id, index_configuration_id)` for papers.
   - `papers` holds every known paper. `indexed_generation` is null for metadata-only
     records.
   - Payload indexes are created before bulk upsert.
6. **Profile `v10-qdrant`.** The Qdrant-served pipeline is a new profile ID, so
   provenance shows which engine served each run.
7. **Parity rule.** `v10-qdrant` inherits the Phase 2 acceptance if both of these hold on
   the development families and sampled queries:
   - lexical top-50 IDs and scores match BM25S within float32 tolerance;
   - end-to-end v10 rankings are identical.

   Otherwise the full Phase 2 procedure applies: a development comparison, then a fresh
   30-family held-out set judged against the v14 gates.

   **Amendment (owner decision, 2026-10-05, P35-15).** Two float32 implementations
   cannot break exact score ties the same way: BM25S orders equal scores by evidence
   ID, while Qdrant's sums differ from them in the last bits. The lexical check is
   therefore tie-aware. Lists match when the counts are equal and, at every position,
   the two scores agree within a relative tolerance of 1e-6. Results whose scores
   agree that closely may appear in a different order or swap across the top-50 cut.
   Results whose scores differ by more must keep their order. The end-to-end check
   is unchanged. Reports also give the strict ID-for-ID mismatch count.
8. **Fallback and cutover.** If `v10-qdrant` fails, the lexical branch reverts to
   in-process BM25S and Qdrant keeps dense search and content serving. The old path stays
   behind the profile switch until the gate passes. Afterwards, BM25S remains only as the
   parity oracle in tests.

## Consequences

- Qdrant becomes the search engine for both branches. One filter implementation replaces
  the separate BM25S eligible-row filter.
- Evidence text is stored twice. PostgreSQL remains the authority, and the payload hash
  detects drift.
- The vocabulary table and average length become versioned parts of the index
  configuration.
- Exact parity depends on Qdrant's IDF formula matching Lucene's. The P35-02 spike
  checks this before any build work.

## Alternatives considered

- **Built-in `Qdrant/bm25` as the engine.** Least code and live IDF, but it loses the
  scientific tokenization and forces a full held-out redo. It is kept as a comparison arm.
- **Keep in-process BM25S.** Proven and fast at this scale, but it leaves Qdrant without
  a lexical role and keeps two filter implementations. It is kept as the fallback.
- **Fusion inside Qdrant.** One call, but component ranks are lost (spec section 9.2).
- **Move text authority to Qdrant or artifact exports.** It conflicts with spec section
  8.3 for no measured benefit.
