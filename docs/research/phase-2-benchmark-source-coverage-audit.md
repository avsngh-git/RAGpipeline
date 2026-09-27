# Phase 2 benchmark source and review coverage audit

| Field | Value |
| --- | --- |
| Reviewer | Assistant |
| Date | 2026-09-27 |
| Dataset | `phase2-benchmark-v1` |
| Active split | `phase2-benchmark-family-splits-v3` |
| Scope | Source mappings, review completeness, split hashes, and coverage floors. No held-out scores or origin ledgers were read. |

## Split and family checks

The active split manifest assigns question families and binds both question
manifests by SHA-256. Recomputed hashes match the tracked manifest:

| Manifest | SHA-256 | Families |
| --- | --- | ---: |
| `benchmark-development-questions-v1.toml` | `6581be118f0f54dfe5ac4b0df50fdcca02aaea2a01b65c94360c8a2e60becab2` | 10 new development |
| `benchmark-heldout-questions-v3.toml` | `d4b13f0a63b732f9b7b3a35a50e6e509c463dc20cdcc95b42a085170b21f653b` | 10 active held-out |

The split also binds the ten-family calibration manifest. Together the calibration
families and new development families produce 20 development families. The active
held-out families are q22–q31. q21 is explicitly excluded and q31 replaces it.
Paraphrases inherit their family assignment. All six category floors in the frozen
sampling plan are met in each split; the exact counts are in the [dataset card](../reference/phase-2-benchmark-dataset-card.md).

## Candidate review completeness

Review-card status and candidate label totals were checked directly from the named
review pools. `*origins.json` files were excluded from every read and glob.

| Pool | Families | Evidence candidates reviewed | Paper candidates reviewed | Label coverage |
| --- | ---: | ---: | ---: | --- |
| New development, q11–q20 | 10 | 1,216 | 341 | Every candidate has label 0, 1, or 2 |
| Active held-out v3, q22–q31 | 10 | 1,581 | 245 | Every candidate has label 0, 1, or 2 |

The evidence and paper label distributions, including per-split totals, are recorded
in the dataset card. q25 and q26 each reached the evidence cap of 200. Those pools
are complete for the declared bounded review, but cap saturation means this does
not prove corpus-wide candidate recall.

## Source-anchor mappings

The q11–q20 private source-review notes contain 83 anchors. Seventy-seven map to
candidate IDs in the review cards. Six are documented as source-only or outside the
question's requested evidence: one each for q12, q13, q14, and q16, and two for
q18. The q12/q14 table audit and family notes explain why source-found table
evidence is retained for coverage without being inserted into a system ranking.

The active held-out v3 source-judgment manifest contains 21 anchors. All 21 map to
review candidates, giving 34 anchor-to-candidate links. These are independent
source-found review mappings; they do not add the source-found candidate to a
retrieval result. The existing executable source-alignment manifest is still
calibration-only. Mapping each gold source span against both chunking variants is a
P2-13 fairness task and remains open.

## Category and modality floors

The active family manifests meet all six frozen category minima. Held-out modality
coverage is also explicit in the source audit: q22/q23/q29 are numeric-table cases;
q24/q28/q31 have direct-positive prose anchors; q22/q25/q26/q27 are negative or
mixed cases. The source-checked development expansion adds source-supported prose
and numeric table evidence, while q15 and q19 provide bounded missing-evidence
cases. Calibration contributes the remaining development category coverage.

This is a family-level coverage audit, not a claim that every pooled card was found
by an exhaustive corpus search. Missing-evidence findings remain bounded to their
documented snapshot and search procedure.

## Integrity and limitations

- q20 was partially unblinded during source review. Its labels were assigned without
  ranks or scores, but its origins and results are excluded from parameter tuning.
- q21 is excluded after private held-out rank and score exposure. q31 was source
  checked and frozen before its v3 retrieval pool was built.
- q22's scope clarification and q31 replacement are recorded by split v3 and were
  frozen before v3 pooling.
- All candidate reviews are assistant-only. Source checks and table image checks
  reduce, but do not remove, interpretation risk or establish human agreement.
- Source-anchor mapping to reviewer candidates is distinct from source-span
  matching against a particular chunking configuration. The latter remains open
  under P2-13.

No held-out score informed model, retrieval, reranker, chunking, or threshold
selection. Held-out labels remain sealed for the P2-20 evaluation gate.
