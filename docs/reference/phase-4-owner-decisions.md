# Phase 4 owner decisions

**Status:** record of the owner's judgement calls during Phase 4, kept for later analysis.
Each entry gives the date, what was decided, the evidence it rested on, the alternatives
set aside, and what to re-examine later. Decisions delegated to the assistant are listed
separately at the end.

## Owner decisions

### 1. Planning interview (2026-10-06)

The owner answered 19 questions and accepted the assistant's recommendation on each.
ADRs 0026–0028 record the resulting design; map issue
[#77](https://github.com/avsngh-git/RAGpipeline/issues/77) lists the cards.

Evidence available at the time:
- **Code inventory:**
  - the log formatter drops run fields;
  - prompts, outputs and drafted claims are not persisted;
  - `configuration_id` hashes prompt version labels, not prompt text;
  - there is no tracing, metrics, authentication, rate limiting or container scanning;
  - five scripted injection cases exist.
- **Langfuse v4 documentation:** six services, with 4 cores and 16 GiB recommended.
- **The machine:** an 11 GiB WSL VM.

| # | Topic | Decision | Alternatives set aside |
| --- | --- | --- | --- |
| Q1 | Scope | The five section 21 deliverables, plus the Phase 3/3.5 inputs that fit the theme: logging gap, persisted drafts, retention, more injection cases. The planner-never-discovers failure is diagnosed as the gate example, not fixed | Core only; everything including agent-quality fixes |
| Q2 | Tracing | OpenTelemetry API only. JSONL file always, Langfuse v4 opt-in over OTLP, in-memory in tests. PostgreSQL authoritative | Langfuse SDK directly; Jaeger/Tempo as main viewer |
| Q3 | Content | Logs never text. Traces `none`/`ids`/`full`, `full` in development, `ids` elsewhere | Never store text anywhere |
| Q4 | Metrics | `prometheus-client` `/metrics`, Prometheus in the profile, no Grafana | Grafana dashboard; OTLP metrics |
| Q5 | Authentication | Hashed API keys with scopes, CLI-managed, Bearer; disabled only on loopback | One static token; OAuth/OIDC |
| Q6 | Experiments | `ExperimentRecord` in PostgreSQL, items in `local-reference/`, `research-eval compare` | Langfuse datasets; MLflow |
| Q7 | Gate | CI contract, `explain`, `reproduce`, security tests; five live walkthroughs reviewed by the owner | — |
| Q8 | Injection suite | Scripted CI cases for every section 15.1 attack plus a live suite, reported | Scripted only |
| Q9 | Workflow | Cards of about 100–300 lines, one pull request each, reviewed before merge; ADRs first | One shared branch |
| Q10 | Rate limits | In-memory token buckets per key and route class, 2 active runs per key, 64 KiB body, 429 with `Retry-After` | — |
| Q11 | Ownership | Runs belong to a principal; others get 404; `admin` sees all; old runs are `legacy-local` | — |
| Q12 | Provenance v2 | Prompt text fingerprints, tool digest, decoding settings, timeouts, generation configuration; `run_configurations`; version-bump CI test | — |
| Q13 | Model-call text | Stored in PostgreSQL at `full` as well as in traces, so `explain` works with Langfuse off. The owner first asked why Langfuse is needed if PostgreSQL holds the calls. Answer: PostgreSQL holds what happened; traces hold the timing tree and the interactive viewer, and the spec locks Langfuse-compatible tracing | Text only in traces; drop Langfuse (needs a LOCKED change) |
| Q14 | Retention | Checkpoints 7 days after completion and 30 after failure, payloads 90 days, retired points when unreadable; manual `--apply` | — |
| Q15 | Scanning | Trivy image and secret scans; `.trivyignore` with reason and expiry | — |
| Q16 | Suites | `scripted-regression`, `agent-dev`, `retrieval-dev`, `security-live`; sealed scripts unchanged | — |
| Q17 | Live sample | A new instrumented `agent-dev` sweep supplies five walkthroughs | Reuse Phase 3 runs (they have no traces) |
| Q18 | Deferred items | One backlog issue, [#115](https://github.com/avsngh-git/RAGpipeline/issues/115) | — |
| Q19 | Parallelism | Codex Luna agents run cards in parallel when blockers allow | Strictly sequential |

**Re-examine:**
- Q2/Q13 if the P4-02 spike shows Langfuse cannot run beside live sweeps;
- Q10 when Phase 6 deploys more than one API process.

### 2. Implementers (2026-10-06)

- **Decision:** cards must be simple enough for Codex Luna agents to implement alone,
  without planning by a larger model. The planning session writes the cards, implements
  P4-01 itself, and then stops.
- **Consequence:** every agent card carries its own rules, exact signatures, numbered steps,
  test names and a "stop and ask" list. Cards never touch live data.

## Decisions delegated to the assistant

- **`security-live` uses fake retrieval** (ADR-0028 decision 6): the synthetic adversarial
  corpus goes through fake retrieval services rather than a test generation in Qdrant. This
  avoids writes to the live index and keeps retrieval deterministic.
- **Retention reports, but does not delete, points of failed or unpublished generations**
  (ADR-0026 decision 6). Deleting them safely needs generation-numbering rules; the item is
  on [#115](https://github.com/avsngh-git/RAGpipeline/issues/115).
- **A resumed run starts a new trace with the same `langfuse.session.id`**, instead of a
  span link to the earlier trace.
- **Card P4-37** (`research-maintenance retention`, #114) was added after the owner
  confirmed the card list, because Q14 had no card.
- **Extra blockers**, so parallel cards do not edit the same functions: P4-13 on P4-08 and
  P4-10; P4-19 on P4-13; P4-26 on P4-09; P4-28 on P4-27 and P4-09; P4-34 on P4-37.
- **`retrieval-dev`** takes the retrieval profile ID as a required option, because the
  search contract requires it explicitly.
