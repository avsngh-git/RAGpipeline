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
| P4-01 (#78) | done | branch `phase4/p4-01-adrs` | ADRs 0026–0028 accepted 2026-10-06; plan, handoff, owner decisions, source of truth 1.39 |

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
- **Private data:** Phase 4 private data goes under `local-reference/phase4/` and
  `local-reference/experiments/`, and traces under `local-reference/traces/`. `/tmp` is not
  persistent.
