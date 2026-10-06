# Phase 4 — Observability, LLMOps and security

Status: planned on 2026-10-06; ADRs accepted by the owner on 2026-10-06. The decisions are in
three ADRs:

- [ADR-0026](../adr/0026-phase4-observability-and-run-records.md): tracing, content levels,
  run records, provenance version 2, metrics, retention.
- [ADR-0027](../adr/0027-phase4-authentication-and-rate-limits.md): API keys, run ownership,
  rate limits, scanning.
- [ADR-0028](../adr/0028-phase4-experiment-records-and-gate.md): experiment records,
  `research-eval`, diagnosis and reproduction, the injection suite, the gate.

The owner's interview answers are in the [owner decisions](../reference/phase-4-owner-decisions.md);
the [handoff](phase-4-agent-handoff.md) records card progress. Section 21 of the
[source of truth](../agents/scientific-research-platform-source-of-truth.md) records the phase.

## Goal

A developer can explain a failed answer from trace evidence and reproduce its effective
configuration (section 21 gate). The other Phase 4 deliverables:

- traces, logs and metrics;
- prompt, model and configuration provenance;
- an experiment comparison workflow;
- an authentication and rate-limit baseline;
- a prompt-injection and tool-abuse suite.

## Gate

Defined in ADR-0028 decision 7:

1. A CI trace and log contract test (P4-17).
2. CI: `research-runs explain` names the stage of each scripted failure (P4-18).
3. CI: `research-runs reproduce` recomputes the hash, and a scripted re-run follows the same
   tool path (P4-19).
4. Live, development data: five failure walkthroughs from trace evidence, including the
   planner-never-discovers case; the owner reviews one (P4-35).
5. CI: the security suite and the auth, ownership and rate-limit tests (P4-26 to P4-28,
   P4-30, P4-31).

Answer quality is reported, not gated.

## How the work is organized

- Map issue [#77](https://github.com/avsngh-git/RAGpipeline/issues/77) holds the card table,
  the decisions and the open questions. The cards are issues
  [#78](https://github.com/avsngh-git/RAGpipeline/issues/78) to
  [#114](https://github.com/avsngh-git/RAGpipeline/issues/114). P4-01 to P4-36 are #78 to #113
  in order, and P4-37 is #114.
- **Implementers:**
  - `ready-for-agent` cards are written for Codex Luna agents working alone and in
    parallel. Each card has its rules, exact files and signatures, numbered steps, named
    tests and a done list;
  - `ready-for-human` cards need live services, private data or the owner.
- **Workflow:**
  - one branch (`phase4/p4-NN-short-name`) and one pull request per card;
  - the planning session reviews each pull request before merge;
  - blockers keep cards that edit the same functions in sequence.
- **Migrations** are pre-numbered:

  | Migration | Card |
  | --- | --- |
  | 022 `run_configurations` | P4-04 |
  | 023 `llm_calls` | P4-05 |
  | 024 `draft_claims` | P4-07 |
  | 025 `experiments` | P4-20 |
  | 026 `api_keys` | P4-25 |

- **Live data:** agent cards never touch `research_phase1_review`, live Qdrant or Ollama.

| Card | Issue | Type | Delivers | Blocked by |
| --- | --- | --- | --- | --- |
| P4-01 | #78 | human | ADRs, plan, handoff, owner decisions | — |
| P4-02 | #79 | human | Langfuse memory spike, pins, new dependencies | P4-01 |
| P4-03 | #80 | agent | Provenance version 2 | P4-01 |
| P4-04 | #81 | agent | Migration 022 `run_configurations` | P4-03 |
| P4-05 | #82 | agent | Migration 023 `llm_calls`, payloads | P4-04 |
| P4-06 | #83 | agent | Recording every model call | P4-05 |
| P4-07 | #84 | agent | Migration 024 drafted claims | P4-05 |
| P4-08 | #85 | agent | Structured run and worker logging | P4-01 |
| P4-09 | #86 | agent | Metrics module and `/metrics` | P4-02 |
| P4-10 | #87 | agent | Domain metrics, worker metrics port | P4-06, P4-07, P4-08, P4-09 |
| P4-11 | #88 | agent | Compose `observability` profile | P4-02, P4-09 |
| P4-12 | #89 | agent | OpenTelemetry setup | P4-02, P4-03 |
| P4-13 | #90 | agent | Run, node and tool spans | P4-08, P4-10, P4-12 |
| P4-14 | #91 | agent | Generation, synthesis and verification spans | P4-13 |
| P4-15 | #92 | agent | Retrieval and citation spans | P4-13 |
| P4-16 | #93 | agent | Worker and wait spans | P4-13 |
| P4-17 | #94 | agent | Gate 1: trace and log contract | P4-08, P4-14, P4-15 |
| P4-18 | #95 | agent | Gate 2: `explain` | P4-06, P4-07, P4-13 |
| P4-19 | #96 | agent | Gate 3: `reproduce` | P4-04, P4-13 |
| P4-20 | #97 | agent | Migration 025 experiments | P4-07 |
| P4-21 | #98 | agent | `research-eval` and `scripted-regression` | P4-20 |
| P4-22 | #99 | agent | `agent-dev` suite | P4-21 |
| P4-23 | #100 | agent | `retrieval-dev` suite | P4-21 |
| P4-24 | #101 | agent | `research-eval compare` | P4-18, P4-21 |
| P4-25 | #102 | agent | Migration 026 API keys | P4-20 |
| P4-26 | #103 | agent | Bearer authentication | P4-09, P4-25 |
| P4-27 | #104 | agent | Run ownership | P4-26 |
| P4-28 | #105 | agent | Rate limits and body limit | P4-09, P4-27 |
| P4-29 | #106 | agent | Trivy scanning | P4-02 |
| P4-30 | #107 | agent | Security suite 1 | P4-01 |
| P4-31 | #108 | agent | Security suite 2 | P4-27, P4-28, P4-30 |
| P4-32 | #109 | agent | `security-live` suite | P4-21, P4-30 |
| P4-33 | #110 | human | Run `security-live` | P4-32 |
| P4-34 | #111 | human | Instrumented development sweep | P4-11, P4-17, P4-22, P4-24, P4-27, P4-37 |
| P4-35 | #112 | human | Gate 4: walkthroughs, planner diagnosis | P4-18, P4-19, P4-34 |
| P4-36 | #113 | human | Closeout | all |
| P4-37 | #114 | agent | `research-maintenance retention` | P4-05 |

## Risks and fallbacks

| Risk | Detection | Response |
| --- | --- | --- |
| Langfuse v4 does not fit beside a live run in 11 GiB | P4-02 memory measurement | Run Langfuse only in diagnosis sessions; the JSONL traces and PostgreSQL records still serve the gate |
| OpenTelemetry context does not cross LangGraph node tasks | P4-13 tests | Pass the parent span context explicitly into node wrappers; record the finding |
| Parallel cards conflict in shared files | Pull request review | Blockers sequence cards that edit the same functions; the reviewer resolves list conflicts |
| The first Trivy scan finds fixable HIGH/CRITICAL issues | P4-29 CI | The owner decides between upgrading and a dated `.trivyignore` entry |
| A security case exposes a real control gap | P4-30, P4-31 | Record a finding and fix it in code; never weaken the test |
| A provenance change fails resumed runs with `configuration_changed` | P4-03 | Expected for runs started before the change; drain the queue before deploying |

## Not in Phase 4

- MCP (Phase 5);
- deployment, a UI and Grafana (Phase 6);
- fixing the planner, the `answered` definition, the flagged-table policy, configuration
  drift migration, the worker image and the dense tie-breaker (backlog
  [#115](https://github.com/avsngh-git/RAGpipeline/issues/115));
- changes to retrieval models or rankings;
- answer-quality gates.
