# Phase 1 completion audit — 2026-09-26

## Verdict and scope

**Hold Phase 2 implementation pending the completion fixes below.** The accepted
100-paper corpus exists and its current source/index integrity checks pass, but
recovery, acquisition ownership and secret-safe errors have reproducible defects.

Reviewed completion revision: `956b9b616958e821c0f417b5da59c209fb7e952d`.
The worktree was clean at audit start. The Phase 0 revision `d104e56` was used only
to identify the Phase 1 change surface; the review target is the current completion
revision. Requirements came from the local authoritative source of truth, Phase 1
plan, handoff and accepted ADRs. This is an implementation/completion review, not
a new corpus-membership or licensing decision.

No application code, accepted corpus, existing database or index was changed.
This audit is stored locally under the currently ignored `docs/` directory.

## Independently verified evidence

- 173 non-integration tests passed; all 15 integration tests passed separately
  against newly created disposable PostgreSQL and Qdrant containers. Total: 188.
- Ruff lint and formatting passed (71 files); strict mypy passed (40 source files).
  `pip check` found no broken requirements.
- Hosted [CI run 36232464593](https://github.com/avsngh-git/RAGpipeline/actions/runs/36232464593)
  succeeded on the exact reviewed revision. Docker build/dependency-audit evidence
  comes from hosted CI; those steps were not repeated locally in this audit.
- Read-only validation of snapshot `4b11fab3-d4a5-4e7a-a58e-8654accf2c6c` in
  `research_phase1_review` returned finalized, 100 members, 44,277 expected chunks
  and no issues. All 100 selected extractions have status `completed`.
- Reopened and hashed all 100 selected original PDFs: all checksums and byte sizes
  match their registered artifacts. Selected originals total 104,636,195 bytes;
  this is not a measurement of the entire artifact store or database footprint.
- Live Qdrant scroll returned exactly 44,277 unique evidence IDs for that snapshot,
  with no missing or extra IDs. Paper, document, extraction, source-artifact and
  index-configuration payload references all match PostgreSQL.

The original model/extraction experiments and manual quality samples were reviewed
as recorded evidence; they were not rerun or exhaustively reannotated. This audit
makes no new claim about all table cells, retrieval quality or broader coverage.

## Standards findings

### S1 — P1: OpenAlex budget-check errors expose the API key

Location: `src/research_platform/ingestion/cli.py:1687` (HTTP request and
`raise_for_status`), with the CLI exception handler at line 1958.

The budget preflight puts the key in a URL query parameter and raises an unsanitized
`httpx.HTTPStatusError` on 401/429/5xx responses. That exception is outside the CLI
handler and its traceback includes the URL and key. An offline MockTransport
reproduction returning 401 with a fake key included that fake key in the exception
text; no real credential was used or exposed by the audit.

Source of truth §14.2 requires that sensitive values/secrets must not be emitted
to logs or traces; §7.2 requires safe errors. Translate failures at this boundary
into sanitized domain errors without a URL-bearing exception chain. Regression
checks should exercise the CLI error path for 401 and 429 and assert the fake key
is absent from all captured output.

### S2 — P1: Acquisition bypasses the shared ingestion lease

Location: `src/research_platform/ingestion/cli.py:1628` and
`src/research_platform/ingestion/artifacts.py` (instance-local store locking).

`membership acquire` performs its eligibility checks, downloads and registration
without claiming the shared ingestion lease. Two commands can download the same
pending work and independently reserve storage/request budgets. Two ArtifactStore
instances sharing a temporary directory reproduced 26 bytes stored against a
20-byte cap using concurrent synthetic 13-byte PDFs. Cleanup only checks running
ingestion jobs, so it also cannot recognize this acquisition operation.

Source §8.6 requires one active ingestion process with concurrent-start protection
and a hard storage cap. Hold shared ownership from preflight through publication
and registration, with recoverable cancellation. Test two concurrent acquisition
commands and acquisition racing cleanup; the losing command must neither issue
content requests nor exceed the shared capacity.

### S3 — P2: Fresh checkouts lose the authoritative project documentation

Location: `.gitignore:239`; commit `5bac22e` removes the tracked `docs/` tree.

The specifications, ADRs, plans, handoffs and acceptance reports exist on this
machine but are no longer in HEAD. README links and mandatory AGENTS.md read paths
therefore fail in a fresh checkout. This prevents a new agent or contributor from
recovering the approved requirements and acceptance evidence from the repository.

AGENTS.md requires the source of truth; source §19 requires scripted/documented
acquisition, and P1-14 requires documentation and acceptance evidence. Retain
sanitized specifications, decisions, reports and runbooks in version control;
keep full text, credentials and generated corpus artifacts excluded. If local-only
documentation is intentional, explicitly resolve that reproducibility tradeoff.
Verify required instructions and README links against Git's tracked tree, not
merely filesystem existence.

## Specification findings

### R1 — P1: Targeted retry can falsely complete an unfinished job

Location: `src/research_platform/ingestion/runner.py:293`; resume rejection in
`src/research_platform/ingestion/stage_repository.py:182`.

Completion checks only whether any registered document rows are failed. A shared
failure on the first document stops the run before later planned documents get
rows. Retrying the first document clears the only failed row and marks the entire
job completed, making the untouched documents impossible to resume in that job.

Reproduced against the disposable PostgreSQL instance with two synthetic planned
papers: the first run raised a shared failure; targeted retry returned completed
with one registered/completed document and the second never processed; resume
raised `a completed ingestion job cannot be resumed`.

Source §8.2 requires resumability after partial failure; P1-11 requires explicit
outcomes. Persist full planned membership and require all necessary terminal-stage
checkpoints before completion. Add this two-document interruption/targeted-retry/
resume regression, including cancellation and expired-lease variants.

### R2 — P2: Oversized table context stops unrelated papers

Location: `src/research_platform/ingestion/processing.py:283` and
`src/research_platform/ingestion/evidence.py:679`.

The processor only translates the obsolete error text `one table row exceeds`.
The cell-splitting fallback now raises `table cell header context exceeds the
configured searchable token limit`. A synthetic table with a 500-token caption
under a 480-token limit raises an untranslated ValueError; the runner treats it as
a shared failure and aborts later documents.

Source §8.6 requires unaffected papers to continue after paper-specific failures.
Use a typed chunking error translated into DocumentStageFailure, preserve usable
intermediate extraction, and test a failing table followed by a successful paper.

### R3 — P2: Stage compatibility depends on unrelated repository changes

Location: `src/research_platform/ingestion/processing.py:102` and
`src/research_platform/ingestion/cli.py:831` / line 870.

The effective pipeline hash includes the whole repository revision/dirty digest.
Changing only that revision with identical parser/tokenizer/chunk settings changes
the pipeline identity, and the CLI rejects resume. A README-only commit therefore
forces a new job. Extraction and chunking are also wired as one runtime stage,
so changing chunk settings reruns the parser instead of reusing extraction.

Source §8.2 requires reprocessing only affected stages when a version changes.
Keep code revision as provenance, define compatibility fingerprints for the
actual stage inputs/implementation, and checkpoint extraction independently from
chunking. Test that a documentation change does not prevent resume and that a
chunk-only change reuses retained parsing output.

## Remediation disposition — 2026-09-26

All six findings have been corrected in the current worktree:

- **S1 — fixed.** OpenAlex budget-check status and network errors are translated at the HTTP boundary to a sanitized `OpenAlexRequestError` without a chained URL-bearing exception. CLI regressions cover 401 and 429 and assert the fake API key is absent from captured output.
- **S2 — fixed.** Membership acquisition creates and claims a persisted `membership-acquisition` job before preflight, keeps its lease alive through registration, and finishes the job on success/failure/cancellation. Artifact writers now use a cross-process filesystem lock around the shared byte-cap check and write. Live tests cover concurrent stores, competing acquisition leases before content requests, and cleanup recognizing an active acquisition job.
- **S3 — fixed.** The `/docs/` ignore rule is removed and sanitized specifications, ADRs, plans, handoffs, reports, and audits are restored to Git. Relative links to local-only manifests, excerpts, and PDFs are plain path references that say those materials remain outside Git. No credential, paper PDF, local excerpt, or generated corpus artifact is included.
- **R1 — fixed.** Migrations `013_ingestion_job_plans.sql` and `014_snapshot_chunking_configuration.sql` persist the complete document/input plan and required terminal stage. A job can complete only after every planned document has its matching terminal checkpoint. Live regressions cover shared interruption, targeted repair followed by full resume, cancellation, and expired-lease recovery.
- **R2 — fixed.** Oversized table context raises typed `EvidenceChunkingError`, which the PDF processor converts into a non-retryable paper-level failure. The extracted source remains persisted independently; a live runner regression proves a later paper still runs.
- **R3 — fixed.** Git revision is retained as job provenance and excluded from stage compatibility IDs. Parser/extraction and tokenizer/chunking now have separate compatibility fingerprints and checkpoints. Matching extraction output is loaded from PostgreSQL by later chunk configurations, and chunk IDs include their full compatibility identity, and each snapshot member selects one active chunk set so old chunks are not mixed into the rebuilt index. Tests cover stable extraction IDs, changed chunk IDs, cache reuse without a parser call, and idempotent chunk persistence.

### Verification

- Full suite: **199 passed in 4.86 seconds**, including the isolated PostgreSQL/Qdrant live-service tests against newly created disposable containers.
- Ruff lint passed; Ruff formatting check passed (93 files).
- Strict mypy passed (40 source files).
- README and Markdown relative links were checked against Git’s tracked file list after restoring `docs/`; required AGENTS.md documentation paths are tracked.
- The accepted 100-paper database, snapshot, artifacts, and Qdrant collection were not touched.

The remediation worktree has not been committed or pushed. Hosted CI for its new revision remains outstanding, so Phase 2 stays on hold until the user commits the changes and that CI run passes. The green CI evidence above applies to the previously reviewed revision only.


## Planning-time verification update — 2026-09-26

Hosted CI [36238052340](https://github.com/avsngh-git/RAGpipeline/actions/runs/36238052340)
passed on remediation revision `d28e1adc299d6199774c78a2d63cb3eb0870d5ab`.
The planning pass verified that result but did not rerun the code-fix regressions.

The earlier S3 closeout statement was premature: the bottom `/docs/` rule was
removed, but `.gitignore:16` still contained bare `docs`, and `git ls-files docs`
returned no paths. The approved Phase 2 planning change removes that remaining
rule and makes the sanitized documents eligible for tracking. No staging or commit
was performed. Verify their inclusion in the next committed change set before
claiming fresh-checkout readiness. This correction does not change corpus data.
