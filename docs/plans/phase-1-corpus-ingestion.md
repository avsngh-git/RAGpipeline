# Phase 1 — Corpus and ingestion

Status: detailed plan approved 2026-09-23; implementation not started.
Original scope approved 2026-09-22. Phase 0 hosted CI on the fixed revision is
still the entry gate at this handoff; verify current evidence before starting.

## Authority and working agreement

Read the [source of truth](../agents/scientific-research-platform-source-of-truth.md)
in full as required by AGENTS.md. Section 8.6 owns the corpus constraints.
[ADR-0001](../adr/0001-versioned-corpus-evidence.md) explains versioned evidence;
[ADR-0002](../adr/0002-finalize-validated-snapshots.md) explains snapshot acceptance.
[CONTEXT.md](../../CONTEXT.md) defines terms.

The user implements this project to learn Python. Default to explaining one small
exercise, reviewing their attempt and helping debug. Implement only when explicitly
asked. Approval of this plan is not blanket delegation of application coding.
A continuing agent should start with the [Phase 1 handoff](phase-1-learning-handoff.md).

## Outcome and boundaries

Deliver a finalized snapshot containing 100 successfully ingested papers with
usable text and structured table evidence, verified provenance, safe recovery,
a rebuildable Qdrant index and a measured corpus quality report. First compare
extraction approaches on 10 papers. These counts are engineering milestones,
not proof of research coverage or retrieval quality.

The initial scope is English-language RAG, retrieval and reranking papers from
2020 through the recorded snapshot date, with explicit older foundational
exceptions. Include substantive contributions/evaluations and negative or mixed
findings. Broader ML research is the later expansion path.

Coverage questions:

1. When does hybrid retrieval outperform dense-only retrieval?
2. How much does cross-encoder reranking improve retrieval quality, and at what latency cost?
3. How do chunking choices affect evidence retrieval and citation support?

Use OpenAlex for discovery, metadata and real citation relationships. Acquire
full text through supported sources under documented permissions. Prefer the
published version, falling back to an eligible preprint, and identify the version
actually indexed. Preserve metadata-only and unresolved-reference records.

Phase 1 includes an explainable discovery shortlist and human-approved manifests.
It does not require a learned selection classifier, automated refresh, recursive
full-text citation expansion, background job queue, ingestion UI, full search API,
research agent or MCP server. A local index-inspection command is in scope;
full lexical/hybrid/reranking evaluation belongs to Phase 2. The eventual required
API endpoints remain part of the project, even though ingestion is terminal-driven
in this phase. Plot/equation interpretation is assessed during the pilot before
committing to implementation scope.

Use local compute without paid data acquisition/cloud compute initially. The
observed laptop GPU has 4 GiB VRAM and WSL exposes about 7.6 GiB RAM; remeasure
at execution time. Neither parser nor vision-model feasibility is established.
Virtual filesystem free space is not proof of physical host capacity.

## Task checklist and dependencies

All Phase 1 tasks are pending. Mark a task complete only with its listed evidence.
Use these IDs in commits or future issues; these rows are not published tickets.

| ID | Task | Depends on | Status |
| --- | --- | --- | --- |
| P1-01 | Entry gate and execution profiles | Phase 0 fixes | Pending |
| P1-02 | Typed ingestion contracts and configuration | P1-01 | Pending |
| P1-03 | Safe schema evolution and persistence | P1-02 | Pending |
| P1-04 | Reproducible discovery and explainable shortlist | P1-02, P1-03 | Pending |
| P1-05 | Paper/version identity and unresolved citations | P1-03, P1-04 | Pending |
| P1-06 | Acquisition and efficient artifact storage | P1-03, P1-05 | Pending |
| P1-07 | Human-verified 10-paper reference set | P1-04, P1-06 | Pending |
| P1-08 | Extraction comparison and quality decision | P1-07 | Pending |
| P1-09 | Normalized evidence and chunking | P1-03, P1-08 | Pending |
| P1-10 | Embeddings, Qdrant indexing and rebuild | P1-09 | Pending |
| P1-11 | Runner, recovery and snapshot finalization | P1-02 through P1-10 | Pending |
| P1-12 | Operational visibility and storage controls | Across P1-03 through P1-11 | Pending |
| P1-13 | Verification suite and CI | Alongside every implementation task | Pending |
| P1-14 | 100-paper acceptance pilot and documentation | P1-01 through P1-13 | Pending |

The order describes completion dependencies, not a requirement to finish every
layer before exercising it. Introduce a minimal runner/checkpoint path with the
first persisted stage and expand it incrementally. Add tests and operational
records with each stage; P1-11 through P1-13 are consolidation gates, not permission
to defer reliability until the end.

## P1-01 — Entry gate and execution profiles

- Verify hosted CI against the committed Phase 0 fixes, not the earlier green revision.
- Record the starting code revision, environment lock and runtime versions.
- Measure usable RAM/VRAM and physical storage available to project artifacts.
- Define deterministic CI, 10-paper comparison and 100-paper pilot profiles.
- Give each profile explicit resource/request limits; keep live downloads and
  large-model execution outside ordinary CI.

Completion evidence: verified baseline, recorded hardware/runtime profile and
profile definitions. Reuse Phase 0 foundations rather than rebuilding them.

Learning: reproducible execution, configuration scope and interpreting CI evidence.

## P1-02 — Typed contracts and configuration

Introduce typed representations as their first use cases require them:
discovery candidates, external references, paper/document versions, artifacts,
extraction results, evidence units, snapshots, jobs, attempts and stage outcomes.
Keep application contracts independent of source, parser, database and model clients.

Validate serializable configuration for corpus queries/dates/language/exceptions,
supported sources, parser/model revisions, text/table chunking, embeddings/index
identity, retry/time limits, batches and storage limits. Separate secrets from
serializable configuration. Define stable identifiers for effective configuration,
record the code revision and define which changes invalidate downstream stages.

Completion evidence: invalid inputs fail clearly; configuration round-trips;
identical effective inputs have consistent identity; outputs reference the
configuration that produced them. Exact libraries and field layouts are implementation
choices, subject to existing architecture and measured needs.

Learning: dataclasses/Pydantic, enums, protocols, validation and serialization.

## P1-03 — Safe schema evolution and persistence

Add migrations; preserve the already-applied `001_initial.sql`. Support:

- normalized external paper identifiers and verified version relationships;
- artifact references, acquisition timestamps, permissions and checksums;
- extraction versions, evidence locations and structured tables;
- draft/finalized snapshots with selected versions and configurations;
- per-stage checkpoints, attempts, errors and output references;
- unresolved external citation endpoints without invented titles;
- index configuration and reconciliation status.

Make migration execution and version recording atomic where supported, with
protection against concurrent migration runs. Update integration tests that
currently assume only `001_initial`. Build repository operations and connection
lifecycle management appropriate to ingestion; the readiness probe is not an
application persistence layer.

Completion evidence: empty-database and Phase 0 upgrade paths pass; failed migrations
do not falsely record success; uniqueness and referential constraints have live,
isolated tests. Record material schema decisions through the project change process.

Learning: transactions, constraints, migrations, repositories and resource ownership.

## P1-04 — Discovery and explainable candidate selection

Implement configurable OpenAlex queries/filters, pagination, bounded requests,
provider throttling/backoff and resumable discovery. Preserve query/configuration,
retrieval timestamps and enough source metadata to explain a candidate's origin.
Source APIs can change: replayability comes from retained records, not a promise
that repeating today's query always returns the same future results.

Normalize identifiers, handle duplicates, and produce an explainable shortlist
with recorded selection signals. Export a reviewable manifest and preserve the
reviewer's inclusion/exclusion reasons, including explicit older-paper exceptions.
Keep negative and mixed findings. Review across all three coverage questions.

Evaluate shortlist relevance, coverage and bias against retained review decisions.
Report the evaluated sample and limitations; do not claim corpus-wide recall
without a suitable reference set. Improving selection is a Phase 1 deliverable;
a learned classifier is not required.

Completion evidence: discovery resumes correctly; candidate origin and selection
are inspectable; the pilot manifest is approved and versioned; selection weaknesses
and a follow-on improvement path are recorded.

Learning: HTTP clients, pagination, iterators, normalization and deterministic rules.

## P1-05 — Identity, versions and citations

Use reliable identifiers/metadata to associate document versions with one logical
paper. Prefer an eligible published version; use an eligible preprint when necessary.
Record the actual evidence version. Keep uncertain matches separate for review.

Retain real citation relationships with unresolved external identifiers before
full metadata exists. Enrich those records through bounded metadata requests;
never invent a title or automatically acquire referenced full text. Ensure the
schema supports these references without pretending they are complete papers.

Completion evidence: repeated inputs avoid duplicate logical records; version
selection is explainable; uncertain matches and unresolved references have tested,
explicit representations.

Learning: identity versus representation, normalization and referential integrity.

## P1-06 — Acquisition and artifact storage

Build adapters for explicitly supported download sources. Verify current source
access terms and limits before acquisition. Record acquisition/indexing permission
evidence separately from public passage-display eligibility.

Enforce timeouts, bounded retries and streamed size limits. Validate destinations
and redirects to avoid unintended private/local-network requests. Validate returned
content instead of assuming an HTTP success contains a valid PDF. Detect incomplete,
invalid or oversized downloads. Publish completed artifacts atomically from temporary
files; retain checksums, source URLs, acquisition time and document-version links.

Keep unique originals once, share them across collections and compress extraction
outputs. Choose a local artifact root outside Git, configure its runtime mount,
and explicitly ignore generated data/model/index paths. Retain metadata-only records
separately from acquisition failures. Regenerate disposable page images when practical.

Completion evidence: interrupted writes never masquerade as complete artifacts;
repeated downloads avoid duplicate storage; source provenance resolves; retention
references protect shared artifacts.

Learning: streaming I/O, hashing, filesystem operations, atomic writes and cleanup.

## P1-07 — Ten-paper reference set

Select representative papers across the agreed questions and difficult layouts.
Prepare human-verified samples from every paper before comparing approaches.
Include section/read-order samples, ordinary tables, merged headers, tables spanning
pages, numeric values and header associations, captions, units, footnotes and locations.

The assistant may help draft the annotation format/checking instructions; the user
verifies selected evidence against PDFs. Version the sampling rules, annotations
and corrections. Use permitted fixtures and keep restricted full text outside Git.

Completion evidence: a versioned reference set with explicit checked coverage and
expected results independent of parser outputs. Record sample counts and limitations;
this is not a claim of exhaustive checking of every page/cell.

Learning: reference data, annotation consistency, sampling and evaluation bias.

## P1-08 — Extraction comparison and decision

Compare structured document conversion with a local vision-model approach using
pinned configurations on the reference set. Docling pipelines are candidates,
not selected dependencies. Provider-parsed text may also be evaluated but must
meet the same evidence requirements.

Measure text omissions/read-order errors; table values, structure and contextual
accuracy; source-location correctness; runtime; peak RAM/VRAM; artifact sizes;
and failure/recovery behavior. Preserve figures/captions/equation regions where
available, assess interpretation capability, and explicitly decide its phase scope.

Record a justified pipeline or combination/fallback decision. Do not assume a
model fits the laptop or that structured output guarantees accuracy. If candidates
fail quality/resource needs, investigate and return the scope tradeoff to the user.
Set numerical acceptance criteria after this assessment and before judging the
100-paper run; record their definitions, denominators and checked sample.

Completion evidence: comparison artifacts, reproducible commands/configurations,
resource measurements, accepted extraction decision and quality thresholds.

Learning: adapters, controlled experiments, measurement and error analysis.

## P1-09 — Evidence normalization and chunking

Define source-location conventions: actual document version, page numbering,
coordinate system when available and offsets into retained normalized text.
Represent missing location detail explicitly rather than fabricate coordinates.

Respect section boundaries for prose. Preserve table cells and header relationships;
include captions, units and footnotes in searchable context. Split large tables into
row groups with relevant headers repeated, linked to the complete structured table.
Keep derived searchable text linked to retained evidence, not only model summaries.

Evidence identities must distinguish changed documents/extractions while remaining
stable across equivalent retries. A results-table validation failure blocks successful
ingestion of the paper until resolved. Keep usable intermediate outputs for retries
or reviewed corrections with provenance. Any eventual exclusion is a recorded
selection decision, not silent quality filtering.

Completion evidence: inspectable source-linked evidence, repeatability checks,
section/table boundary tests and a versioned chunking configuration.

Learning: immutable identities, structured data transformations and boundary cases.

## P1-10 — Embeddings, index integrity and rebuild

Choose an initial locally runnable embedding model through pilot measurements;
full retrieval-quality comparison remains Phase 2. Record model/revision, dimensions,
preprocessing, input limits and batching configuration.

Implement bounded embedding batches and repeatable Qdrant upserts. Payloads must
resolve evidence, paper, document version, configuration, collection/snapshot and
filterable metadata to authoritative records. Separate incompatible embedding/index
configurations. Define reconciliation after partial cross-store writes; do not
pretend PostgreSQL and Qdrant share an atomic transaction.

Provide index validation/rebuild from retained evidence and configuration, plus a
small local inspection/query command. Verify IDs, counts and source resolution;
bit-identical model outputs are not assumed unless the runtime supports that claim.

Completion evidence: retry-safe upserts, partial-write recovery, configuration mismatch
checks and a successful rebuild with expected evidence membership and provenance.

Learning: embeddings as derived data, batching, adapters and cross-store consistency.

## P1-11 — Runner, recovery and snapshot lifecycle

Provide terminal operations for start, status, resume, targeted retry, draft-evidence
inspection, validation/finalization, index rebuild, storage inspection and cleanup preview.
Choose command spelling during implementation and document it; these names are capabilities,
not a locked CLI syntax.

Build the runner over reusable application services. Allow one active ingestion
process initially with ownership/concurrent-start protection and explicit crash recovery.
Bound download concurrency and control extraction/embedding batches. The process stops
when terminated; persisted progress supports resumption rather than background execution.

Checkpoint successful stages and output fingerprints. Invalidate only affected
downstream work on configuration/input changes. Continue other papers after
paper-specific errors; pause on shared database/storage failures. Preserve stage and
reason for targeted retries, with explicit pending/partial/completed/failed/skipped outcomes.

Draft snapshots are inspectable/testable. Finalize explicitly only after validating
fixed membership, selected document/extraction versions, effective configurations
and index integrity. Normal research consumes finalized snapshots. New evidence
or configuration changes produce a new snapshot rather than silently altering one
used by retained runs. A smaller valid snapshot does not satisfy the 100-paper target.

Completion evidence: interruption/resume, targeted retry, duplicate-start rejection,
stale ownership recovery, finalization rejection and immutable finalized references
are demonstrated by tests.

Learning: state machines, CLI design, ownership and idempotency.

## P1-12 — Operational visibility and storage controls

Record job/document/stage IDs, durations, counts, retries, failure categories,
configuration IDs and resource measurements. Keep availability (metadata-only/full
text), processing outcome and snapshot lifecycle distinct. Avoid logging secrets
or disallowed source content.

Measure the 10-paper footprint; configure a cap before scaling. Pause new acquisition
at the limit. Clean temporary/disposable outputs promptly; protect artifacts shared
across collections or referenced by retained snapshots/runs. Make cleanup inspectable
and retirement explicit. Test interrupted cleanup and accounting consistency.

Completion evidence: failures can be explained from recorded events, the pipeline
respects resource limits, and cleanup preserves shared/retained evidence.

Learning: structured observability, accounting, retention and operational diagnostics.

## P1-13 — Verification suite and CI

Build tests alongside each behavior. Use small synthetic/permitted fixtures,
isolated PostgreSQL/Qdrant services and deterministic substitutes for network/model
boundaries in ordinary CI. Run real-model quality/performance experiments separately.

| Area | Required cases |
| --- | --- |
| Configuration | Validation, serialization, stable configuration identity, stage invalidation |
| Discovery | Pagination, duplicate results, interruption, malformed metadata, throttling |
| Acquisition | Interrupted/atomic writes, invalid content, streamed size bounds, unsafe redirects, checksum reuse |
| Identity | Published/preprint preference, uncertain matches, unresolved citations |
| Evidence | Missing content, incorrect table associations, source locations, chunk boundaries |
| Persistence | Migration failure/retry, constraints, stage transitions, snapshot immutability |
| Indexing | Partial writes, repeat upserts, incompatible configuration, orphan detection, rebuild |
| Operations | Cancellation, targeted retries, concurrent starts, storage exhaustion, safe cleanup |
| Security | Secret-safe logs, untrusted document handling and download destination controls |

Confirm public test boundaries with the user when using the TDD skill. Expectations
must describe behavior rather than repeat implementation logic. Run hosted CI on the
actual completed revision, retaining GPU/network-heavy benchmarks as separate evidence.

Completion evidence: relevant cases pass in the documented small profile and hosted
CI, with reference/model evaluation results linked independently.

## P1-14 — Hundred-paper acceptance and documentation

Freeze the selected configuration and reviewed manifest, then run the full pipeline.
Use automated integrity checks for every paper and a documented manual sample for
quality assessment. Report precisely what was checked; do not imply every table cell
was manually verified.

The report must include discovery/shortlist/selection/exclusion counts; coverage
across the three questions; source and published/preprint distribution; metadata-only,
failed, skipped, partial and completed counts; extraction metrics/sample sizes;
processing time/RAM/VRAM/storage/retries; and integrity/rebuild outcomes. Preserve
reasons for any replacement or exclusion. Only accepted full-text papers count toward 100.

Document setup, permitted source access/credentials, execution profiles, CLI usage,
interruption/retry, configuration changes, cleanup, rebuild and benchmark reproduction.
Update README, the learning handoff and source of truth with actual outcomes.

Completion evidence: accepted report and finalized 100-paper snapshot with usable
text/table evidence, quality gates satisfied, all indexed sources resolvable,
recovery/rebuild demonstrated, storage bounded and CI passing. State limitations
and Phase 2 inputs without claiming later retrieval or generation capabilities.

## Explicitly open decisions and their decision points

| Decision | Resolve when |
| --- | --- |
| Exact source adapters, access limits and per-source permissions | Before acquiring the reference set; inspect current official terms/docs |
| Exact schema, artifact paths and CLI/library choices | At the corresponding implementation task; record material decisions |
| Parser/local vision model and fallback | Ten-paper comparison |
| Numerical quality thresholds and manual sampling protocol | After reference assessment, before 100-paper acceptance |
| Chunk sizes/table row-group sizes and initial embedding model | Pilot measurements and recorded configuration |
| Storage cap and disposable retention periods | Ten-paper footprint assessment, before scaling |
| Plot/equation interpretation scope | Pilot assessment |
| More advanced selection/classifier and expansion criteria | Review initial shortlist results; beyond the required explainable baseline |
| Background scheduling and ingestion API integration | Later operational need; preserve the eventual API contract |

## Research starting points

Verify current terms/model requirements when the relevant task is reached:

- [OpenAlex full text](https://help.openalex.org/access/fulltext/)
- [arXiv bulk access](https://info.arxiv.org/help/bulk_data.html)
- [Docling document model](https://docling-project.github.io/docling/concepts/docling_document/)
- [Docling vision pipelines](https://docling-project.github.io/docling/usage/vision_models/)
