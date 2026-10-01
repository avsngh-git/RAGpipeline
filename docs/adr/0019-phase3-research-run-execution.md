---
status: accepted
date: 2026-10-01
---

# Phase 3 research runs: modes, execution, durability and evidence handles

Accepted by the project owner on 2026-10-01. This resolves open decision 8 (background
execution for research runs) of the source of truth. API-controlled ingestion remains
open.

## Context

- Section 7.2 locks `POST /v1/research` and `GET /v1/research/{run_id}`. A run takes up to
  minutes on the laptop.
- Section 10 locks one LangGraph agent with explicit budgets, and section 4 says the LLM
  chooses the next action while tools act.
- A 4B model makes more mistakes when it must choose every single tool call.
- Migration 001 already defines `research_runs`, `tool_calls`, `claims` and
  `claim_evidence`; Phase 2 evidence hits are `chunks.id` values.
- The project uses asyncpg. `langgraph-checkpoint-postgres` 3.x requires psycopg 3 with
  `autocommit=True` and `row_factory=dict_row`, and creates its own tables with `setup()`.

## Decision

1. **Modes.** `quick` is a fixed LangGraph graph: search papers, search evidence, then
   synthesize and verify. `deep_research` plans, executes, then judges sufficiency: the
   LLM proposes an `ActionBatch` of 1 to 4 typed actions, code executes them, and one
   evaluation call returns either "sufficient" or a revised batch. Both modes share the
   synthesis and verification nodes. The request's `mode` field is required.
2. **Execution.** `POST /v1/research` validates, stores a `queued` run and returns its
   ID. One asyncio worker inside the API process runs one run at a time in queue order.
   `GET` reads the stored run.
3. **Durability.** LangGraph's `AsyncPostgresSaver` stores checkpoints in a separate
   Postgres schema `langgraph`; `scripts/migrate.py` calls `setup()` after the SQL
   migrations. The thread ID is the run ID. Checkpoints are written after every step
   (durability `sync`), and `LANGGRAPH_STRICT_MSGPACK=true` is set. psycopg is used only
   in `research_platform.runs.checkpointing`; everything else stays on asyncpg.
4. **Resume.** On startup the executor re-queues runs left `running` and resumes each
   from its last checkpoint. A run is resumed at most 2 times, then fails with
   `resume_exhausted`. A run whose recorded configuration ID differs from the current one
   fails with `configuration_changed`. The 300-second budget counts active time summed
   across attempts.
5. **State.** Graph state holds references only: chunk IDs, evidence handles, scores and
   compact tool observations. Passage text returned by a tool is stored in the new
   `research_run_evidence` table and read back for synthesis, so checkpoints stay small
   and the original access policy decision is not repeated.
6. **Evidence handles.** Each new chunk in a run gets the next handle (`E1`, `E2`, …, up
   to 40) in arrival order. Prompts show handles, the model cites handles, and code maps
   them to chunk IDs. A cited handle outside the run's registry rejects that claim.
7. **Retention.** Checkpoints are kept after a run ends so failed runs can be inspected.
   `research-runs prune --older-than <days>` deletes runs, their evidence copies and their
   checkpoints. Retention periods stay open.

## Consequences

- Two Postgres drivers exist; the second is confined to one module and one schema.
- A crash costs at most the step in progress. Tools are read-only, so re-executing a
  step is safe, but its model output may differ.
- One run at a time matches single-user laptop operation; a separate worker can replace
  the in-process executor later without changing the API.
- Run provenance records mode, budgets, configuration ID, code revision, snapshot,
  retrieval profile, prompt versions, model identity, and resume count.

## Alternatives considered

- **Per-step tool choice (ReAct).** More flexible, but slower and more error-prone with a
  4B model.
- **No checkpointing; mark crashed runs failed.** Simpler; the owner preferred resumable
  runs because LangGraph already provides them.
- **A custom asyncpg checkpointer.** Avoids psycopg but is subtle code to own.
- **A separate worker and queue.** More infrastructure than one laptop user needs.
