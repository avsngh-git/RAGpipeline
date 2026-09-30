---
status: accepted
date: 2026-09-29
---

# Revise how Phase 2 is accepted after two failed acceptance attempts

Accepted by the project owner on 2026-09-30 with the thresholds below. All judgments in it are assistant-reviewed;
none are human-verified.

## Context

- **v13 result.** Under [ADR-0014](0014-phase2-acceptance-method.md), the enlarged v13 held-out set (30 families)
  failed 10 of 14 gates. The failures were paper nDCG@10 (0.686 against 0.80) and three evidence gates.
- **Development diagnosis.** The [development diagnosis](../research/phase-2-development-diagnosis-post-v13.md)
  rebuilt the 21 development families using the v13 pooling and judging method.
  - The selected profile clears the paper gate only on the ten calibration families (0.810).
  - On q11–q19 it scores 0.685 on paper nDCG and 0.414 on evidence nDCG, close to v13's paper score.
  - The original limits were set from a development baseline dominated by sparsely judged calibration families, so
    they overstated what this corpus, these models and this hardware class achieve.
  - Ten development-only paper-ranking variants were tried. None reaches 0.80. The best, ordering papers by their
    strongest reranked passage, reaches about 0.79 overall and 0.73 on q11–q19.
- **Stop rule.** The owner's stop rule of 2026-09-29 says a replacement set is built only if a development variant
  clears the gates. None does, so ADR-0014 point 9 sends the decision to the owner.
- **Contamination.** The v13 aggregates are now known. Any threshold chosen now could be fitted to them. v13 therefore
  cannot be re-judged under revised gates, and any revision applies only to the one remaining fresh set.

## Options

1. **Keep the gates; accept Phase 2 with a documented limitation.**
   - Phase 2 closes on the engineering gate: correctness, permissions, filtering, rebuild, failures and operations,
     all of which passed.
   - The report records honestly that absolute retrieval quality did not meet the 0.80 / 0.45 targets. No
     replacement set is built.
   - This is the cheapest option and keeps the evidence intact, but "accepted" then means something weaker than the
     SoT gate text.
2. **Relative-plus-floor gates on one fresh set** (recommended).
   - Replace the four failing absolute quality gates with requirements measured on the one remaining fresh
     held-out set:
     - (a) The selected profile beats BM25 on paper and evidence nDCG@10, with the paired 95% lower bound above 0.
     - (b) The selected profile beats Dense on evidence nDCG@10, with the lower bound above 0.
     - (c) Paper nDCG@10 is not below Dense by more than 0.05 on the point estimate.
     - (d) Absolute floors of paper nDCG@10 ≥ 0.60 and evidence nDCG@10 ≥ 0.30, set from development
       q11–q19 (about 0.88× and 0.72× of the selected profile's development scores) before any new held-out
       scores exist.
   - Operational and source gates stay unchanged.
   - This tests whether the system's components earn their place (portfolio goal §2.3; SoT §9.3) rather than an
     absolute bar the corpus may not support. ADR-0014 rejected CI-based gates as silent threshold changes; here the
     change is explicit and owner-approved.
   - The cost is one more construction cycle (about 12–20 reviewer-hours).
3. **Improve first, then reuse the current gates.**
   - Implement reranker-based paper ordering and an evidence-recall change (for example, deeper candidate pools or a
     stronger reranker within the RTX 3050 budget).
   - Validate on development, and build the fresh set only if development clears 0.80 / 0.45.
   - This offers no assurance of convergence: evidence recall at 50 is 0.40 on q11–q19.
4. **Rescope the acceptance evidence.** Replace the held-out absolute gates with a larger development-plus-held-out
   report and defer absolute quality to Phase 6 documentation. This weakens the pre-registered test more than
   option 2.

## Decision (owner-approved 2026-09-30)

The four failing quality thresholds are lowered for the one remaining fresh held-out set. The values are recorded in
`benchmarks/phase2/acceptance-v14.toml`:

| Held-out gate | acceptance-v13 | acceptance-v14 | Development basis (21 re-judged families) |
| --- | ---: | ---: | --- |
| Paper nDCG@10 | 0.80 | 0.65 | BM25 0.557; selected 0.717 (q11–q19 0.685); gte dense 0.757 |
| Evidence nDCG@10 | 0.45 | 0.40 | Dense E5 0.364; selected 0.517 (q11–q19 0.414) |
| Evidence direct MRR@10 | 0.45 | 0.45 | selected 0.653 |
| Evidence judged Recall@20 | 0.60 | 0.50 | selected 0.607 |
| Warm p95 | 2,000 ms | 5,000 ms | [ADR-0016](0016-phase2-warm-latency-5000ms.md) |

All other gates are unchanged. The owner also approved a relative check: the selected profile must beat BM25 on paper
and evidence nDCG@10, with the paired family-bootstrap 95% lower bound above 0.

- **Basis.** The thresholds come from development data only. They sit about BM25 + 0.1 and about one sampling width
  (0.05–0.06 at N = 30) below the selected profile's development score.
- **Contamination.** The v13 aggregates were known when these values were chosen. v13 therefore stays failed under
  its own gates, and these values apply only to a set frozen after this decision.
- **Literature.** The literature review found no published absolute threshold for nDCG@10 or MRR@10. Retrieval
  evaluation normally judges systems against baselines on the same collection, with paired significance tests (see
  [threshold literature](../research/phase-2-threshold-literature.md)). The absolute floors here are project-local
  quality guards, not field standards; the relative check follows common IR practice.
- **Other rules.** ADR-0014's other rules stay: the coverage pre-check, composition floors, single run,
  point-estimate judgment with intervals reported, and sealing after the run. A frozen profile change needs its own
  development validation and hosted CI.
- **Failure.** A failure on that set closes the attempt series. The owner then picks option 1 or 4. No further set is
  built by default.

## Label-quality check and the context rule (owner decision, 2026-09-30)

A fresh assistant reviewer re-labelled, blind, the 57 cards of the COIL development question that Codex had audited.

- It agreed with Codex on every direct-evidence (label 2) call, for all 31 passages and 25 papers.
- All 26 disagreements were context (1) against irrelevant (0), with Codex giving the 1. Linear weighted kappa was
  0.45.
- The owner spot-checked three of these disagreements.

The owner decided to keep the existing, more inclusive context rule: **label 1 means useful context or incomplete
support**, as in the evaluation protocol and in the Codex audit. Codex's COIL corrections stand, including the three
ColBERT passages raised from 0 to 1. A stricter rule was briefly adopted and then withdrawn on 2026-09-30.

- Direct-evidence gates (evidence MRR, judged recall, source recall) depend only on label 2 and are robust to this
  choice.
- nDCG gates are sensitive to it: more inclusive context labels raise nDCG for every profile. So no set may mix
  reviewers or rounds that apply different context thresholds, and the reviewer protocol must spell the rule out.
- This check covers one development question. It is not a measured error rate for the full benchmark.

## Consequences

- Phase 2 acceptance tests relative component value and realistic floors instead of the unreached absolute targets.
  The SoT, the acceptance TOML (new version), the evaluation protocol and the acceptance report must change in the
  same change set on acceptance.
- v13 and earlier sets stay spent and are reported under their original gates.
- The q07 extraction-ID defect in `benchmarks/phase2/calibration-v1.toml` is corrected in a tracked follow-up.

## Change-control items (on acceptance)

- SoT §9.4 "Experiments and acceptance" and §21 Phase 2 gate text; header version.
- `benchmarks/phase2/acceptance-v14.toml` (new) and `r8-v14-freeze-v1.toml` template; the runner gains the
  relative gates.
- `docs/plans/phase-2-evaluation-protocol.md`, `phase-2-retrieval-evaluation.md`, `phase-2-agent-handoff.md`, and
  `docs/reference/phase-2-acceptance-report.md`.
