# Phase 0 completion audit

Date: 2026-09-23. **Initial result: five implementation gaps found. Follow-up: fixes implemented and locally verified; hosted CI on the fixed revision remains pending.**

Reviewed `da01d11...95bec46` and the current working tree against the
[Phase 0 checklist](../plans/phase-0-learning-handoff.md) and
[source of truth](../agents/scientific-research-platform-source-of-truth.md).
The pre-existing modification in `src/research_platform/validation.py` was
formatting-only; its behavior was preserved while its formatting issue was fixed.
The initial audit recorded findings; their subsequent resolutions are below.

## Baseline evidence (before fixes)

| Check | Result and scope |
| --- | --- |
| Ruff lint | Pass in the intended `sci_research_agent` Conda environment |
| Ruff format | Fail in current worktree: `validation.py` comparison spacing and final newline; 28 other files already formatted |
| mypy | Pass, 12 source files |
| pytest | 19 passed; current tests do not provide live-service integration coverage |
| Dependency consistency | `python -m pip check` passed |
| Installed package | Imported successfully from `/tmp`, resolving to the project's source package |
| Hosted CI | [Run 35844283065](https://github.com/avsngh-git/RAGpipeline/actions/runs/35844283065) succeeded for `95bec46cf6d8d14f537f0d5031dcdb9e0e837167` |
| Clean committed-source startup | `git archive HEAD` extracted into a temporary directory; Docker image built and isolated Compose stack started with fresh volumes |
| Live HTTP | `/health` and `/ready` returned 200; PostgreSQL and Qdrant reported `ok` |
| Migration | Applied twice to disposable PostgreSQL; one migration version recorded |
| Basic constraints | Duplicate collection name rejected; document referring to nonexistent paper rejected |
| Restart persistence | Test collection record, migration state and Qdrant collection survived ordinary service restarts; readiness recovered |
| Error-path reproduction | Unexpected 500 without incoming request ID returned null body ID and no `X-Request-ID`; synthetic secret in exception text appeared in captured logs |
| Stalled PostgreSQL query | A stub established connection exceeded the configured 0.02-second probe timeout; an external 0.2-second guard stopped it |

The clean-source check used a separate Compose project and alternate host ports;
no user service data was used. The existing Conda environment ran the local
checks; a fresh locked Conda environment was not recreated for this audit.
Hosted CI verifies a fresh runner, but installs from YAML rather than the lock.
The hosted workflow includes pip-audit; no additional current advisory scan or
container vulnerability scan was performed locally. A green CI run is evidence
for the checks it runs, not for the missing cases below.

## Follow-up resolution

The initial findings below are historical; the implementation and local checks
now resolve them as follows:

| Finding | Resolution |
| --- | --- |
| S1 | CI creates its environment from `environment-linux-64.lock`; the Docker image installs the same lock and the project without dependency resolution. |
| S2 | JSON exception logs retain exception type and bounded frame metadata, but omit exception messages and source lines; a synthetic-secret regression test verifies this. |
| S3 | Request IDs persist in ASGI scope state and are returned in the unexpected-error body/header and both correlated error logs. |
| S4 | PostgreSQL connect/query/cleanup share one deadline; stalled-query and stalled-close tests verify termination and bounded completion. |
| S5 | Three opt-in live tests cover readiness, repeatable migrations and database constraints, and temporary Qdrant collection lifecycle. |
| P4 | `validation.py` formatting is fixed without changing its behavior. |

Follow-up local verification:
- Ruff lint and format checks pass; mypy passes for 12 source files.
- Unit/API suite: 21 passed; three integration tests are skipped unless dedicated test-service URLs are supplied.
- Explicit integration run against disposable PostgreSQL and Qdrant: 3 passed.
- A `linux/amd64` Docker build consumed the Conda lock; an isolated Compose stack returned 200 for `/health` and `/ready`, with both dependencies healthy.
- Hosted CI on the fixed revision has not yet run. Phase 0 completion remains pending that gate.

## Initial standards findings

1. **S1 — Dependency locks are bypassed (high).**
   `.github/workflows/ci.yml:43` installs `environment.yaml`; `Dockerfile:11`
   independently installs unpinned dependencies from PyPI. The committed Linux
   Conda lock is not consumed by either path. Source-of-truth Sections 15 and
   17.1 require deliberate dependency locking and CI installation from a lock.
   Make each install path use an appropriate locked input and verify the
   intended relationship between the tested environment and container runtime.

2. **S2 — Exception logs can disclose secrets (high).**
   `src/research_platform/observability/logging_config.py:30` serializes raw
   exception text/tracebacks. Both request-failure logging and the outer error
   handler reach it. A fake secret appeared in captured JSON logs, despite a
   sanitized HTTP response. Section 14.2 prohibits secret leakage to logs.
   Define safe exception reporting/redaction and test captured output with
   synthetic sensitive values while preserving useful diagnostics.

3. **S3 — Unexpected errors lose correlation IDs (medium).**
   `src/research_platform/api/errors.py:41` reads request context after
   `observability/request_context.py:59` resets it. The outer error handler also
   bypasses header injection. Reproduced 500 response: body request ID null,
   response header absent, while the request-failure log had an ID.
   Preserve the validated/generated ID beyond middleware unwinding and verify
   consistency across error body, response header and logs. Covers Section 7.4.

4. **S4 — Readiness timeout does not bound the whole PostgreSQL probe (medium).**
   `src/research_platform/services/readiness.py:56-64` times out connecting but
   leaves the query and cleanup without the configured overall deadline.
   An established stalled connection can delay `/ready` beyond that deadline.
   Bound the whole operation and cleanup, then test stalled queries and
   resource release. Covers Section 7.4 and checklist Task 7.

5. **S5 — Live integration coverage is missing (medium).**
   `tests/test_migrations.py:6` only checks SQL substrings, and readiness API
   tests use stubs. CI applies the migration once but does not assert constraints,
   reapplication or live Qdrant behavior. Sections 16.2 and checklist Tasks 8–9
   call for isolated boundary tests. Add repeatable disposable-service tests;
   this audit's manual smoke checks are not a replacement.

No additional code-smell-only findings were retained.

## Initial spec findings

1. **P1 — Task 7 remains partial:** the promised bounded readiness behavior is
   not satisfied for an established stalled PostgreSQL connection (S4).
2. **P2 — Tasks 8–9 remain partial:** live schema application and basic constraints
   worked during the audit, but the repository lacks automated integration and
   constraint coverage (S5).
3. **P3 — Tasks 2, 10 and 11 have reproducibility gaps:** the lock exists and
   startup/CI succeed, but automated install paths bypass locked inputs (S1).
4. **P4 — The current worktree fails its formatting gate:** run the formatter
   on `src/research_platform/validation.py` before expecting CI-equivalent checks
   to pass. This is the user's existing edit, not a functional regression.

The scope was Phase 0. Missing ingestion, research endpoints, retrieval,
model evaluation and MCP are later-phase work, not completion findings here.

## Follow-through

Have the user verify hosted CI after publishing the fixed revision through their
normal workflow. When it passes, record Phase 0 completion and resume the
approved Phase 1 plan.

Totals: 5 Standards findings (highest: unlocked installs and unsafe exception
logging); 4 Spec findings (highest: timeout and reproducibility gaps).
