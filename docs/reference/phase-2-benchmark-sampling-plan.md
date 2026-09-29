# Phase 2 benchmark sampling plans

## Current plan: v3 (adopted 2026-09-29, ADR-0014)

The machine-readable current plan is [benchmark-sampling-plan-v3.toml](../../benchmarks/phase2/benchmark-sampling-plan-v3.toml),
adopted under [ADR-0014](../adr/0014-phase2-acceptance-method.md) (owner-approved
2026-09-29). It keeps dataset ID `phase2-benchmark-v13`, the accepted snapshot, the 21
development families and the split policy, and replaces v2's ten held-out families with
a target of 30 (floor 24). Nothing in v13 was scored or frozen, so no set is spent. The
held-out families will be constructed afresh and source-reviewed; no spent set is reused.

Held-out composition, counting distinct families (categories overlap): each of
discovery, specific evidence, table result, cross-paper comparison and filters at least
5; missing evidence at least 4; direct-positive prose at least 5; table result at least
8, of which numeric-table at least 5; negative or mixed findings at least 5; at least
24 positive families; at least 20 independently source-reviewed direct anchors across
at least 15 positive families; no more than two families taking positive anchors from
the same paper. If the feasibility screen supports fewer than 30, record a revised N no
lower than 24, naming the failing category, before pooling; below 24 needs a further ADR.

Before freeze, every declared profile (BM25, Dense, Hybrid, selected, fixed-window) is
pooled to the top 20 papers and top 50 evidence results per query (per-family caps of 80
papers and 200 evidence are raised if they bind). A coverage-only check must show at
least 95 percent judged in each profile's top 10 and 90 percent in the top 20 (micro),
and no family below 80 percent at top 10 for the selected profile. Shortfalls are closed
by blind source review of the missing candidates, never by relabeling them 0 or
dropping queries.

Budget: 24 minutes per family is 12 reviewer-hours at 30 families (9.6 at 24); adding
20 percent for coverage top-up and cross-paper/absence review gives 11.5-14.4 hours, so
the plan budgets 15 (16-20 at a pessimistic 40 minutes per family). This replaces v2's
13 hours for 31 families; review time is remeasured after the first five new held-out
families. About 22 families need new source screening. At most two acceptance runs are
authorized.

No held-out score informed this revision. Gates use point estimates against unchanged
thresholds with bootstrap intervals reported beside them; complete freshness against
unavailable spent-family identities cannot be certified.

## Superseded plan: v2 (frozen 2026-09-29)

Status: superseded before any v13 scoring by v3. The machine-readable v2 plan is
[benchmark-sampling-plan-v2.toml](../../benchmarks/phase2/benchmark-sampling-plan-v2.toml).
It froze 31 families (21 development, 10 held-out) and a 13-hour budget; its
development composition and split policy carry into v3 unchanged.

## Historical plan: v1 (frozen 2026-09-27)

Status: frozen for its original P2-12.1 benchmark construction. Its size decision is
superseded by v2 and then v3; its original records remain unchanged. The machine-readable v1 plan is
[benchmark-sampling-plan-v1.toml](../../benchmarks/phase2/benchmark-sampling-plan-v1.toml).

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
