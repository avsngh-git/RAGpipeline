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
| P4-12 (#89) | done | see PR | Tracing setup, JSONL and OTLP exporters, all 74 span and attribute names from the card. Agent work found uncommitted in a `/tmp` clone; rescued and reviewed |
| P4-13 (#90) | done | PR #132 | Run root span, node and tool spans, persistence spans, real trace ID in provenance, trace and span IDs in logs; `run_case_detailed` in the regression harness |
| P4-21 (#98) | done | PR #133 | `research-eval run/list/show` and the `scripted-regression` suite (33/33 in a smoke run). Agent work found uncommitted in a `/tmp` clone; rescued and reviewed |
| P4-25 (#102) | done | PR #134 | Migration 026 `api_keys`, `research_runs.principal`, `research-keys` CLI. Agent work found unpushed in a `/tmp` clone; pushed and reviewed |
| P4-14 (#91) | done | batch-3 PR | Generation spans for every model call (Langfuse attributes, input/output only at `full`), synthesize and verify_citations spans. Review: claim counts now recorded at every content level |
| P4-15 (#92) | done | batch-3 PR | Search, eligibility, lexical, dense, fusion, rerank, hydrate, select and citation_lookup spans; rankings unchanged |
| P4-16 (#93) | done | batch-3 PR | Worker request and paper spans, wait-node attributes. Review: tests imported another test module (fails under importlib mode); fixed |
| P4-18 (#95) | done | batch-3 PR | `research-runs explain`: deterministic stages and findings; stage table unchanged from the card. Merge with P4-19 fixed a missing `return` that would have run `prune` after `explain` |
| P4-19 (#96) | done | batch-3 PR | `research-runs reproduce`: hash recompute, rebuild, recipe; scripted re-run test |
| P4-22 (#99) | done | batch-3 PR | `agent-dev` suite over the API, with resume and API-key header |
| P4-23 (#100) | done | batch-3 PR | `retrieval-dev` suite; profile ID as a required option |
| P4-26 (#103) | done | batch-3 PR | Bearer API-key auth; `disabled` only on loopback in development or test. The host API now needs a key or `RESEARCH_PLATFORM_AUTH_MODE=disabled` |
| P4-32 (#109) | done | batch-3 PR | `security-live` suite (8 cases, live model, fake retrieval). Review: the violation test's claim was not grounded in its quote, so it could never detect a violation; fixed |
| P4-17 (#94) | done | P4-17 PR | **Gate item 1 passes in CI:** 10 trace and log contract tests (required spans, one connected tree, root and generation attributes, no text in `ids` mode or logs, run records match the trace, search stage tree) |
| P4-24 (#101) | done | PR #136 | `research-eval compare`: metric deltas, seeded paired bootstrap, configuration differences, stage counts; output confined to `local-reference/` |
| P4-27 (#104) | done | PR #137 | Runs record their principal; another principal gets 404, `admin` reads all; evaluation scripts send `RESEARCH_PLATFORM_API_KEY`. Review: integration tests lacked `mode` and failed in CI; fixed |
| P4-28 (#105) | done | P4-28 PR | In-memory token buckets per key and route class, 2 active runs per key, 64 KiB body limit (413), 429 with `Retry-After`. Agent work found committed in a `/tmp` clone, not pushed |
| P4-31 (#108) | done | PR #147 | 14 API attack tests and two online-ingestion cases (unknown paper refused, from #140; run paper limit). Review: the run-limit case requested 8 papers, which the tool schema (max 5 per call) rejects before the policy, so it failed in CI; now 5 papers against a run limit of 3 |
| P4-20 (#97) | done | PR #128 | Migration 025 `experiments`, `ExperimentRecord`, stores and private item writer. Agent work found unpushed in a `/tmp` worktree; pushed and reviewed |
| P4-30 (#107) | done | PR #129 | Nine scripted §15.1 attack cases; every control held. Agent work found unpushed; review pinned observed status, outcome and tool path so cases cannot pass vacuously |
| P4-37 (#114) | done | PR #130 | `research-maintenance retention`, dry run by default. Agent work found uncommitted in `/tmp`; rescued and reviewed |
| P4-08 (#85) | done | PR #118 | Run fields in JSON logs, run ID context, request ID into the run task, JSON worker logs; merge with P4-03 resolved one import conflict in `runner.py` |
| P4-09 (#86) | done | PR #119 | Metrics module and `/metrics`; HTTP metrics by route template |
| P4-29 (#106) | done | PR #121 | Trivy image and secret scans; seven owner-approved exceptions expire 2026-11-06 (owner decision 4) |
| P4-33 (#110) | reported | local branch `phase4/p4-33-security-live-report` | Three `security-live` runs recorded in the [report](../reference/phase-4-security-live-report.md); findings filed as [#139](https://github.com/avsngh-git/RAGpipeline/issues/139) and [#140](https://github.com/avsngh-git/RAGpipeline/issues/140); report awaits merge |
| P4-34 (#111) | done | P4-34 PR | Imported Phase 3 baseline `49ac1320-64cc-4324-bf0c-e70a673036fc`; resumed and completed all 42 `agent-dev` pairs in `c24d4759-aa3f-4ed6-b5b8-b54c69ae576c`; scripted regression `6e5b11ca-8a77-4f34-ba8f-bfbde713d742` passed 33/33. Candidate: answered 4, partially supported 11, insufficient evidence 27, median 176.45s, p90 284.44s; baseline: 1, 18, 23, median 16.58s, p90 32.95s. Compare: `local-reference/phase4/compare-agent-dev.md`; 42/42 pairs matched. Imported Phase 3 runs lack exact configuration rows; see report's configuration differences. Caveats (review): the baseline's stage counts (41 `generation`) are an artifact of Phase 3 runs having no drafted-claim records, and its configuration differences are inflated by the legacy provenance format; only the candidate's stages (none 4, evidence 17, verification 20, retrieval 1) are meaningful. No question text recorded here |

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
- **Agent worktrees:** agents have worked in `/tmp/ragpipeline-p4-NN` clones whose `origin` is the
  local checkout, and left work uncommitted or unpushed (and in one batch, uncommitted in the
  main checkout on `main`). `/tmp` is not persistent: push each branch to GitHub as soon as it
  has a commit.
- **Private data:** Phase 4 private data goes under `local-reference/phase4/` and
  `local-reference/experiments/`, and traces under `local-reference/traces/`. `/tmp` is not
  persistent.
