# 14. Development

This chapter is for contributors. It covers the code layout, testing, CI and how changes and decisions are made. Set up the environment first ([Getting started](02-getting-started.md#development-environment)).

## Code layout

The package lives in `src/research_platform/`. Dependencies point downwards: interfaces → application services → domain logic → adapters.

| Package | Role | Key modules |
| --- | --- | --- |
| `api/` | FastAPI app, routes, authentication, rate limits, body limits, error envelope, static web page | `app.py`, `routes.py`, `research_routes.py`, `ingestion_routes.py`, `auth.py` |
| `mcp/` | MCP adapter mounted at `/mcp`; tools and resources over `ResearchCapabilities` | `server.py`, `mount.py`, `search_tools.py`, `paper_tools.py`, `run_tools.py` |
| `services/` | Shared use cases for HTTP and MCP: deadlines, error mapping, snapshot checks, text exposure, readiness | `capabilities.py`, `text_exposure.py`, `readiness.py` |
| `agents/` | LangGraph graphs, nodes, prompts, typed actions, evidence packing, synthesis and quote verification | `graph_quick.py`, `graph_deep.py`, `answering.py`, `verification.py`, `prompts.py` |
| `tools/` | `ResearchTools`: validated, budgeted tool execution for the agent | `research_tools.py` |
| `runs/` | Run contracts, executor, runner, repository, checkpointing, diagnosis, reproduction, CLI | `contracts.py`, `executor.py`, `runner.py`, `diagnosis.py`, `reproduce.py` |
| `search/` | Retrieval: profiles, lexical analyzer, sparse and dense search, fusion, reranker, selection and budgets, paper reads, citation graph | `application.py`, `hybrid_search.py`, `fusion.py`, `reranker.py`, `generation_search.py` |
| `ingestion/` | Discovery, manifests, acquisition, permissions, Docling extraction, chunking, snapshots, jobs, generations, online ingestion, CLI | `cli.py`, `pdf_extraction.py`, `snapshots.py`, `generation_*.py`, `online_ingestion.py` |
| `discovery/` | Online OpenAlex discovery for runs | `online.py` |
| `worker/` | Ingestion queue worker | `main.py`, `handlers.py` |
| `llm/` | Model adapter interface, Ollama client, scripted fake, call recording | `contracts.py`, `ollama.py`, `scripted.py` |
| `evaluation/` | Experiment records, suites, metrics, statistics, comparison, CLI | `cli.py`, `experiments.py`, `scoring.py`, `statistics.py`, `suites/` |
| `observability/` | Tracing with content levels, JSON logging, request context, metrics | `tracing.py`, `content.py`, `metrics.py` |
| `auth/` | API key hashing and the `research-keys` CLI | `keys.py`, `cli.py` |
| `demo/` | Demo bundle export and load, model fetch | `bundle.py`, `database.py`, `qdrant.py`, `cli.py` |
| `persistence/` | Migration runner | `migrations.py` |
| `maintenance/` | Retention | `retention.py` |
| `config.py` | Validated settings | |

Other top-level directories:

| Path | Contents |
| --- | --- |
| `migrations/` | Forward-only SQL migrations 001–028 |
| `tests/` | Unit and API tests at the top level; `integration/` for live services; `security/` for attack suites |
| `benchmarks/` | Frozen retrieval profiles, acceptance configurations, scripted regression cases |
| `configs/` | Versioned JSON configurations and Ollama model files |
| `scripts/` | Demo loader and smoke test, migration wrapper, evaluation and acceptance scripts from each phase |
| `docs/` | This guide, ADRs, operations guides, reports, plans and the specification |
| `local-reference/`, `manifests/`, `data/` | Git-ignored private data: review files, indexes, model caches, artifacts, run outputs |

### Architectural rules enforced by tests

- Routes, LangGraph nodes and MCP handlers contain no SQL, Qdrant queries or ranking logic.
- The MCP adapter and `ResearchCapabilities` must not import database, vector store, ranking or agent modules ([`test_phase5_gate_import_boundary.py`](../../tests/test_phase5_gate_import_boundary.py)).
- MCP, HTTP and agent tools return the same results on the same fixtures ([`test_phase5_gate_parity.py`](../../tests/test_phase5_gate_parity.py)).
- Prompt texts have pinned fingerprints (`tests/prompt_fingerprints.json`), so a prompt change is always deliberate and visible in review.
- The checkpoint allow-list matches the run state's types (`test_checkpoint_allowlist.py`).

## Tests

| Kind | Where | Needs |
| --- | --- | --- |
| Unit and API | `tests/test_*.py` (about 150 files) | Nothing; models, LLM and services are faked |
| Integration | `tests/integration/` | `RESEARCH_PLATFORM_TEST_DATABASE_URL` (a database named `research_test`) and `RESEARCH_PLATFORM_TEST_QDRANT_URL`; skipped otherwise |
| Security | `tests/security/` | Nothing |
| Scripted regression | `research-eval run scripted-regression` and its CI test | Nothing |
| Live evaluation | `research-eval` suites `retrieval-dev`, `agent-dev`, `security-live` | Models, GPU and private datasets; never in CI |

Conventions:

- Tests must not depend on a developer's local data. Integration tests create their own state in disposable services.
- Nondeterministic model behaviour stays out of blocking CI; CI uses the scripted LLM fake (`llm/scripted.py`).
- New integration modules for a phase are named `test_phaseN_*.py`.

## Continuous integration

[`.github/workflows/ci.yml`](../../.github/workflows/ci.yml) runs on every pull request and every push to `main`:

1. create the exact Conda environment from `environment-linux-64.lock` and install the hash-pinned wheels;
2. `ruff check` and `ruff format --check`;
3. `mypy` in strict mode over `src/research_platform`;
4. `pytest` with PostgreSQL 16 and Qdrant 1.19.1 service containers;
5. apply all migrations to a clean database;
6. `pip check` and `pip-audit`;
7. build the Docker image;
8. Trivy image scan (HIGH and CRITICAL, unfixed ignored, exceptions in `.trivyignore`) and Trivy secret scan;
9. on `main` only, push the image to GHCR as `sha-<12 characters>`.

[`release.yml`](../../.github/workflows/release.yml) and [`demo-smoke.yml`](../../.github/workflows/demo-smoke.yml) are described in [Operations](13-operations.md#release-flow). GPU and model evaluations never run in CI.

## Environments

| File | Used for |
| --- | --- |
| `environment.yaml` | Human-maintained starting point for development |
| `environment-linux-64.lock` | Exact CI and test environment, without PyTorch |
| `environment-serving.yaml` and `environment-serving-linux-64.lock` | The image's CPU inference environment, with PyTorch, transformers and sentence-transformers |
| `requirements-bm25s.txt`, `requirements-langgraph.txt`, `requirements-serving.txt` | Hash-pinned wheels not available from conda-forge |
| `pyproject.toml` extras `pdf`, `embeddings`, `pdf-vlm` | Optional local dependencies for extraction and models |

Regenerate a lock only after a deliberate environment change; see the [serving environment guide](../operations/serving-environment.md).

## Style

- Python 3.12, `src/` layout, Ruff for linting and formatting (line length 88), strict mypy.
- Typed contracts everywhere: Pydantic models with `extra="forbid"` at boundaries, frozen dataclasses inside.
- Errors at boundaries are `AppError` with a stable code. Never expose exception text.
- Logs and traces never carry passage or prompt text below the `full` trace level.
- Match the surrounding code's naming and comment density.

## How changes are decided

The [project specification](../agents/scientific-research-platform-source-of-truth.md) is the authority. It marks decisions as **LOCKED** (change only through the decision process) or **OPEN**.

- A material change to scope, architecture, core technology, public API, data model, evaluation contract, deployment or security needs a short **ADR** in [`docs/adr/`](../adr/) (context, decision, alternatives, consequences). It also needs the owner's approval if it alters a LOCKED decision, and an update to the specification in the same change.
- Changing a retrieval model or ranking setting needs new development evidence **and** a fresh held-out set. Spent held-out sets cannot be reused for tuning.
- Work is tracked in [GitHub Issues](https://github.com/avsngh-git/RAGpipeline/issues): one card per pull request, a branch named after the card, and `Closes #N` in the pull request. See [`docs/agents/issue-tracker.md`](../agents/issue-tracker.md).
- Domain vocabulary lives in [`CONTEXT.md`](../../CONTEXT.md). Use its terms, and add new ones there.

Before a material contribution, answer the specification's [agent operating checklist](../agents/scientific-research-platform-source-of-truth.md#24-agent-operating-checklist). Which phase does it serve? Does it duplicate logic across API, LangGraph and MCP? What tests prove it? What telemetry makes it diagnosable? Can it run in the small profile?

## Private data

Questions, answers, passages from non-public documents, development labels and run outputs are private. They live under git-ignored `local-reference/` and `manifests/`, never in commits, issues or public logs. Keep the checkout outside the system temporary directory; one evaluation script refuses to run there to protect this data.
