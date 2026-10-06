---
status: proposed
date: 2026-10-06
---

# Phase 4: experiment records, the injection suite and the Phase 4 gate

Proposed on 2026-10-06 after the Phase 4 planning interview, in which the owner chose the
options recorded here ([owner decisions](../reference/phase-4-owner-decisions.md), Q6–Q8,
Q16, Q17). It makes the Phase 4 gate in source-of-truth section 21 checkable, and applies
sections 13.3 (experiment record) and 15.1 (RAG threat model).

## Context

- **Evaluation scripts.** Each phase wrote its own: the Phase 2 benchmarks and acceptance
  runs, the Phase 3 development sweep, and the Phase 3.5 gate. Their results sit in
  `local-reference/` JSON files with different shapes.
- **No comparison.** Nothing compares two research runs or two configurations.
- **Injection cases.** Five scripted prompt-injection cases exist, plus one for malicious
  abstracts. Section 15.1 also names repeated or unauthorized tool calls, exfiltration of
  secrets or unrelated documents, fabricated citation IDs and unbounded recursion.
- **The gate:** "a developer can explain a failed answer from trace evidence and reproduce
  its effective configuration."
- **The real failure to explain.** Phase 3 and 3.5 left one: the `deep_research` planner
  never chooses `discover_papers` on its own.
- **Spent sets.** The Phase 2 held-out sets are spent and must not guide tuning.

## Decision

1. **Experiment records.** Every evaluation run writes one `experiments` row:
   - suite, dataset name, version and SHA-256, code revision;
   - configuration ID and configuration, component versions, random seed, hardware
     profile;
   - metrics and failure counts.

   Per-item results go to `local-reference/experiments/<id>/items.jsonl`, with private
   file permissions.
2. **`research-eval` suites.**

   | Suite | Runs | Notes |
   | --- | --- | --- |
   | `scripted-regression` | the Phase 3 scripted cases | |
   | `agent-dev` | both research modes over the private development tasks | through the API |
   | `retrieval-dev` | the served retrieval profile over the development calibration datasets | development data only |
   | `security-live` | the live model over the synthetic adversarial corpus | below |

   The sealed Phase 2 acceptance scripts and the Phase 3.5 gate scripts stay unchanged as
   historical evidence.
3. **Comparison.** `research-eval compare A B` compares two experiments of the same suite
   and dataset hash. It reports:
   - metric deltas;
   - paired bootstrap 95% intervals over matched items (seeded);
   - configuration differences;
   - for runs, counts by diagnosis stage.
4. **Diagnosis.** `research-runs explain` assigns each run one deterministic stage from its
   run records: `none`, `in_progress`, `model`, `planning`, `retrieval`, `evidence`,
   `generation`, `verification`, `budget`, `ingestion` or `infrastructure`. It adds
   findings such as `planner_never_discovered`, `drafts_rejected`, `failed_check:<name>`
   and `ingestion_wait_cap`. Output carries identifiers, counts and codes, never text.
5. **Reproduction.** `research-runs reproduce` loads the stored configuration, checks that
   it re-hashes to the run's `configuration_id`, rebuilds the inputs, checks that the
   current code rebuilds the same ID, and prints the settings and code revision needed to
   re-run it.
6. **Injection and tool-abuse suite.**
   - **Scripted CI cases.** The adversarial passages are synthetic, and the scripted model
     obeys them. The cases prove the code controls hold for every section 15.1 attack:
     verification, delimiter escaping, the tool allow-list, budgets, filters and secret
     isolation. Further cases cover the API boundary and the Phase 3.5 online surfaces.
   - **`security-live`.** The live model runs the same corpus through fake retrieval. It
     never writes to the live index, and the results are reported, not gated.
7. **The Phase 4 gate.** It passes when all of these hold:
   1. CI: a scripted run produces one connected trace with the required spans and
      attributes. Its logs carry run and trace fields and no question or passage text.
   2. CI: `explain` names the expected stage for each scripted failure category.
   3. CI: `reproduce` recomputes the configuration hash, and a scripted re-run from the
      recovered configuration follows the same tool path with the same ID.
   4. Live, development data: five failed or partial runs from a new instrumented
      `agent-dev` sweep are each attributed to a stage, with cited trace evidence and a
      passing `reproduce`. At least one shows the planner-never-discovers pattern. The
      owner reviews one walkthrough.
   5. CI: the scripted security suite and the authentication, ownership and rate-limit API
      tests pass.

   Answer quality is reported, not gated, as in Phases 3 and 3.5.

## Consequences

- Experiments become comparable across phases only from Phase 4 on. Older results stay in
  their original files. A Phase 3 baseline must be imported once for the first comparison.
- The gate does not require Langfuse.
- A failing security expectation is recorded as a finding and fixed; the test is not
  weakened.
- The planner failure is diagnosed in Phase 4 and fixed later (backlog issue
  [#115](https://github.com/avsngh-git/RAGpipeline/issues/115)).

## Alternatives considered

- **Langfuse datasets and experiments as the store.** They would need Langfuse running and
  would put private questions into it.
- **MLflow.** Another service, with no need the PostgreSQL table does not meet.
- **A test generation in Qdrant for `security-live`.** It writes to the live index and
  makes retrieval nondeterministic, with no gain for measuring the model's behaviour.
- **Gating live answer quality.** Phases 3 and 3.5 showed that the development set is too
  small for a stable quality threshold.
