# ADR-0011: Explicit search result semantics

**Status:** Accepted under Phase 2 implementation delegation, 2026-09-27
**Decision owners:** Project owner; assistant implementation/reviewer
**Related:** Phase 2 P2-02 and P2-11.5; [search contract](../api/phase-2-search-contract.md)

## Context

A zero-result response can mean that filters selected no records or that eligible
records produced no returned candidate. Candidate ranks and raw scores also do not
establish that a query is answerable or that a claim is supported. Phase 2 explicitly
keeps relevance cutoffs disabled until calibrated for the exact retrieval mode and
profile.

## Decision

Search responses report an exact `eligible_count` before ranking/page limits and
derive one of three statuses: `no_eligible_records`, `no_candidates_returned`, or
`ranked_candidates`. Every response labels its interpretation `ranking_only`; it
makes no answerability or claim-support assertion.

No relevance cutoff is implemented. A future cutoff requires development calibration
for the exact effective mode and retrieval profile, profile/version provenance, and
freeze before held-out evaluation. Hybrid search requires lexical and dense branches
to agree on the exact eligible count and fails closed when they do not.

## Consequences

- The framework-independent and HTTP response schemas expose eligibility and result
  semantics. Evaluation attempt records persist them under schema version 2.
- Lexical results distinguish filter eligibility from positive term-match counts.
  Dense results expose the exact snapshot/filter count already validated by the index.
- API clients cannot infer support from rank or score. Unsupported-query evaluation
  describes returned candidates unless a later calibrated cutoff is frozen.
- `eligible_count` units follow the operation: papers for paper/metadata search and
  evidence records for evidence search.

## Alternatives considered

- **Infer the reason from an empty hit list:** rejected because it conflates an empty
  eligible scope with eligible records that yield no returned lexical candidate.
- **Add a general score cutoff now:** rejected because development judgments and the
  final mode/profile have not been selected or calibrated.
- **Treat high rank/score as support:** rejected because retrieval relevance and
  claim-level verification are separate operations.
