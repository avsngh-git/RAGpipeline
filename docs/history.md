# Project history and previous README notes

This document keeps the former README status record and reference material. Current setup instructions live in the linked operations guides; the source of truth remains the project specification.

## Phase 0

Phase 0 learning work is complete. See the [Phase 1 acceptance report](reference/phase-1-100-paper-acceptance-report.md) for the corpus milestone that followed.

## Phase 1

The 100-paper corpus snapshot was accepted after the remediation and audit recorded in the [completion audit](reviews/phase-1-completion-audit-2026-09-26.md) and [acceptance report](reference/phase-1-100-paper-acceptance-report.md). The previous README status record below retains its revision and CI references.

## Phase 2

Phase 2 was accepted on 2026-09-30 after the one-time v14 assessment passed all 16 gates. The selected profile is gte-modernbert-base with BM25S hybrid retrieval and the Ettin-150M reranker; three quality gates passed by narrow margins inside sampling noise, the gates had been lowered after v13 failed, and labels are assistant-reviewed. See the [acceptance report](reference/phase-2-acceptance-report.md) and [benchmark summary](reference/benchmarks.md).

## Phase 3

The owner accepted Phase 3 on 2026-10-03. Its development sweeps measured bounded quick and deep research runs; answer quality remains diagnostic rather than a gate. See the [evaluation report](reference/phase-3-evaluation-report.md) and [failure analysis](reference/failure-analysis.md).

## Phase 4

The owner accepted Phase 4 on 2026-10-11 after five gate items passed, covering trace contracts, run diagnosis and reproduction, live walkthroughs, security, authentication, ownership, and rate limits. See the [gate report](reference/phase-4-gate-report.md).

## Phase 5

The owner accepted Phase 5 on 2026-10-12 after the parity, import-boundary, security, and live-client checks passed. HTTP, agent, and MCP use shared research capabilities. See the [gate report](reference/phase-5-gate-report.md).

## Original project introduction

An installable Python project for a scientific literature research platform.

## Original project status record

## Project status

Phase 0 and the Phase 1 corpus milestone are complete. The accepted 100-paper
snapshot is finalized. Phase 1 remediation passed [hosted CI
36238052340](https://github.com/avsngh-git/RAGpipeline/actions/runs/36238052340)
on revision `d28e1adc299d6199774c78a2d63cb3eb0870d5ab`; see the
[audit closeout](reviews/phase-1-completion-audit-2026-09-26.md) and
[corpus acceptance report](reference/phase-1-100-paper-acceptance-report.md).

**Phase 2 is accepted (2026-09-30).** The one-time R8 v14 held-out assessment (30 families)
passed all 16 gates with frozen profile v10: gte-modernbert-base + BM25S hybrid + Ettin-150M
reranker ([ADR-0017](adr/0017-phase2-accepted-profile-v10.md)). Three quality gates passed by
narrow margins inside sampling noise, the gates were lowered after v13 failed
([ADR-0015](adr/0015-phase2-acceptance-gate-revision.md)), and labels are
assistant-reviewed. See the [current acceptance report](reference/phase-2-acceptance-report.md),
the [handoff](plans/phase-2-agent-handoff.md) and the
[evaluation protocol](plans/phase-2-evaluation-protocol.md).

**Phase 3 was accepted by the owner on 2026-10-03** ([owner acceptance record](https://github.com/avsngh-git/RAGpipeline/issues/18#issuecomment-5972350487)). P3-17 merged as
PR #41; exact main CI run [37144867835](https://github.com/avsngh-git/RAGpipeline/actions/runs/37144867835)
passed on revision `f2cd0954a940d04c418d2607a98c79fc009b96be`. The live development report
covers `quick` and `deep_research`, and the local run guide shows how to submit and inspect
either mode: [evaluation report](reference/phase-3-evaluation-report.md),
[Phase 3 run operations](operations/phase-3-generator.md).


## Previous README reference material

The following sections were moved out of the front page. For current procedures, use the linked guides.

## Research runs

The API starts asynchronous research runs with `POST /v1/research` and returns a `run_id`.
Set `mode` to `quick` or `deep_research`; poll `GET /v1/research/{run_id}` or use
`research-runs show RUN_ID` to inspect status and the structured answer. Follow the
[Phase 3 operations guide](operations/phase-3-generator.md) to start the local API,
retrieval services and generator.

```json
{
  "question": "Which retrieval methods improve evidence ranking?",
  "mode": "deep_research"
}
```

The response includes claims, evidence handles and paper metadata. Passage text and live
evaluation inputs remain private local data.


## MCP server

The MCP server exposes selected research tools over the local API at `/mcp/` using Streamable HTTP.
See the [MCP operations guide](operations/mcp.md) for keys, clients and the Inspector check.
The adapter and its security decisions are documented in [ADR-0030](adr/0030-phase5-mcp-adapter.md).


## Development environment

This project uses Conda as its development dependency manager.

Create the environment from the human-maintained specification:

```bash
conda env create --file environment.yaml
conda activate sci_research_agent
python -m pip install --no-build-isolation --no-deps -e .
```

The editable installation makes the local `src/` package importable while
keeping source changes immediately available to the environment.

Run the project checks from the repository root:

```bash
python -m ruff check .
python -m ruff format --check .
python -m mypy
python -m pytest
```

The integration tests skip unless RESEARCH_PLATFORM_TEST_DATABASE_URL and
RESEARCH_PLATFORM_TEST_QDRANT_URL point to disposable services. The
PostgreSQL URL must use a dedicated database named research_test; tests apply
migrations and enforce constraints. The Qdrant test creates and removes a
temporary collection. CI supplies fresh service containers for these tests.


## Locked Linux environment

`environment-linux-64.lock` is the slim test and development environment;
`environment-serving-linux-64.lock` is the CPU inference environment used by the
Docker image. See [the serving environment guide](operations/serving-environment.md)
for its model dependencies and regeneration procedure.

`environment-linux-64.lock` is an exact Conda package lock for Linux x86-64.
Use it when reproducing the currently tested Linux environment:

```bash
conda create \
  --name sci_research_agent_linux \
  --file environment-linux-64.lock

conda run -n sci_research_agent_linux \
  python -m pip install --no-deps --require-hashes -r requirements-bm25s.txt

conda run -n sci_research_agent_linux \
  python -m pip install --no-deps --require-hashes -r requirements-langgraph.txt

conda run -n sci_research_agent_linux \
  python -m pip install --no-build-isolation --no-deps -e .
```

The lock file contains exact Conda packages, not PyPI distributions. The
BM25S and LangGraph PostgreSQL checkpoint runtime wheels are separately
version- and hash-pinned in `requirements-bm25s.txt` and
`requirements-langgraph.txt`; install both before the local package. Conda
provides their runtime dependencies, including NumPy 2.5.3 for BM25S.


## Application configuration

`research_platform.config.Settings` reads configuration from process
environment variables and validates it when a settings object is created.
Supported variables are:

- `RESEARCH_PLATFORM_ENVIRONMENT`: `development`, `test`, or `production`.
- `RESEARCH_PLATFORM_LOG_LEVEL`: `DEBUG`, `INFO`, `WARNING`, `ERROR`, or
  `CRITICAL`.
- `RESEARCH_PLATFORM_DATABASE_URL`: a PostgreSQL connection URL.
- `RESEARCH_PLATFORM_QDRANT_URL`: an HTTP or HTTPS Qdrant URL.
- `RESEARCH_PLATFORM_DEPENDENCY_TIMEOUT_SECONDS`: positive timeout for readiness
  checks.
- `OPENALEX_API_KEY`: secret used by explicitly invoked discovery/acquisition
  commands; it is never part of the serialized ingestion configuration.

`.env.example` documents safe local-development values. It is not loaded
automatically by the standard library configuration code; copy it to `.env`
and export those values in the shell, or provide the variables through Docker
Compose. `.env` is ignored by Git and must contain any real credentials.

Invalid values raise `ValueError` during `Settings()` construction so an
application fails at startup with a clear configuration error.


## Run the API

Start the development server with Uvicorn:

```bash
python -m uvicorn research_platform.api:create_app \
  --factory \
  --reload
```

Check process liveness:

```bash
curl http://127.0.0.1:8000/health
```

Expected response:

```json
{"status":"ok"}
```


## Logging and errors

The API assigns every HTTP request an `X-Request-ID`. A caller-provided ID is
preserved when it is non-empty and reasonably bounded; otherwise the API
generates a UUID. The ID is returned in response headers and error bodies, and
is attached to request logs.

Application logs are emitted as JSON with timestamps, levels, logger names,
request IDs, and safe HTTP metadata. Expected failures can raise `AppError`
and return a structured response containing an error code, message, and
request ID. Unexpected failures return a generic `internal_error` response.
Exception diagnostics retain the exception type and frame locations while
omitting exception messages and traceback source text.


## Local services and migrations

Start PostgreSQL, Qdrant, and the API together:

```bash
docker compose up --build
```

The services use named volumes so ordinary restarts preserve local data.
Verify liveness and dependency readiness separately:

```bash
curl http://127.0.0.1:8000/health
curl -i http://127.0.0.1:8000/ready
```

Apply the versioned PostgreSQL schema from the host environment:

```bash
conda activate sci_research_agent
python scripts/migrate.py
```

The migration runner records applied versions in `schema_migrations` and is
safe to run again. The Qdrant index remains a derived store and is not part
of the relational migration.



## Environment files

- `environment.yaml` is the human-maintained Conda environment definition.
- `environment-linux-64.lock` records exact package builds for Linux x86-64.
- `pyproject.toml` defines the Python package and configures build, linting,
  type checking, and testing tools.

The YAML specification is the normal starting point for a new development
environment. The Linux x86-64 lock is consumed by GitHub Actions and the Docker
image, so the tested CI environment and container runtime use the same exact
Conda packages. The image installs the local project with dependency resolution
disabled; its runtime dependencies come from that lock. Regenerate the lock
after deliberate environment changes.


