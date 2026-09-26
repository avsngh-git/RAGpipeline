# Phase 2 paper-candidate fusion

**Status:** Initial implementation policy; assistant-reviewed 2026-09-27.

Paper search combines two independently ranked candidate lists:

- metadata candidates ranked over title and abstract text;
- evidence candidates ranked after grouping eligible passages by paper.

The initial policy reuses the profile-bound `rrf-v1` method and its positive
`rank_constant` (`k`). For a paper present in either or both lists, the aggregate is:

```text
RRF(paper) = sum(1 / (k + branch_rank))
```

There is one contribution per branch per paper. A missing branch contributes nothing.
The metadata BM25 score and evidence component scores are retained in their own
provenance; they are never added to one another. The returned paper result carries
`metadata_rank` and `evidence_rank`; `component_scores.fusion` carries the fused rank
and RRF score. Supporting `EvidenceHit` values retain the evidence branch's original
component scores.

Equal aggregate scores are ordered by canonical public paper ID. A metadata-only result
has an empty `supporting_evidence` tuple; no passage is inferred from title or abstract
matching. Evidence-only results retain the grouped paper's strongest eligible passage
and its bounded support set.

This is a reproducible starting policy, not a selected winner. Evaluate the rank
constant and metadata/evidence fusion on the development benchmark in P2-14, before
held-out assessment. Any change remains profile-bound and must retain branch-rank
provenance.
