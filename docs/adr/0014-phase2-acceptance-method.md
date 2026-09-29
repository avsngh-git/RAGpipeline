---
status: accepted
date: 2026-09-29
---

# Fix the Phase 2 acceptance method before the next held-out run

Approved by the project owner on 2026-09-29. Assistant-reviewed judgments throughout;
no human verification is claimed. This ADR
changes how acceptance evidence is gathered and judged. It changes no numeric
threshold, the frozen profile, the strongest-passage paper rule or the snapshot.

## Context

Phase 2 acceptance requires one fresh, source-reviewed held-out set to pass all 14
frozen gates in a single run (nine quality/source gates, five operational gates; warm
p95 is 2,000 ms under [ADR-0013](0013-phase2-warm-latency-acceptance.md)). Ten sets
(v3-v12) have been built and spent, each of about ten purposive, assistant-built
question families. Outcomes do not converge:

| Set | Gates passed | Failed gate(s) |
| --- | ---: | --- |
| v7 | 12/14 | paper nDCG@10; warm p95 |
| v8 | 13/14 | evidence direct MRR@10 |
| v9 | 13/14 | paper nDCG@10 |
| v10 | 13/14 | warm p95 (1,602.2 vs 1,500 ms, since re-set to 2,000) |
| v11 | 14/14 | none (later superseded by code changes) |
| v12 | 8/14 | paper nDCG, evidence nDCG, evidence direct MRR, evidence Recall@20, source Recall@50, positive families hit@10 |

The failing gate changes almost every time. R1-R7 (latency, exact-selection reuse,
accounting, fallback typing) are done with hosted CI; the profile identity
`sha256:959e24b6...` was the same on v10, v11 and v12. Published aggregates for the
selected profile and the baselines (v7-v9 report only failed gates):

| Set | Paper nDCG@10: BM25 / Dense / Hybrid / Selected | Evidence nDCG@10: BM25 / Selected | Source Recall@10 (selected) |
| --- | --- | --- | ---: |
| v3 | 0.624 / 0.720 / 0.712 / 0.725 | 0.111 / 0.331 | 0.353 (17 anchors) |
| v10 | 0.696 / 0.806 / 0.835 / 0.847 | 0.593 / 0.704 | 0.778 (9) |
| v11 | 0.727 / 0.904 / 0.930 / 0.921 | 0.446 / 0.668 | 0.556 (9) |
| v12 | 0.343 / 0.638 / 0.544 / 0.579 | 0.180 / 0.323 | 0.300 (10) |

Every profile moved together from v11 to v12 (paper nDCG shifts of -0.26 to -0.39;
selected -0.34), and BM25 fell to 0.343 against 0.70-0.73 on v10/v11. A retriever
regression would not depress an unchanged lexical baseline; the set (questions,
labels, pooled coverage) changed. Across v10-v12 the selected profile's paper nDCG
has a sample SD of 0.18 (BM25 0.21), from three sets only.

### Sampling noise at ten families

Per-family SD backed out of the v11 paired 95% bootstrap intervals (10 families,
SE = half-width / 1.96, SD = SE x sqrt(10)): paired paper-nDCG difference SD is about
0.19 (selected vs BM25), 0.18 (vs Dense) and 0.13 (vs fixed-window); evidence nDCG
paired SD 0.12-0.21. Per-family SD of a single profile's nDCG is therefore roughly
0.15 (easy sets) to 0.35 (heterogeneous sets). The 95% half-width of a set mean is
1.96 x SD / sqrt(N):

| SD per family | N = 10 | N = 24 | N = 30 | N = 40 |
| ---: | ---: | ---: | ---: | ---: |
| 0.15 | 0.093 | 0.060 | 0.054 | 0.046 |
| 0.25 | 0.155 | 0.100 | 0.089 | 0.077 |
| 0.35 | 0.217 | 0.140 | 0.125 | 0.108 |

At N = 10 the point estimate of paper nDCG carries +/-0.16 to +/-0.22, larger than
the 0.10 margin by which the v11 pass exceeded its 0.80 gate and about the size of the
v11-to-v12 swing. Ratio metrics are worse: direct MRR is defined on positive families
only (7 of 10), with per-family SD near 0.4 (SE 0.15 at n = 7 against 0.08 at n = 24),
and source-anchor recall rests on 9-10 anchors (binomial SE 0.17 at p = 0.5 versus
0.10 at 27 anchors; anchors cluster within families, so these are optimistic). A profile
whose true paper nDCG is 0.85 passes that single gate with probability about 0.67-0.74
at N = 10 (SD 0.35 / 0.25) and 0.78-0.86 at N = 30; the conjunction of nine quality
gates lowers this further. The sampling-only reading (SD about 0.35) explains the
v11-to-v12 shift (2.2 SE of the difference), so N matters. The alternative reading, an
extra between-set component from differing construction and coverage, would not shrink
with N; three sets cannot separate the two. The decision therefore pairs a larger N
with coverage and composition controls and a descriptive difficulty check.

### Judgment coverage precedent

v3 judged only 5.96% of the selected profile's evidence results (9/151; 1.2-7.1%
across profiles) and 88% of paper results. v11 judged 217/301 paper results (72.1%
micro, 82.3% macro) and 173/173 evidence results. Unjudged results carry zero gain in
the frozen "conservative judged-pool" convention, so low coverage can depress every
profile at once. v12's coverage is not published in the sanitized report.

### State of v13

The v13 plan (`phase2-benchmark-sampling-v2`: 31 families, 10 held-out) has a source
screen, 10 unscored candidate themes, exact filter counts, a gate config and runner.
It has no held-out family records, judgments, alignment, freeze or scores; only the
two development families (one comparison, one unsupported) exist and do not count.

## Decision

All points below are assistant-reviewed judgments, approved by the owner on 2026-09-29.

1. **Gates unchanged.** The 14 gate thresholds in `acceptance-v13.toml` (identical to
   `acceptance-v10.toml`) stay fixed. Single run, dataset frozen before scoring,
   assistant-reviewed labeling, snapshot and profile identity unchanged.
2. **Larger held-out set.** Target N = 30 families; floor 24 (recorded, with the
   failing category named, before candidate pooling). Rationale: SE of a set mean
   falls 42% from N = 10 to 30 and 35% to N = 24; beyond 30 the gain is under 10% per
   extra 8 families while review effort and freshness risk grow linearly.
3. **Composition** (distinct families; categories overlap): each of discovery,
   specific evidence, table result, cross-paper comparison and filters at least 5;
   missing evidence at least 4 (each needs a bounded snapshot-wide absence review).
   Modality floors: direct-positive prose at least 5; table-result at least 8 with at
   least 5 numeric-table; negative or mixed findings at least 5. At least 24 positive
   families, at least 20 independently source-reviewed direct anchors across at least
   15 positive families (so source gates rest on more than 9-10 anchors). No more than
   two families may take their positive anchors from the same paper (independence).
4. **Folding v13.** Keep dataset ID `phase2-benchmark-v13`; nothing is scored or
   frozen, so no set is spent. Publish `phase2-benchmark-sampling-v3` (held-out 30,
   supersedes v2's 10; new split manifest and freeze counts; development families and
   the split policy are otherwise unchanged). Source-map themes 1-3, 5, 6, 8, 9 may
   become families after source review (about 6-8 expected; themes 1/2/4/8 share
   COIL, so the two-per-paper cap binds); 7 and 10 only after their conditional
   checks. Theme 4 overlaps the development comparison family (COIL vs MORES
   stage/measure) and is excluded unless shown distinct, since paraphrases inherit
   the family's split. About 22 families need new source screening.
5. **Judgment coverage before freeze.** Pool, for every declared profile (BM25,
   Dense, Hybrid, selected, fixed-window), the top 20 paper and top 50 evidence
   results per query; the per-family caps (80 papers / 200 evidence) are raised if
   they bind. A coverage-only script (judged/unjudged counts; no metric or gold
   output) must show, on the frozen queries, at least 95% judged in each profile's
   top 10 (paper and evidence, micro), at least 90% in the top 20, and no family
   below 80% at top 10 for the selected profile. Shortfalls are closed by source
   review of the missing candidates, blind to profile and rank, never by relabeling
   them 0 or dropping queries; the table is published. Gates still use the frozen
   zero-gain-for-unjudged convention.
6. **Baseline sanity check (descriptive only).** The freeze manifest records, before
   scoring, a reference band from published sets: BM25 paper nDCG@10 0.50-0.85 and
   BM25 evidence nDCG@10 0.25-0.75 (published values 0.62-0.73 and 0.11-0.59; the
   band is judgment, not a threshold). The runner prints the BM25 (and Dense) values
   and the in-band/out-of-band flag before the gate table. A flag is reported as
   "set difficulty unusual" and feeds the diagnosis; it never changes a gate result.
7. **Judgment basis.** Gates are judged on point estimates against the unchanged
   thresholds, as now. The report adds paired family-bootstrap 95% intervals (10,000
   resamples, seed 20260930) and per-category results beside every gate. A gate is not
   passed on an interval and not failed on one.
8. **Bind the code.** The assessed revision must be the release candidate; a later
   change touching retrieval, selection, scoring or profile files needs new evidence
   (v11 was superseded this way). Freeze also records dataset counts, coverage table
   and the difficulty band.
9. **After a failure.** The set is sealed. Work returns to development-only diagnosis
   with a written note (using aggregates only) before any new set is authorized; no
   immediate replacement set. A replacement needs a material change validated on
   development data or an explicit owner decision. At most two acceptance runs
   (enlarged v13 and one replacement) are authorized here. After a second failure
   the owner chooses via change control (re-scoping acceptance evidence or scope);
   no third set is built by default. A pass on all 14 gates accepts Phase 2.

## Feasibility (assistant-reviewed estimates; review time was not measured for v11)

Candidate counts: v11 had 622 reviewed candidates for 10 families (235 paper, 387
evidence; 62 per family); v10 had 559 (56 per family). Scaling: N = 30 is about
1,870 judgments (705 paper, 1,160 evidence); N = 24 about 1,500. The sampling plan
budgets 24 minutes per family (calibration measured about 3 minutes per family for
source discovery only): N = 30 is 12 hours; N = 24 is 9.6 hours. Adding 20% for
coverage top-up and cross-paper/absence reviews gives 11.5-14.4 hours; at a
pessimistic 40 minutes per family, 16-20 hours. The 13-hour plan budget (31 families)
must be re-budgeted. The bigger cost is construction of about 22 fresh families beyond
v13's screen (7 works, 13 screened source documents).

Constraints: the snapshot has 100 papers and 44,277 chunks; about 100 spent held-out
and 21 development families already drew from it, with spent identities unavailable
(origins are unread), so freshness cannot be certified and grows harder with N.
- Missing evidence is the binding category. Each needs a snapshot-wide 38-variant
  screen and primary-source adjudication; three earlier scopes are done and the v13
  unsupported scan still has 12 unadjudicated paper hits. Realistic fresh count is
  4-6, so the floor is 4 and the maximum realistic missing share is about 20%.
- Filters: year counts 2020: 12, 2021: 17, 2022: 9, 2023: 22, 2024: 24, 2025: 15,
  2026: 1; enough ranges for 6 families; each still needs an exact eligible count.
- Direct prose is scarcer than tables (v12: 3 text vs 6 table anchors); the floor of
  5 is plausible but unverified. Tables (at least 8) and cross-paper comparison (at
  least 5) are feasible but comparison families cost more and need matched conditions.
Maximum realistic N is about 30; below the floor of 24 the category floors fail first.
If the feasibility screen finds fewer fresh families, record a revised N no lower
than 24 before pooling; do not proceed below it without a further ADR.

## Consequences

- The next attempt costs roughly 12-20 reviewer-hours instead of about 4 and delays the
  outcome; v13's current 10-family preparation is partly reusable (screens, counts,
  runner) but no scored or frozen work is discarded.
- Sampling noise falls to about SE 0.05-0.06 on nDCG (SD 0.25-0.35); a pass or fail is
  more informative but never certain. Systematic set effects are addressed only by
  coverage, composition and the descriptive check, not eliminated.
- The unsupported-family share and the anchor count become explicit design levers.
- The runner needs a coverage-only mode, a baseline-context block and new freeze counts;
  it builds its timing cases from all families, and its only N-dependent check is the freeze manifest's dataset counts (timing sample sizing at N = 30 is unverified).
- Attempts are bounded; a second failure escalates to the owner rather than a third set.

## Alternatives considered

- **Keep 10-family sets.** Cheapest, but SE 0.08-0.11 on nDCG and 0.15+ on MRR make the
  outcome close to a coin flip near the gates; ten sets have not converged.
- **Accept on v11.** Rejected: v11 predates later code changes, the same profile scored
  0.58 paper nDCG on v12, and it would waive the single-run rule after the fact.
- **CI-lower-bound gates.** Rejected: at N = 30 (SD 0.25) they require a point
  estimate near 0.89 for the 0.80 gate, silently raising the bar; upper-bound
  ("not significantly below") gates silently lower it. Both violate the fixed-threshold
  constraint. CIs are reported, not gated.
- **Pooling v10-v12 with v13.** Rejected: spent sets cannot be reused for acceptance.
- **Random sampling of families.** Preferable statistically but infeasible for
  assistant-built, source-reviewed questions over 100 papers; the sample stays purposive.

## Change-control items (applied on approval)

1. Source of truth `docs/agents/scientific-research-platform-source-of-truth.md`:
   section 9.4 "Benchmark and review" and "Evaluation" bullets (31 families/10 held-out,
   "Ten held-out families support directional..."), section 21 Phase 2 gate paragraph,
   section 23 item 12, header version/date/stage, and the ADR list in 9.4 (this is a
   LOCKED bullet; owner approval required).
2. `benchmarks/phase2/benchmark-sampling-plan-v3.toml` (new) and
   `docs/reference/phase-2-benchmark-sampling-plan.md` (current-plan section, budget).
3. `docs/plans/phase-2-evaluation-protocol.md`: "Question sampling and splits" (size
   decision, coverage pre-check), "Required metrics" (judgment coverage), "Timing and
   uncertainty" (CIs beside point-estimate gates).
4. `docs/plans/phase-2-retrieval-evaluation.md`: P2-12 row and section, P2-20, v13
   sections. `docs/plans/phase-2-improvement-plan.md` R8 steps 1-5.
5. `docs/plans/phase-2-agent-handoff.md`: next actions 3-5 and checklist (ten-family).
6. `docs/reference/phase-2-benchmark-dataset-card.md` and
   `docs/reference/phase-2-acceptance-report.md` (status, method, v13 placeholder).
7. `docs/adr/0012-phase2-accepted-retrieval-profile.md` consequences ("ten-family"
   wording); `README.md` status; `benchmarks/phase2/acceptance-v13.toml` (identity
   only, thresholds untouched); new `benchmarks/phase2/r8-v13-freeze-v1.toml`;
   `scripts/phase2_r8_v13_acceptance.py` (coverage mode, baseline block).
