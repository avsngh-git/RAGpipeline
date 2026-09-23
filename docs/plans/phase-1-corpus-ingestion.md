# Phase 1 — Corpus and ingestion

Status: approved plan, implementation pending. Approved 2026-09-22.

The [project source of truth](../agents/scientific-research-platform-source-of-truth.md)
is authoritative. Its Section 8.6 records the agreed ingestion constraints;
[ADR-0001](../adr/0001-versioned-corpus-evidence.md) explains the architectural tradeoffs.
Terms are defined in [CONTEXT.md](../../CONTEXT.md).

## Outcome and prerequisites

Build a reproducible corpus pipeline that resumes after failure and links every
indexed evidence unit to its authoritative source. Progress from a 10-paper
end-to-end comparison to a 100-paper pilot. These are engineering milestones,
not proof of research coverage or retrieval quality.

The repository currently contains documentation, not the Phase 0 implementation.
First establish the installable Python package, configuration/logging, FastAPI
health/readiness, PostgreSQL and Qdrant Compose services, migrations, test harness,
and CI. Demonstrate the Phase 0 clean-checkout gate before declaring the
ingestion pipeline operational.

## Delivery slices

| Slice | Work | Completion evidence |
| --- | --- | --- |
| 1. Collection manifest | Version discovery queries, filters, snapshot date, reviewed membership and inclusion/exclusion reasons | A reproducible selection with explicit older-paper exceptions and coverage across the three questions below |
| 2. Acquisition and identity | OpenAlex metadata/citations, supported full-text sources, permission records, logical paper/version links, checksums | Downloaded artifacts resolve to metadata and their actual versions; uncertain identity matches remain separate |
| 3. Ten-paper comparison | Structured conversion versus local vision-model extraction, including difficult tables | Human-verified reference results, per-approach quality/runtime/memory measurements, documented selection or combination |
| 4. Evidence and indexing | Section-aware text units, structured table units, versioned chunking/embedding configuration, Qdrant index | Each indexed unit resolves to retained evidence, its document version and source location |
| 5. Recovery and storage | Start/status/resume commands over reusable services, persisted stages, targeted retries, deduplication and cleanup | Interruption/retry and index-rebuild demonstrations; measured disk use and a configured cap |
| 6. Hundred-paper pilot | Run the selected pipeline with frozen configuration and produce the quality report | 100 successfully ingested full-text papers with separately reported failures, skips and metadata-only records |

Each slice includes its relevant checks; reliability is tested as persistence and
indexing are introduced, not deferred until the final pilot. Command names and
schemas remain implementation details; the pilot does not require a background queue.

## Collection coverage and selection

Use these questions to inspect coverage, including negative and mixed findings:

1. When does hybrid retrieval outperform dense-only retrieval?
2. How much does cross-encoder reranking improve retrieval quality, and at what latency cost?
3. How do chunking choices affect evidence retrieval and citation support?

Automated discovery feeds a reviewed pilot manifest. Preserve review decisions
to support later evaluation of automated selection. Improving selection is a
critical follow-on: assess relevance, coverage and selection bias against reviewed
examples before removing manual review. Exact automation methods and targets are open.
These coverage questions are not a substitute for an independent retrieval benchmark.

## Extraction assessment

Prepare the reference set before comparing approaches. Include ordinary tables,
merged headers, and tables spanning pages. Check values against row/column headers,
captions, units and footnotes, along with text omissions and evidence locations.
Store measured quality, latency, peak memory and artifact sizes per document.

Text and tables are required capabilities. Table-heavy papers are included in
the assessment; actual extraction errors require investigation or reprocessing.
Preserve figures, captions and equation regions where available. Assess plot and
equation interpretation during the pilot, then decide its implementation scope.
Neither approach is assumed accurate or feasible on the laptop until measured.

Docling's structured and local vision pipelines are research candidates, not
selected dependencies. Provider-parsed text may be evaluated as an input option;
it does not remove the need for table/provenance validation.

## Recovery and storage checks

- Reingesting unchanged inputs produces no duplicate papers, artifacts or index entries.
- Interrupt acquisition, extraction and indexing; resume without losing completed work.
- Inject a paper-specific failure; other papers continue and the failed stage is retryable.
- Simulate database unavailability and exhausted storage; the run pauses safely.
- Change a parser or embedding configuration; reprocess affected stages without
  silently replacing evidence referenced by a retained snapshot or research run.
- Rebuild Qdrant from retained artifacts and metadata, checking evidence IDs and counts.
- Verify cleanup preserves shared and referenced artifacts while removing disposable files.

Use isolated services and small deterministic fixtures for CI. Real-model quality
and performance comparisons run separately on the measured local hardware profile.

## Pilot report and completion gate

Report discovery and selection counts, coverage, source/version distribution,
full-text eligibility, metadata-only records, completed/failed/skipped/partial
processing, failure reasons, extraction quality, processing time, memory and disk
use. Separate document availability from processing status.

Phase 1 is complete when the 100-paper target is reached, the agreed pilot quality
thresholds are satisfied, recovery and rebuild checks pass, and every indexed
evidence unit resolves to its authoritative source. Failed and metadata-only
papers do not count toward the full-text target. Numerical thresholds must be
recorded after the ten-paper assessment and before judging the larger pilot.

## Decisions deferred to evidence

| Decision | Resolve when |
| --- | --- |
| Exact source adapters and per-source access controls | Verify current source terms/access before acquiring the reference set |
| Parser, local vision model and any combination/fallback | Ten-paper extraction comparison |
| Chunk sizes, table row-group sizes and initial embedding model | Local pilot measurements; record versioned configurations |
| Numeric extraction quality thresholds | After reference-set assessment, before the 100-paper acceptance run |
| Storage cap and disposable-artifact retention periods | Measure the ten-paper run, then configure before scaling |
| Plot/equation interpretation scope | Pilot assessment |
| Automated selection method and acceptance targets | Evaluate against retained review decisions before expanding automation |
| Background queue and API-controlled scheduling | Later operational need; preserve the required eventual ingestion API |

## Research starting points

Recheck current access terms and model requirements before implementation:

- [OpenAlex full text](https://help.openalex.org/access/fulltext/)
- [arXiv bulk access](https://info.arxiv.org/help/bulk_data.html)
- [Docling document model](https://docling-project.github.io/docling/concepts/docling_document/)
- [Docling vision pipelines](https://docling-project.github.io/docling/usage/vision_models/)
