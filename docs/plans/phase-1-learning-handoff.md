# Phase 1 — Learning handoff

Updated: 2026-09-23. Detailed plan approved; implementation not started.

## Start here

1. Follow AGENTS.md and read the authoritative
   [source of truth](../agents/scientific-research-platform-source-of-truth.md).
2. Read the [approved Phase 1 task checklist](phase-1-corpus-ingestion.md).
3. Resume at **P1-01**, verifying hosted CI for the actual Phase 0 fixed revision.
   Then work on P1-02, one small typed-contract/configuration exercise at a time.

Do not repeat the completed planning interview. Corpus scope, 10/100-paper
milestones, text/table requirements, manually finalized snapshots, one active
ingestion process and unresolved citation preservation are already approved.
Library/model choices and numerical thresholds are deliberately deferred to the
plan's decision points. Ask only about genuinely unresolved choices.

## Working with the user

The user is learning Python and writes the implementation. Default to tutoring:
explain the next small task and its purpose, let them attempt it, review the work,
and help debug. Implement only when explicitly delegated. This handoff request
and approval of the plan do not delegate building the whole phase automatically.
The user prefers Luna for routine work to control token use; this file does not
change the active model. Keep progress updates and explanations focused.

Documentation and checklist maintenance are authorized as part of this handoff.
Preserve existing worktree changes. Do not commit, push, create GitHub issues or
start large acquisitions/model downloads merely because they appear in the plan.
Use the issue-tracker instructions if ticket publication is later requested.

## Repository facts at handoff

- HEAD was `95bec46cf6d8d14f537f0d5031dcdb9e0e837167`.
- Phase 0 audit fixes were present in the uncommitted worktree. The
  [audit](../reviews/phase-0-audit-2026-09-23.md) and
  [Phase 0 handoff](phase-0-learning-handoff.md) record local verification.
- The last observed green hosted CI run was
  [35844283065](https://github.com/avsngh-git/RAGpipeline/actions/runs/35844283065),
  for the earlier HEAD. It does not verify uncommitted fixes. Recheck current
  state; preserve the user's normal commit/publish workflow.
- Existing foundations: Conda environment/lock, package, typed settings,
  FastAPI health/readiness, logging/errors, PostgreSQL/Qdrant Compose,
  migration runner and unit/API/live-service test infrastructure.
- Ingestion, discovery, artifact storage, extraction, embedding, indexing and
  snapshot finalization are not implemented. Existing tables are foundations,
  not evidence of those behaviors.
- Preserve applied `001_initial.sql`; extend through new migrations. The
  migration runner needs atomic apply/version recording and concurrent-run
  protection before substantial schema expansion. Check current code first.
- Existing citations require complete local paper rows; Phase 1 must represent
  unresolved external endpoints explicitly. Snapshot and extraction lineage also
  need schema support. An ADR is required for material schema decisions.
- Observed RTX 3050 Laptop GPU: 4 GiB VRAM; WSL RAM: about 7.6 GiB total.
  Remeasure at execution. Virtual filesystem free space is not physical host
  free capacity. Parser/model feasibility remains untested.

## Progress protocol

The detailed plan owns task IDs, scope, dependencies and completion evidence.
Update its status table after verified milestones; keep this handoff's next step
current. Label user-reported versus agent-verified outcomes and record code/config
revisions. Do not mark Phase 1 complete without its actual finalized 100-paper
snapshot, acceptance report, recovery/rebuild evidence and passing checks.

Next task: P1-01 pending. No Phase 1 code or data was generated while writing
this handoff. Once P1-01 is settled, teach the first small part of P1-02 rather
than generating an entire domain model before its use cases exist.
