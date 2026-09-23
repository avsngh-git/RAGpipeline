# Phase 0 — Learning checklist and handoff

Updated: 2026-09-22. Resume at Phase 0 gate verification: migration, persistence, and CI.

## Working agreement

The user is learning Python by implementing this project personally. Act as a
tutor and reviewer: explain the next small task, let the user attempt it, then
review and help debug. Write application code or perform implementation steps
only when explicitly asked. A request to move on means advance the lesson, not
implement the remaining phase automatically.

Keep explanations concise, define unfamiliar terms, and explain why commands
and configuration exist. Prefer one exercise at a time. The user wants Luna for
routine learning work to reduce token use; this document enables a new session
to continue without replaying the conversation. It does not change model settings.

Read the [source of truth](../agents/scientific-research-platform-source-of-truth.md)
as required by AGENTS.md. Phase 0's gate is a clean checkout that runs tests and
starts baseline services from documented commands. The [Phase 1 plan](phase-1-corpus-ingestion.md)
is already approved; its implementation follows the foundations below.

## Phase 0 checklist

| Task | What the user implements | What they learn | Done when |
| --- | --- | --- | --- |
| 1. Python package | `pyproject.toml`, `src/research_platform/`, isolated environment and editable installation | Packages, imports, environments, dependencies | Package imports from outside the repository in the intended environment |
| 2. Development checks | Ruff, mypy, pytest configuration; documented dependency locking | Formatting, static analysis, repeatable environments | Checks run through documented commands and dependencies can be recreated |
| 3. Typed configuration | Validated environment settings and `.env.example` | Types, validation, defaults, configuration boundaries | Valid settings load; invalid values produce useful errors; secrets remain outside Git |
| 4. Minimal API | FastAPI application with `/health` and an API test | Functions, HTTP, response models, application construction | Endpoint returns the expected response and its test passes |
| 5. Logging and errors | Structured logs, request correlation IDs and consistent error responses | Exceptions, middleware, logging, debugging | Requests can be traced without exposing secrets or internal stack traces to clients |
| 6. Local services | PostgreSQL and Qdrant in Compose, persistent volumes and health checks | Containers, networking, persistence | Both services start reliably and data survives a normal restart |
| 7. Application connections | Dependency connections, lifecycle management and `/ready` | Resource management, dependency injection, timeouts | Readiness succeeds with working dependencies and fails clearly when unavailable |
| 8. First schema and migration | Minimal collection/ingestion metadata schema and migration | SQL, relational modeling, constraints, schema evolution | Schema can be created in an empty database and constraints are verified |
| 9. Test foundations | Isolated integration tests plus unit/API tests | Fixtures, test boundaries, isolation | Tests use disposable data and require no GPU or live LLM |
| 10. Reproducible startup | API container, Compose integration and README instructions | Image builds, configuration, developer experience | A clean checkout starts the baseline stack by following the README |
| 11. CI | GitHub Actions checks, integration tests, dependency/security checks and Docker build validation | Automated verification, reproducibility | Workflow passes in a clean environment; later phases extend it |

## Progress and evidence

- Task 1: package directory and setuptools configuration exist. Installation was
  discussed and generated metadata exists, but an outside-repository import
  result was not captured. Verify briefly if needed rather than reteaching packaging.
- Task 2: complete. `environment.yaml` defines the Conda development
  environment, and `environment-linux-64.lock` records the recreated Linux
  package set. The README documents both workflows and editable installation.
  The user chose Conda as the sole development dependency manager. Agent
  verification confirmed Ruff, mypy, and pytest pass in
  `sci_research_agent`.
- Ruff/mypy/pytest configuration exists in `pyproject.toml`. The user reported
  installing tools through Conda in the `sci_research_agent` environment: Ruff
  0.16.7, mypy 2.3.1, pytest 9.1.1.
- Task 3: complete. `config.py` provides frozen typed settings with safe
  development defaults, environment-variable overrides, URL validation, and
  allowed environment/log-level validation. `.env.example` documents safe
  placeholders, `.env` remains ignored, and README documents loading behavior.
- Agent verification after Task 3: Ruff lint/format, mypy, and 9 pytest tests
  pass. No new dependency was needed; configuration uses the standard library.
- Task 4: complete. The FastAPI dependencies are managed through Conda, the
  application factory exposes a typed `GET /health` response, and the API
  contract has an HTTP-level test. The Linux lock was regenerated after the
  dependency update. The test uses HTTPX's async ASGI transport because the
  installed Starlette/httpx `TestClient` path hung in this environment.
- Agent verification after Task 4: Ruff lint/format, mypy, and 10 pytest tests
  pass. The recreated environment imports the application and passes the API
  test.
- Task 5: complete. Request middleware now preserves or generates bounded
  correlation IDs, exposes them through request context and response headers,
  and logs safe request metadata as JSON. Expected `AppError` failures and
  unexpected exceptions have consistent sanitized response envelopes.
- Agent verification after Task 5: Ruff lint/format, mypy, and 15 pytest tests
  pass.
- Task 6 implementation: `docker-compose.yml` defines PostgreSQL and Qdrant
  with named volumes, plus the API service. PostgreSQL has a container
  healthcheck; Qdrant is intentionally gated by process start because the
  pinned image does not include a reliable HTTP probe utility. Qdrant is
  verified by the application's network readiness check instead.
- Task 7 implementation: `/ready` uses bounded async PostgreSQL and Qdrant
  probes with injectable test seams and configurable timeouts. Unit/API tests
  cover ready and unavailable responses. The user verified the live endpoint
  returned HTTP 200 with both `postgres` and `qdrant` reported as `ok`.
- Task 8 implementation: `migrations/001_initial.sql` and
  `scripts/migrate.py` provide an idempotent first relational schema covering
  metadata, citations, documents, ingestion, runs, tools, claims, and
  evidence. The user successfully applied the migration to the live
  PostgreSQL service, and its migration state survived a normal restart.
- Task 9 implementation: tests now cover configuration, API contracts,
  observability, readiness seams, migration entities, and validation without
  requiring a GPU or live LLM. Disposable live-service integration tests remain
  a follow-on after the Compose gate is executable.
- Task 10 implementation: `Dockerfile`, `.dockerignore`, Compose startup, and
  README operations instructions are present. The user verified the API image
  built, the Compose stack started successfully, and named-volume state
  survived a normal restart. A clean-checkout run remains pending.
- Task 11 implementation: `.github/workflows/ci.yml` runs Conda setup, lint,
  formatting, mypy, tests, PostgreSQL migration, dependency checks, and Docker
  build validation. GitHub-hosted execution remains unverified in this session.
- Agent verification after the remaining implementation: Ruff lint/format,
  mypy, 19 pytest tests, Compose YAML parsing, `pip check`, and `pip-audit`
  pass. `pip-audit` reported no known vulnerabilities.
- User implemented `validation.py` and reported passing tests. The exercise
  checks increasing, equal and reversed year ranges, and illustrates type errors
  versus behavioral errors. The test is now under root `tests/` on disk.
  The user says they understand the gist; avoid repeating this exercise.
- User-reported Docker acceptance: `docker compose up --build` built the API,
  started PostgreSQL and Qdrant, and started the API. `/health` returned HTTP
  200 and `/ready` returned HTTP 200 with both dependencies `ok`. The user
  also successfully ran the migration and confirmed the migration state and
  readiness survived a normal PostgreSQL/Qdrant restart. CI acceptance
  evidence remains outstanding.
- The latest checks were agent-verified in the intended Conda environment.
  Consult actual files for current implementations.

## Next small task

Continue the Phase 0 gate:

1. Run the CI workflow in GitHub and resolve any runner-specific issues.

The earlier pip-tools instructions were superseded by the user's Conda choice.
Conda manages development dependencies, while Setuptools remains the package
build backend. Generated `.egg-info` directories are packaging artifacts, not
files the learner should hand-edit.

Checks already taught (run in the intended environment at repository root):

```bash
python -m ruff check .
python -m ruff format --check .
python -m mypy
python -m pytest
```

Update this handoff's progress after meaningful milestones, distinguishing
user-reported results from agent-verified results. Select later libraries and
implementation details when reaching their task, within the source-of-truth constraints.
