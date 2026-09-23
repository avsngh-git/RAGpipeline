# Phase 0 — Learning checklist and handoff

Updated: 2026-09-23. Audit fixes are implemented and locally verified; hosted CI on the fixed revision remains pending.

Read the [completion audit](../reviews/phase-0-audit-2026-09-23.md) for the
original findings, fixes, and verification evidence. Locked container and
disposable-service checks passed locally; hosted CI on the fixed revision is pending.

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

The 2026-09-23 audit identified gaps after the initial Phase 0 checks. The
follow-up fixes and local verification are recorded in the linked audit.
Remaining sign-off requires hosted CI to pass on the fixed revision.

| Task | Current status |
| --- | --- |
| 1. Package | Verified: import works outside the repository |
| 2. Development checks | Locked Conda environment used by CI; Ruff lint/format and mypy pass |
| 3. Configuration | Implemented with passing configuration tests |
| 4. Minimal API | Implemented; API tests and live `/health` pass |
| 5. Logging/errors | Verified: unexpected errors preserve request IDs in response/logs; JSON exception logs omit messages and source text |
| 6. Services | Verified: isolated stack startup and both stores' restart persistence |
| 7. Connections/readiness | Verified: live happy path plus stalled-query and stalled-cleanup timeout tests |
| 8. Schema/migrations | Verified: live migration reapplication and unique/FK constraints tested against disposable PostgreSQL |
| 9. Test foundations | 21 unit/API tests pass; 3 live PostgreSQL/Qdrant integration tests pass |
| 10. Startup | Verified: lock-based Docker build and live `/health` and `/ready` checks pass |
| 11. CI | Workflow now uses the Conda lock and runs isolated integration tests; hosted run on the fixed revision is pending |

The user uses Conda (`sci_research_agent`) and has completed the introductory
validation/type-checking exercise. The audit implementation gaps are fixed;
do not mark Phase 0 complete until hosted CI passes on the fixed revision.

## Next small task

Next, have the user commit/publish the reviewed changes through their normal
workflow and verify the resulting hosted CI run. Once it passes, record Phase 0
completion and resume the approved Phase 1 plan. Do not commit or publish on the
user's behalf unless explicitly asked.

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
