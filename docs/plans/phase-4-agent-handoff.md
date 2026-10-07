# Phase 4 — Agent handoff

Updated: 2026-10-06. **Status: ADRs 0026–0028 accepted by the owner on 2026-10-06; implementation open.**
The [plan](phase-4-observability-security.md) and map issue
[#77](https://github.com/avsngh-git/RAGpipeline/issues/77) define the cards; the
[owner decisions](../reference/phase-4-owner-decisions.md) record the interview.

## How work is picked up

- Each card is a GitHub issue labelled `wayfinder:task`, plus `ready-for-agent` or
  `ready-for-human`, under map issue #77. P4-01 to P4-36 are #78 to #113, and P4-37 is #114.
- Cards run in parallel. Pick any open, unassigned card whose "Blocked by" issues are
  closed, and claim it with `gh issue edit <n> --add-assignee @me`.
- Each card holds its own rules: the branch is `phase4/p4-NN-short-name`, with one pull
  request per card containing `Closes #<issue>`.
- 2026-10-06: the owner asked that agent cards be implemented by Codex Luna agents working
  alone from the card text, with no planning help from a larger model. The planning
  session reviews each pull request before merge.

## Progress

| Card | State | Commit / PR | Notes |
| --- | --- | --- | --- |
| P4-01 (#78) | done | PR #116 | ADRs 0026–0028 accepted 2026-10-06; plan, handoff, owner decisions, source of truth 1.39 |
| P4-02 (#79) | done | PR #117 | OpenTelemetry 1.45.0 and prometheus_client 0.26.0 in the lock; pins, Prometheus networking (bridge + `host.docker.internal`), memory (with Langfuse: peak 9,650 MiB used, 2,314 MiB available) and rendering in the [spike report](../reference/phase-4-langfuse-spike.md) |
| P4-03 (#80) | done | PR #120 | Provenance version 2; golden `tests/prompt_fingerprints.json` |
| P4-04 (#81) | done | PR #122 | Migration 022 `run_configurations`; the runner saves each effective configuration (planning session) |
| P4-05 (#82) | done | PR #123 | Migration 023 `llm_calls` and `llm_call_payloads`; `append_llm_call` / `list_llm_calls` (planning session) |
| P4-06 (#83) | done | PR #124 | `RecordingLLMClient` records every model call; payloads only at trace content `full` (planning session) |
| P4-07 (#84) | done | PR #125 | Migration 024 `draft_claims` and `research_runs.synthesis`; verdicts per drafted claim. Also added `ClaimVerdict`, `DraftClaimOutcome` and `SynthesisSummary` to the checkpoint serializer allow-list (not in the card) (planning session) |
| P4-10 (#87) | done | PR #126 | Domain metrics for runs, tools, model calls, search stages and the worker (port 9101) |
| P4-11 (#88) | done | PR #127 | Prometheus and Langfuse v4 in `docker-compose.observability.yml` (used with `-f`), not in `docker-compose.yml`: Compose interpolates required `${VAR:?}` secrets in every service, which broke plain `docker compose up`. Fixed in review |
| P4-20 (#97) | done | PR #128 | Migration 025 `experiments`, `ExperimentRecord`, stores and private item writer. Agent work found unpushed in a `/tmp` worktree; pushed and reviewed |
| P4-30 (#107) | done | PR #129 | Nine scripted §15.1 attack cases; every control held. Agent work found unpushed; review pinned observed status, outcome and tool path so cases cannot pass vacuously |
| P4-37 (#114) | done | PR #130 | `research-maintenance retention`, dry run by default. Agent work found uncommitted in `/tmp`; rescued and reviewed |
| P4-08 (#85) | done | PR #118 | Run fields in JSON logs, run ID context, request ID into the run task, JSON worker logs; merge with P4-03 resolved one import conflict in `runner.py` |
| P4-09 (#86) | done | PR #119 | Metrics module and `/metrics`; HTTP metrics by route template |
| P4-29 (#106) | done | PR #121 | Trivy image and secret scans; seven owner-approved exceptions expire 2026-11-06 (owner decision 4) |

## Environment facts

- **Machine:** the WSL VM has 11 GiB of RAM (about 6.7 GiB available with the usual
  services), 12 CPUs and an RTX 3050 Laptop GPU with 4 GiB.
- **Langfuse:** self-hosted Langfuse is v4 and recommends 4 cores and 16 GiB. It accepts
  OTLP/HTTP at `/api/public/otel/v1/traces`, with Basic auth from the project keys and
  `x-langfuse-ingestion-version: 4`.
- **Dependencies:** they come from the exact Conda lock `environment-linux-64.lock`. P4-02
  adds `opentelemetry-api`, `opentelemetry-sdk`, `opentelemetry-exporter-otlp-proto-http`
  and `prometheus_client` once, so no implementer card touches the lock.
- **Integration tests:** modules run in name order, and new ones are named
  `test_phase4_*.py`. Each new migration is added to the expected list in
  `tests/integration/test_live_services.py`.
- **Live services:** the host API serves on `127.0.0.1:8001` from the Conda environment
  `sci_research_agent`, and `research-worker` runs on the host. Research runs use the
  database `research_phase1_review`, which has migrations through 021.
- **Agent worktrees:** agents have worked in `/tmp/ragpipeline-p4-NN` worktrees and left work
  unpushed. `/tmp` is not persistent: push each branch as soon as it has a commit.
- **Private data:** Phase 4 private data goes under `local-reference/phase4/` and
  `local-reference/experiments/`, and traces under `local-reference/traces/`. `/tmp` is not
  persistent.
