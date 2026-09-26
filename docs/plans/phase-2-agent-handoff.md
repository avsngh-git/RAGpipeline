# Phase 2 — Agent handoff

Updated: 2026-09-26. Plan approved; P2-01/P2-02 and P2-03.1–P2-03.3 complete.

## Start here

1. Follow AGENTS.md and read the authoritative source of truth in full.
2. Read the [roadmap](phase-2-retrieval-evaluation.md), then the first pending task
   whose prerequisites are satisfied. Begin at **P2-03.4**.
3. Read the [evaluation protocol](phase-2-evaluation-protocol.md) when working on
   judgments, experiments or scoring. Read ADR-0008 for variant/access boundaries.

The planning interview is complete. Preserve its decisions; investigate current
facts yourself. Do not restart the interview or select different technology merely
because another agent prefers it. Measured settings are deliberately deferred to
named tasks and must be recorded there.

## Delegation and working style

The user explicitly delegated all Phase 2 implementation, calibration, benchmark
preparation and source review for now. Once asked to begin Phase 2, execute bounded
substeps autonomously, explain changes/tests briefly and update progress. The earlier
user-writes-code default does not apply to this delegated phase. No recurring human
annotation gate is required. Mark new judgments assistant-reviewed; record source
checks, uncertainty and sampling limits. Escalate actual contradictions or material
changes beyond the approved scope, rather than routine reversible choices.

The user's preference is economical model use for routine work. This handoff does
not change the active model. Never infer that an unchecked task is complete.
No commit, push, ticket publication, paid compute or public deployment is authorized
merely by this roadmap. Preserve the user's existing worktree and publication workflow.

## Current baseline and traps

- Current entry revision: `0458c9c7f28a5eceac5ca939fe1e17a59e870c1b`.
  [Hosted CI 36241133854](https://github.com/avsngh-git/RAGpipeline/actions/runs/36241133854)
  passed on that exact revision. It changes docs/configuration only relative to
  the remediation revision `d28e1adc299d6199774c78a2d63cb3eb0870d5ab`; no local
  test suite was rerun during P2-01.
- P2-01 removed the root `/docs/` ignore rule. Sanitized project documents are
  eligible for version control and were committed by the user at
  5f2a7db5835df2fa6b89692a06701d564901a8bb. Local-only manifests, excerpts and
  PDFs remain excluded from Git.
- The accepted snapshot is `4b11fab3-d4a5-4e7a-a58e-8654accf2c6c` in
  **research_phase1_review**, not default **research**. P2-01 applied migrations
  013/014 after a verified local backup; read-only validation, 100 source checksums
  and snapshot-scoped reconciliation all pass at 100 papers / 44,277 chunks. The
  running API still targets `research`; bind Phase 2 operations to the review DB.
- Qdrant `phase1-e5-small-v2` also contains the retained ten-paper draft's points.
  Every query must bind a snapshot and compatible profile; collection count is not
  corpus membership. New model/chunk variants must not overwrite the accepted set.
- All 100 permission records allow storage/indexing and disable passage display.
  The approved trusted private-local inspection policy is separate from public
  output. Never change permissions by interpreting an API flag as authorization.
- Reuse ingestion/indexing.py, embeddings.py, snapshots.py, evidence persistence
  and migrations 013/014. They provide versioned indexing, query embeddings,
  finalization checks and separate extraction/chunk checkpoints. Verify applied
  schema before querying with newer code; tests use isolated services.
- Existing query_snapshot handles snapshot filtering; richer filters, lexical
  search, fusion, reranking, evaluation and the new API remain Phase 2 work.
- Existing draft preview is not the finalized evidence service. The API currently
  exposes health/readiness only. New routes call shared services.
- Model shortlist and hardware memory figures are not feasibility proof. Remeasure
  current resources. Keep synthetic CPU CI independent of model downloads.
- JSON is broadly ignored. Use deliberately tracked sanitized config/fixture paths;
  full text, source PDFs and private review artifacts stay outside Git.

## Progress and stop rules

- **P2-02 complete** in the user commit `5f2a7db5835df2fa6b89692a06701d564901a8bb`: search contract, framework-independent contracts,
  strict HTTP schemas, fail-closed filter matching, and server-owned evidence access.
- **P2-03.1 inventory complete:** existing snapshot/index/stage persistence was
  inspected. The accepted snapshot has 100 members and 44,277 currently selected
  chunks. All 100 member chunking IDs are null; 39,209 selected chunks carry a config
  ID and 5,068 are legacy chunks without one. IndexRepository currently treats null
  as every chunk under an extraction. Do not add variant chunks under those accepted
  extractions or rebuild its index until P2-03.3 guards the exact selected set.
- **P2-03.2 complete:** src/research_platform/search/profiles.py defines strict,
  canonical profile and chunk-selection identities. The accepted snapshot selection
  hashes to sha256:cc5b7c30962ce66ad279a5ff95b0e1e6dd8aede68980292717d1a7a23ecd6f18.
  No lexical dependency or model choice was made.
- **P2-03.3 complete:** migration 015 persists each snapshot's exact selected chunk IDs,
  backfills legacy selections, and blocks mutation after finalization. Variants copy
  a finalized parent's paper/document/extraction and exact chunk selection, and retain
  the parent's canonical selection identity in lineage. The loader, inspection and
  finalization checks use the persisted selection. See ADR-0009 and the roadmap.
- Verification: ruff check ., ruff format --check ., and mypy pass;
  pytest -m 'not integration' reports 202 passed / 19 deselected; the focused
  variant integration test passes on Compose research_test. The separate migration
  runner test expects a pristine test DB, but local research_test already contained
  migrations 001–012 and that test failed before applying pending migrations.
  Migration 015 was then applied successfully by the variant integration test.
  The accepted database was not migrated. Hosted CI has not run.
- P2-03.2/03.3 code and documentation are committed as the current checkpoint. No
  Phase 2 model was downloaded, index built, source corpus changed, judgment authored,
  or benchmark run. Next substep: **P2-03.4**, atomic derived-index publication.


The roadmap owns the task status table. For each completed substep record changed
paths, actual commands/results, code/config/benchmark IDs and any limitations.
Mark a task complete only when its Done condition is met; update this file's next
step without duplicating the full checklist. Preserve intermediate failures and
assistant-review uncertainty. Thresholds are frozen before held-out assessment.

A failed measurement or missing external input is not completion. Continue useful
independent work and report the specific blocker. Any source/schema/permission
change follows the source-of-truth change-control rule. Keep the original corpus
usable throughout.

**Next step:** P2-03.4. See docs/api/phase-2-search-contract.md for the profile contract,
ADR-0009 for exact selection and lineage, and docs/reviews/phase-2-entry-check.md
for resource measurements, migration/restore evidence and local artifact paths.
