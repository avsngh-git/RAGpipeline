---
status: accepted
date: 2026-10-04
---

# Phase 3.5: online discovery and run-triggered ingestion

Accepted by the project owner on 2026-10-04, after the Phase 3.5 planning interview,
with the instruction to begin implementation.

This ADR changes several LOCKED and OPEN items in the source of truth:

- LOCKED section 8.6: scope, selection and execution.
- LOCKED section 10.4: the tool list.
- It resolves open decision 1 in part (corpus expansion).
- It resolves the API-controlled ingestion part of open decision 8.

It depends on ADR-0022 and ADR-0023.

## Context

- The owner wants a research question to find papers online, ingest the permitted ones,
  and answer from them.
- Discovery, permission-gated acquisition (ADR-0007), Docling extraction and indexing
  already exist, but they run as manual terminal commands with a reviewed manifest.
- Docling extraction took about 85 s per paper in the Phase 1 pilot. The generator and
  retrieval share an RTX 3050.
- OpenAlex charges about $0.01 per content download, against a free daily allowance of
  about $1.
- Many discovered papers will have no permitted full text.

## Decision

1. **Scope.** Discovery may cover ML and information retrieval research broadly. English
   and 2020 onward stay the defaults, with the existing exception for older foundational
   papers. Discovery filters on configured OpenAlex topic fields.
2. **`discover_papers` tool.**
   - It searches OpenAlex.
   - It upserts metadata into the PostgreSQL catalog, including a new metadata revision
     when a known paper's metadata changes.
   - It upserts title/abstract dense vectors into the `papers` collection, and ranks
     candidates by similarity to the question.
   - It returns OpenAlex abstracts as evidence of kind `abstract`. These get ordinary
     evidence handles, are stored in `research_run_evidence`, and are labelled as abstract
     evidence in claims and provenance. Their use is private and local; public display
     stays disabled.
3. **Membership policy.** The agent proposes papers through `request_ingestion`. Code, not
   the model, enforces:
   - exact-file permission evidence through the ADR-0007 routes;
   - per-run and daily budgets;
   - no recursive acquisition.

   Papers without a permitted source stay metadata-only. Every proposal, refusal and
   reason is recorded. Snapshots finalize automatically when the ADR-0002 integrity
   checks pass; this replaces the reviewed manifest for online-ingested papers. The owner
   can review afterwards.
4. **Modes.** Only `deep_research` may call `discover_papers` and `request_ingestion`.
   `quick` stays local, but may report known papers that are relevant but not ingested.
5. **Budgets (defaults, recorded with each run).**
   - Per run: 10 OpenAlex search requests, 5 full-text downloads, and 5 papers per
     ingestion wait.
   - Per day: an OpenAlex spend cap set below the free allowance.
6. **Worker.**
   - A separate `research-worker` process claims jobs from a PostgreSQL outbox with
     `FOR UPDATE SKIP LOCKED`. It runs in the same environment as the API, which is
     the host Conda environment today because the packaged image has no PyTorch. It
     becomes a Compose service when the image gains the model dependencies.
   - The outbox row is written in the same transaction as the ingestion request.
   - It runs the existing pipeline, then the ADR-0023 publication protocol.
   - GPU work takes a PostgreSQL advisory lock shared with generation.
   - One active ingestion job stays the rule.
7. **Run waiting.** A run that requests ingestion enters `waiting_for_ingestion` on its
   LangGraph checkpoint (ADR-0019).
   - The wait is capped at about 15 minutes. Waiting time does not count against the
     300-second active-time budget.
   - On completion the run switches to the new generation and records the switch.
   - If the cap is hit, it answers from what is published and lists the pending papers.
8. **API.** `POST /v1/collections/{collection_id}/ingest` enqueues the same outbox job for
   explicit paper IDs. Terminal commands keep working.

## Consequences

- Corpus membership is no longer reviewed before use for online-ingested papers.
  Provenance and post-hoc review replace it.
- Two new tools enter the locked tool contract. Their schemas follow section 10.4 rules.
- Runs can last many minutes of wall time while staying within their active-time budget.
- The Compose stack gains a worker service. Docling and the generator must take turns on
  the GPU.

## Alternatives considered

- **Owner approval per batch.** Stronger control, but every run blocks on a person.
- **Terminal-only ingestion with run requests queued.** Simpler, but it does not meet the
  owner's goal of answering from newly found papers.
- **Full-text-only evidence.** Most discoveries without a permitted source would
  contribute nothing.
- **Ingestion inside the API's run worker.** Long CPU/GPU work would block runs and
  breaks spec section 7.4.
