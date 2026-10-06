# Phase 3.5 owner decisions

**Status:** record of the owner's judgement calls during Phase 3.5, kept for later analysis.
Each entry gives the date, what was decided, the evidence it rested on, the alternatives
that were set aside, and what to re-examine later. Decisions delegated to the assistant are
listed separately at the end.

## Owner decisions

### 1. Plan, ADRs and sequential implementation (2026-10-04)

- **Decision:** accepted ADR-0022 (Qdrant search and content), ADR-0023 (index
  generations) and ADR-0024 (online discovery and ingestion), and asked for the 30 cards to
  be implemented one at a time on `phase3.5/implementation`, one commit per card, pushing
  only on request.
- **Record:** [handoff](../plans/phase-3.5-agent-handoff.md), map issue
  [#44](https://github.com/avsngh-git/RAGpipeline/issues/44).

### 2. Tie-aware lexical parity (2026-10-05, P35-15)

- **Decision:** amended ADR-0022 item 7. Lexical parity counts results whose scores agree
  within 1e-6 relative at every position as matching, even when their order differs.
  Strict ID-for-ID counts are still reported.
- **Evidence:** development queries were identical (84/84 lexical, 336/336 end to end).
  Strict order differed on 37 of 200 sampled queries, every time among results that BM25S
  scores exactly equal in float32 and Qdrant scores about one float32 unit apart (largest
  relative difference 2.8e-7) ([parity report](phase-3.5-lexical-parity-report.md)).
- **Alternatives set aside:** re-score Qdrant candidates in Python with BM25S arithmetic;
  the full Phase 2 re-evaluation with a fresh held-out set (P35-16); keep BM25S for
  lexical search.
- **Consequence:** `v10-qdrant` inherits the Phase 2 acceptance; P35-16 was closed as not
  needed. Served rankings can differ from BM25S among exactly tied results (10–15 of 200
  sampled queries changed in the top 10 end to end).
- **Re-examine:** if a later evaluation finds rankings drifting, check tie handling first.

### 3. Cutover to Qdrant serving (2026-10-05, P35-17)

- **Decision:** approved switching the active profile to `v10-qdrant`, making Qdrant the
  default content source and lexical engine, and deleting the superseded Qdrant
  collections `phase2-dev-gte-modernbert-base-v1`, `research-passages-gte-v1` and
  `research-papers-gte-v1`.
- **Evidence:** Gate B; no research run queued or running; a vector export of the Phase 2
  collection under `local-reference/phase35/qdrant-export/`.
- **Consequence:** order among duplicate chunks with identical embeddings changed for 18 of
  336 development responses (the dense branch has no ID tie-breaker). BM25S remains the
  fallback (`RESEARCH_PLATFORM_LEXICAL_ENGINE=bm25s`).

### 4. Delegating P35-18 to P35-24 to other agents (2026-10-05)

- **Decision:** the owner had cheaper agents implement P35-18 to P35-24, then asked for a
  review, fixes and a push.
- **What the review found:** failing tests (integration module order, the frozen Phase 3
  fitness check), formatting, an incomplete handoff, an outstanding P35-24 acceptance
  criterion, and the P35-22 leave-out build deleting the shared `phase1-e5-small-v2`
  collection. The collection was restored from the export and the script fixed.
- **Accepted with the fixes:** P35-24 made `PdfEvidenceProcessor` accept no snapshot, a
  shared-module change the card asked to raise first (backward compatible).
- **Kept as is:** the P35-22 commit message has no card number; rewriting pushed history
  was not worth changing cited hashes.
- **Re-examine:** delegated cards that touch shared data or shared modules need review
  before they run against live services.

### 5. Push and pull request (2026-10-05)

- **Decision:** asked for the branch to be pushed and the remaining items fixed. Pull
  request [#76](https://github.com/avsngh-git/RAGpipeline/pull/76) was opened so hosted CI
  runs (CI runs only on pull requests and `main`).

### 6. Phase 3.5 acceptance (2026-10-06, P35-30)

- **Decision:** accepted Phase 3.5, including two judgement calls:
  1. **Gate D rests on a forced trigger.** The live model never called `discover_papers` or
     `request_ingestion` on its own (10 natural runs). The wait-cap gate was measured with
     the first plan scripted to discover and request the hidden papers: 9 of 9
     ingestion-triggering runs finished within the cap, none failed
     ([evaluation report](phase-3.5-evaluation-report.md)).
  2. **Flagged-table review blocks online ingestion of table-heavy papers.** Every hidden
     paper re-extracted in the live evaluation flagged a results table, and automatic
     finalization refuses unreviewed flagged tables, so no hidden paper was ingested.
     Accepted as a known limitation rather than relaxing the Phase 1 quality rule.
- **Gates at acceptance:** A passed; B passed under decision 2; C reported (hidden-paper
  recall@10 mean 0.100); D as above, with the seven scripted cases green in hosted CI.
- **Re-examine (Phase 4 inputs):** planner tool choice, a review step or policy for
  flagged tables in online ingestion, answer quality on abstract evidence, configuration
  drift handling, a Compose worker image, retention of retired points, and a dense
  tie-breaker ([source of truth](../agents/scientific-research-platform-source-of-truth.md),
  section 21).

## Decisions delegated to the assistant

These were made by the assistant under the owner's delegation and are recorded on the
issues named.

- **P35-13/P35-15:** the live-test module named `test_phase35_*` (integration order rule)
  instead of the card's name.
- **P35-15:** a 1e-6 relative tolerance as the meaning of "float32 tolerance"; the built-in
  `Qdrant/bm25` comparison scored on the 12 development families that still have
  judgments (labels for q11–q19 were lost on 2026-09-30).
- **P35-25 ([#69](https://github.com/avsngh-git/RAGpipeline/issues/69)):** online child
  snapshots are finalized without the legacy per-snapshot index
  (`require_snapshot_index=False`); generation verification checks the index instead.
  Publication may skip failed generations. New papers with paper-specific validation
  issues are refused rather than failing the whole append.
- **P35-26:** an unknown publication year or language is not refused (the policy refuses
  only clear cases).
- **P35-27:** runs pin the generation published when they first start (not at creation),
  and resumed runs rebuild provenance from their starting identity.
- **P35-29:** the forced-trigger pass, reported separately from the natural pass.
