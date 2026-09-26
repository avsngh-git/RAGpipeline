# ADR-0004: Phase 1 PDF extraction strategy

- Status: Accepted for the Phase 1 100-paper pilot
- Date: 2026-09-24

## Context

P1 requires source-linked prose and structured result tables while running on a
laptop with 4 GiB of GPU memory. The parser was OPEN until comparison on ten
human-reviewed PDFs. The measured sample covers 19 annotated pages from 280
pages and must not be treated as exhaustive parser validation.

The standard Docling PDF pipeline and the local Granite-Docling VLM pipeline
both recovered every annotated prose passage and page position. Standard
conversion took 30.437 seconds, returned 57/66 selected numeric values and had
98% mean caption coverage. The VLM took 908.855 seconds, returned 60/66 numeric
values and had 88% mean caption coverage. Both completed without parser errors.

On the sparse two-header table W4404782883, the standard pipeline retained a
26×8 grid and header markers but found only 3/12 selected numbers. The VLM found
11/12, but returned a differently shaped 25×11 grid with no header markers.
The candidates do not provide enough evidence to safely merge those cells and
preserve their row/header relationships.

## Decision

Use Docling `StandardPdfPipeline` as the automatic Phase 1 extractor, pinned to
Docling 2.130.0. Record the effective pipeline options and installed relevant
dependency versions in each extraction configuration. Use local
Granite-Docling 258M only as a diagnostic/review aid for tables flagged by this
pilot heuristic: at least two consecutive column-header rows and at least 20%
blank grid positions. The heuristic flagged one of ten reference tables.

Never merge or substitute VLM table cells automatically. A flagged table needs a
human header/value association check before being treated as verified evidence.

Phase 1 preserves figure captions and parser-recognized equation text with source
locations. It does not interpret figure pixels or create chart summaries. The
original permitted PDF remains the source for visual inspection.

Use the numerical and human-review acceptance gates in
[the comparison report](../reference/phase-1-extraction-comparison.md). Revisit
the heuristic, parser or threshold only with new measured evidence and a revised
ADR.

## Alternatives considered

1. **Standard pipeline only, with no vision review.** Fastest, but the reviewed
   sparse multi-header table lost most selected values without a diagnostic path.
2. **Granite-Docling for every page.** Improved numeric presence by 4.5 percentage
   points but was about 30× slower and had lower caption coverage. It also lost
   table-header markers in the table where it recovered the most values.
3. **Automatically replace standard tables with VLM tables on flagged pages.**
   Rejected because the different grid shape and missing header markers make
   row/column association unsafe to infer.
4. **Use another parser.** Deferred; the tested candidates already meet prose and
   page-location goals, while this pilot identifies a precise table-layout
   failure mode for a targeted review gate.

## Consequences

Docling remains an optional dependency and is lazily imported. Ordinary CI does
not download parser weights or require a GPU. Extracted text and tables retain
zero-based PDF page positions and normalized top-left bounding boxes where
Docling supplies geometry. The source PDF remains the authoritative figure
image.

The adapter removes U+0000 sentinels from extracted strings before they
reach PostgreSQL text or JSONB fields, and resolves Docling `RefItem` values
through `reference.resolve(doc=document)`. Oversized table rows are chunked into
cell-level passages that repeat applicable row and column headers; the stored
structured table remains unchanged.

The pilot heuristic is intentionally narrow and based on one positive example.
It does not prove that all problematic tables will be detected. The 100-paper
acceptance run must report the number of flagged tables and manually inspect all
flagged tables plus a stratified sample of 20 other tables (or all if fewer than
20 are available). Numeric coverage alone does not prove that a value is linked
to the correct method or header.
