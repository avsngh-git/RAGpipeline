# Phase 1 extraction reference protocol

**Protocol version:** 1.0  
**Status:** Human-verified ten-paper reference set; used in the P1-08 comparison

## Purpose and review boundary

This protocol defines reference annotations that are independent of the parser
outputs. The reviewer checks every sampled source passage and table directly
against the selected PDF. Do not treat parser output as the expected answer.

The assistant can prepare the annotation files and comparison reports. A human
must verify the PDF evidence and record corrections before either extraction
approach is evaluated. Keep source PDFs and any restricted full-text annotations
outside Git. The user confirmed all ten selected prose/table samples and their
locations against the PDFs on 2026-09-24; this confirmation clears the P1-07 gate.

## Sample selection

1. Start with at most ten papers from a human-approved, versioned manifest.
2. Record the exact document version, source URL, checksum and permission review
   for each selected file. Prefer an eligible published version, then an eligible
   preprint.
3. Cover the three agreed questions: hybrid versus dense retrieval, reranking
   quality/latency, and chunking/citation support. Include negative or mixed
   findings where the approved shortlist provides them.
4. Across the ten files, seek these layout cases: ordinary table, multi-page
   table, merged or grouped header, numeric cell with units, caption and
   footnote association, two-column prose/read order, and figure/equation regions.
   Record unavailable cases as coverage gaps; do not invent examples.
5. Sample from the source before running either parser. For each paper, annotate
   at least one prose section and, when present, one substantive table. Record
   papers without usable tables as such instead of excluding them silently.

## Annotation record

Keep one JSON record per paper. The local reference data directory is excluded
from Git so it can contain source-specific annotations where needed.

```json
{
  "protocol_version": "1.0",
  "reviewer": "human reviewer identifier",
  "reviewed_at": "2026-09-23T12:00:00Z",
  "paper": {
    "openalex_id": "W123",
    "doi": "10.example/example",
    "document_version_id": "database UUID",
    "version_kind": "published",
    "source_url": "https://source.example/paper",
    "artifact_sha256": "64 lowercase hexadecimal characters"
  },
  "coverage": {
    "hybrid_dense": "covered",
    "reranking_latency": "gap",
    "chunking_citation": "covered",
    "layout_cases": ["ordinary_table", "multi_page_table"]
  },
  "sections": [
    {
      "sample_id": "section-001",
      "heading_path": ["3", "Results"],
      "page_index_zero_based": 4,
      "printed_page_label": "5",
      "expected_text_file": "W123/section-001.txt",
      "source_location_checked": true,
      "read_order_checked": true,
      "review_note": "Synthetic schema example; replace with a PDF-checked note."
    }
  ],
  "tables": [
    {
      "sample_id": "table-001",
      "caption": "Synthetic example caption",
      "units": "milliseconds",
      "page_indices_zero_based": [7, 8],
      "continued_across_pages": true,
      "footnotes": ["Synthetic example footnote."],
      "header_rows": 2,
      "cells": [
        {
          "row": 0,
          "column": 0,
          "text": "Method",
          "row_headers": [],
          "column_headers": [],
          "merged_range": [0, 0, 1, 0]
        },
        {
          "row": 2,
          "column": 1,
          "text": "42.1",
          "row_headers": ["Method A"],
          "column_headers": ["Latency"],
          "merged_range": null
        }
      ],
      "caption_association_checked": true,
      "units_association_checked": true,
      "footnotes_association_checked": true,
      "numeric_values_checked": true,
      "source_location_checked": true
    }
  ],
  "corrections": [],
  "review_complete": false
}
```

The sample text files are retained only in the ignored local reference directory.
Page indices are zero-based PDF positions; printed page labels remain separate.
Use coordinates only when the chosen parser provides a documented coordinate
system. Leave unavailable coordinates absent instead of estimating them.

## Review checklist

For every sampled section, compare heading path, text omissions, paragraph order,
page location and source version. For every table, compare caption, row/column
count, cell strings and numeric values, repeated or merged headers, units,
footnotes, page spans and header associations. Record the observed error and a
correction rather than replacing the source truth with a parser result.

Store parser name/revision, configuration ID, output checksum, run time and peak
RAM/VRAM beside the reviewed annotations. Resolve disagreements by returning to
the PDF and retain the correction history. Report counts and limitations; the
sample is not an exhaustive audit of every page or table cell.

## Current state

The protocol and ten-paper annotation set are complete for the sampled evidence.
The sample was approved and acquired on 2026-09-24; checksums and permission
evidence are in the [acquisition inventory](../../manifests/phase1-discovery-v1-pdf-acquisition.json).
The user confirmed the titles, page locations, prose passages, table captions and
selected table values against the local PDFs. The correction in W4410600121 was
accepted. The per-paper confirmations and sample content are stored in the
ignored [local review packet](../../local-reference/phase1-discovery-v1/review-draft.md).
This is a reference set of ten short samples, not an exhaustive audit of every
page, figure, equation, table or cell in those papers.
