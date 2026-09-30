# Phase 2 benchmark dataset card

| Field | Value |
| --- | --- |
| Dataset | `phase2-benchmark-v1` |
| Snapshot | `4b11fab3-d4a5-4e7a-a58e-8654accf2c6c` |
| Status | Assistant source and candidate review complete; held-out scores remain sealed |
| Active split | `phase2-benchmark-family-splits-v3` |

## Purpose and scope

This benchmark measures scholarly paper and evidence retrieval over the fixed
100-paper Phase 1 snapshot. It covers discovery, specific evidence, numeric table
results, cross-paper comparisons, filters, and bounded missing-evidence questions.
It is a purposive, corpus-grounded sample for this snapshot. It is not a random
sample of scientific questions and does not support claims about general scientific
retrieval.

The active set contains 20 development families and 10 held-out families. The ten
calibration families `q01`–`q10` remain development-only. The new development
families are `q11`–`q20`; active held-out families are `q22`–`q31`. `q21` is
excluded after its private held-out ranks and scores were exposed during review-card
sampling. `q31` replaces it. The q22 scope clarification and q31 replacement were
frozen before v3 held-out pooling.

| Split | Families | Category coverage by distinct family |
| --- | ---: | --- |
| Development, including calibration | 20 | Discovery 5; specific evidence 9; table result 8; cross-paper comparison 5; filters 5; missing evidence 5 |
| Held-out v3 | 10 | Discovery 3; specific evidence 8; table result 3; cross-paper comparison 4; filters 8; missing evidence 3 |

The held-out set includes three numeric-table families (`q22`, `q23`, `q29`), three
direct-positive-prose families (`q24`, `q28`, `q31`), and four negative or mixed
families (`q22`, `q25`, `q26`, `q27`). Ten held-out families support directional
paired conclusions only; they cannot estimate small effects precisely.

## Data and labels

Question and split manifests are tracked in `benchmarks/phase2/`. The active v3
split binds the new development-question manifest hash
`sha256:6581be118f0f54dfe5ac4b0df50fdcca02aaea2a01b65c94360c8a2e60becab2` and
held-out-question manifest hash
`sha256:d4b13f0a63b732f9b7b3a35a50e6e509c463dc20cdcc95b42a085170b21f653b`.
The calibration manifest is separately bound by the split manifest. Paraphrases
inherit the family split.

Candidate relevance uses the approved 0/1/2 scale: 0 is irrelevant, 1 is useful
context or incomplete support, and 2 is direct support for a requested part. Labels
measure relevance rather than whether a finding is favorable. Paper and evidence
labels are separate. Each candidate in the reviewed pools has a resolved label.

| Reviewed pool | Evidence candidates | Evidence labels 0 / 1 / 2 | Paper candidates | Paper labels 0 / 1 / 2 |
| --- | ---: | ---: | ---: | ---: |
| New development `q11`–`q20` | 1,216 | 911 / 252 / 53 | 341 | 274 / 55 / 12 |
| Held-out v3 `q22`–`q31` | 1,581 | 883 / 607 / 91 | 245 | 181 / 52 / 12 |

The ten calibration-family candidate pools are retained with their separate
calibration record; the counts above describe the ten-family expansion and active
held-out pools only. q25 and q26 reached the 200-evidence-candidate family cap, so
the reviewed candidate pool may omit relevant evidence outside its bounded pooling
procedure. Unjudged items outside the active review cards are not treated as label 0.

## Source mapping and review

The q11–q20 source-review notes record 83 source anchors. Seventy-seven map to a
candidate in the reviewed pool. Six remain source-only or outside the question's
required evidence: the q12 Table 1 result, q13 PDFTriage document-type detail, q14
CodeRAG-Bench Table 2 inventory, the q16 retrieval-metric note, and two q18
source-only anchors (legal character offsets and evidence-sentence units). These
anchors remain available for source-coverage accounting and are not inserted into
retrieved rankings. The active held-out source map has 21 anchors, each mapped to a
review candidate, with 34 anchor-to-candidate links. The separate source-alignment
manifest remains calibration-only; cross-chunk fairness mappings for P2-13 are
still pending.

An assistant reviewed candidate relevance and checked source evidence against the
accepted local PDFs. Selected table evidence received visual PDF checks. The q20
systematic-review table was text-extracted but not visually verified because the
WSL environment had no usable PDF renderer. Reviews are not independent human
validation.

The q20 family is disclosed as partially unblinded after origin-map output was
exposed during review. Its candidate labels were not assigned from ranks or scores;
q20 origins and results are excluded from parameter tuning. The q21 family is fully
excluded from tuning and acceptance. No held-out scores have informed configuration
selection, and the active held-out source judgments remain separate from retrieval
and tuning inputs.

## Access, permissions, and intended use

The accepted snapshot permits local storage and indexing under its recorded
permissions; passage display is disabled. Full text, extracted passages, reviewer
cards, source offsets, raw pools, origins, and run scores remain in the ignored
private `local-reference/phase2-runs/benchmark-v1/` tree. They are not part of this
sanitized card or the public repository. The tracked manifests and reports contain
benchmark metadata and source-audit summaries, not pooled source passages.

Use development judgments for bounded experiments after excluding q20 from tuning.
Use held-out judgments only after the P2-15 configuration freeze. Report judged-pool
coverage and the snapshot-bounded nature of negative findings. Do not describe
judged recall as recall over all relevant literature or passages.

## Known limitations

- The sample is small, purposive, and tied to one 100-paper snapshot.
- Assistant-only labels can contain source interpretation errors; there is no
  independent human reliability estimate.
- Candidate pooling is bounded and profile-dependent; q25 and q26 hit the evidence
  cap.
- Six development source anchors do not map to a pooled candidate, as detailed
  above. This limits candidate-pool coverage for those specific anchors.
- q20 has a blinding limitation and is excluded from tuning; q21 is excluded after
  the held-out integrity incident.
- Negative or unsupported findings describe only the documented review procedure
  over this snapshot, not the literature as a whole.
- The ten held-out families support directional paired assessment, not precise
  small-effect estimation.

See the [source coverage audit](../research/phase-2-benchmark-source-coverage-audit.md),
[held-out source audit](../research/phase-2-heldout-question-source-audit.md), and
[evaluation protocol](../plans/phase-2-evaluation-protocol.md) for review and scoring
rules.
