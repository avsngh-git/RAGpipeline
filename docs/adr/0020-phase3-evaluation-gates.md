---
status: accepted
date: 2026-10-01
---

# Phase 3 evaluation: operational gates on development tasks

Accepted by the project owner on 2026-10-01. This sets the Phase 3 part of open decision
12 (thresholds for answer-generation and end-to-end evaluation).

## Context

- The Phase 3 gate in section 21 of the source of truth is operational: representative
  tasks complete within budgets, invalid evidence IDs are rejected, and failures are
  classifiable.
- The Phase 2 held-out method took most of that phase's effort. A Phase 3 answer-quality
  benchmark would need new labels for generated claims.
- 21 Phase 2 development families survive: 10 calibration families with judgments
  (`calibration-v1.toml`), 9 allowlisted development families (q11–q19 in
  `benchmark-development-questions-v1.toml`), and 2 development-only v13 families with
  judgments in the private backup. The unified re-judged development set was lost in the
  `/tmp` wipe.
- Section 13.4 allows an LLM judge only as a supplement, with model, prompt and variance
  recorded.

## Decision

1. **Gates**, all on the development task set:
   1. 100% of fabricated or unknown evidence handles are rejected (scripted cases);
   2. at least 90% of live runs finish within budget (status `completed`);
   3. 100% of failed runs carry a failure category from the fixed list;
   4. every scripted CI case passes: tool routing (about 10), fabricated handles, budget
      exhaustion, prompt injection (5), resume, and failure categories.
2. **Reported, not gated:** answer outcomes, claim support labels from the judge, claims
   per answer, citations per claim, tool calls and plan rounds per run, model calls,
   latency distribution, and peak memory, each for both modes.
3. **Support judge.** One judge call per answer labels each claim `supported`, `partial`
   or `unsupported` against its cited passages, using a versioned prompt. Unsupported
   claims are dropped from the answer. The judge's model, prompt version and thinking
   setting are recorded. It supplements, and never replaces, the deterministic handle check.
4. **Task set.** P3-16 builds one task per surviving development family (21) into a
   private file under `local-reference/phase3-runs/`. No held-out set is built and
   no Phase 2 held-out set is read.
5. **CI.** CI runs only the scripted-LLM suite. Live evaluation is run manually.

## Consequences

- Phase 3 can pass with weak answers if they are well-formed and bounded; the reported
  quality numbers make that visible for Phase 4.
- Gates 2 and 3 depend on the live model and are run on the laptop, not in CI.

## Alternatives considered

- **A held-out answer benchmark with quality thresholds.** Rejected for Phase 3 because of
  its labeling cost and because the phase gate is operational.
- **No live evaluation.** Rejected: budget and failure behavior depend on the real model.
