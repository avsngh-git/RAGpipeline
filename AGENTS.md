# Project guidance

Before planning, writing code, changing architecture, selecting infrastructure,
or adding dependencies, read
`docs/agents/scientific-research-platform-source-of-truth.md` in full.

That document is the authoritative project specification and high-level plan.
Use its delivery phases and gates to scope work, its LOCKED and OPEN decisions
to guide choices, and its change-control process for material changes.
Keep the specification at its current path as the single source of truth.

Before making a material contribution, apply its Agent operating checklist.
Choose the smallest coherent implementation that serves the current phase.

## Agent skills

### Learning workflow

For Phase 0 work, read `docs/plans/phase-0-learning-handoff.md`.
For Phase 1 work, read `docs/plans/phase-1-learning-handoff.md`, then follow the
approved tasks in `docs/plans/phase-1-corpus-ingestion.md`.
These handoffs record progress and the next exercise. The user implements the
project to learn Python; default to tutoring and reviewing, and implement only
when explicitly asked.

### Issue tracker

Track issues and specs in GitHub Issues for `avsngh-git/RAGpipeline`.
Before reading or publishing tickets, read `docs/agents/issue-tracker.md`.

### Triage labels

Use the five default triage labels.
Before triaging issues, read `docs/agents/triage-labels.md`.

### Domain docs

Use a single-context layout: root `CONTEXT.md` and `docs/adr/`.
Before exploring domain concepts or architectural decisions, read
`docs/agents/domain.md`.
