# Phase 2 benchmark sampling plan v1

Status: frozen 2026-09-27 for P2-12.1. This fixes the sample size, category floors,
review budget and pool bounds; question-family creation and source judgments remain
P2-12.2–12.5 work. The machine-readable plan is
[`benchmark-sampling-plan-v1.toml`](../../benchmarks/phase2/benchmark-sampling-plan-v1.toml).

## Size and split

Use 30 question families over the accepted snapshot
`4b11fab3-d4a5-4e7a-a58e-8654accf2c6c`: 20 development and 10 held-out. The ten
`phase2-calibration-v1` families are fixed in development. Add ten new development
families and ten held-out families. A family, including all paraphrases, receives one
explicit split assignment in the versioned family manifest before candidate pooling
and review. The held-out set can be prepared and judged, but its scores stay out of
tuning and configuration selection.

The split is a purposive, corpus-grounded sample for this 100-paper snapshot, not a
random sample of scientific questions. Ten held-out families support directional
paired conclusions only; they cannot establish small quality differences precisely.

## Coverage floors

Count distinct families, not paraphrases. Families may cover multiple categories.
Each split must include at least three distinct families for each of:

- discovery;
- specific evidence;
- table results;
- cross-paper comparison;
- filters;
- missing evidence.

Development must include at least five families in each category. The existing ten
calibration families contribute to development coverage. Their recorded category
counts are discovery 1, specific evidence 5, table results 6, cross-paper comparison
1, filters 2, and missing evidence 1. New development families must fill each
shortfall before this plan is considered satisfied.

Because calibration has no direct-positive prose anchors, both splits must include at
least two families with source-checked direct prose evidence. Each split also needs at
least three table-result families, including two numeric/table-value cases, and at
least two negative or mixed-finding families. These modality/findings floors may
satisfy category floors at the same time. If the fixed corpus cannot support a floor,
record the coverage gap and uncertainty before looking at held-out scores; do not
invent evidence or silently relabel an unsupported query.

## Candidate review workload

For each family, pool the top 50 evidence candidates from each named core profile
(BM25, dense, hybrid and reranked), and include feasible alternative configurations
when they are available. Review at most 200 unique evidence candidates per family
after canonical source-anchor deduplication. Pool the top 20 paper candidates per
profile and review at most 80 unique papers per family. P2-12.2 records each profile,
actual depth, merge/dedup/cap procedure, truncation and source-selection bias.

Independently source-found evidence is reviewed as a judgment, but never inserted
into a system's returned ranking. Hide profile and rank during source review where
practical; retain those fields in the restricted pool for audit and coverage analysis.
Unjudged candidates remain unjudged, not label 0.

The calibration review took about 32 minutes for ten families, including nine visual
table regions and a separate search of all 100 papers for one missing-topic case.
That is roughly three minutes per family for source discovery alone; it is not an
estimate for reviewing the larger pooled candidate sets. Budget 12 reviewer-hours
for constructing and reviewing all 30 source/candidate pools (24 minutes per family
on average). Remeasure actual time after the first five newly pooled development
families. If the projected workload exceeds the budget, record achieved coverage and
freeze a revised size plan before held-out scoring. Do not reduce held-out coverage
in response to system scores.

## Review rules

Use the approved 0/1/2 evidence labels, source matching, table-cell associations,
uncertainty and assistant reviewer identity in
[the evaluation protocol](../plans/phase-2-evaluation-protocol.md),
[calibration](phase-2-calibration.md), and
[source-matching policy](phase-2-source-matching.md). Negative and mixed results can
be direct evidence. “Missing evidence” means the documented review found no support
in this fixed snapshot; it is not evidence that the literature has no such study.
Keep the accepted snapshot, source-document manifest, query split, benchmark version,
and retrieval profiles separately identifiable.

No held-out score has informed this plan. Any later plan change receives a new
version and is recorded before held-out evaluation.
