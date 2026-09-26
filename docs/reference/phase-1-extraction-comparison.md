# Phase 1 PDF extraction comparison

**Run date:** 2026-09-24<br>
**Status:** P1-08 decision recorded for the 100-paper pilot<br>
**Reference set:** 10 user-verified PDFs; 19 annotated pages out of 280 total PDF pages

## Decision

Use Docling `StandardPdfPipeline` as the automatic Phase 1 PDF extractor. Use
Granite-Docling `VlmPipeline` as a **review aid** for tables that the standard
parser flags as sparse and multi-header. The measured review trigger is at least
two consecutive column-header rows and at least 20% blank grid positions. It
flagged one of the ten reference tables, W4404782883.

Do not automatically replace a standard table with the VLM table. On
W4404782883, the standard table has a 26×8 grid, two header rows and 30 cells
marked as column headers. The VLM found more of the selected numeric values, but
returned a 25×11 grid with no cells marked as headers. The row and column
association cannot be reconciled from numeric presence alone. Keep the standard
structure, retain the VLM result only in the ignored comparison/review area, and
require a human to resolve a flagged table before treating it as verified
structured evidence.

This is a pilot choice, not a claim that either parser is generally accurate.
If the 100-paper pilot finds other table layouts or an unacceptable number of
flagged tables, revisit this ADR before changing the extraction contract.

## Quality gates for the 100-paper acceptance run

Score the sample against source-checked annotations, not parser output:

- Every annotated passage must map to its expected zero-based PDF page; target
  **100% page-location accuracy**.
- Ordered normalized prose-token coverage must average at least **95%**, with no
  reviewed prose sample below **90%**.
- Mean normalized caption-token coverage must be at least **90%**.
- Weighted unique numeric-value presence must be at least **95% overall** and at
  least **90% in each human-reviewed table**. Count each distinct expected value
  once; do not average table percentages equally.
- The acceptance sample must include a manual check of table caption, header to
  value association and source page. Review all tables selected by the
  sparse/multi-header rule, plus a stratified sample of 20 other tables (or all
  if fewer than 20 are available). Check up to three representative result cells
  per sampled table against the PDF.
- A parser failure or unresolved table flagged for review cannot be reported as
  successful structured-table extraction. Record partial and failed outcomes
  separately.

These thresholds are extraction gates only; they do not establish retrieval
quality. The 10-paper comparison covers one annotated passage and one table per
paper. Each annotated table is on a single page. Multi-page tables, figure
interpretation and equation-region accuracy are not validated by this set.

## Results

The comparison processed only the 19 source pages annotated in the human-verified
reference set. It did not parse all 280 pages. Both pipelines completed all 19
pages without conversion errors.

| Measure | Standard PDF pipeline | Granite-Docling VLM |
| --- | ---: | ---: |
| Elapsed time | 30.437 s | 908.855 s (15 min 9 s) |
| Peak process RSS | 2,937,028,608 bytes | 2,317,397,616 bytes |
| Peak CUDA reserved | 1,868,562,432 bytes | 1,023,410,176 bytes |
| Serialized parser output | 1,018,293 bytes | 886,763 bytes |
| Ordered prose-token coverage | 100% | 100% |
| Page provenance accuracy | 100% of 366 elements | 100% of 316 elements |
| Mean caption-token coverage | 98% | 88% |
| Unique numeric values found | 57 / 66 (86.4%) | 60 / 66 (90.9%) |
| Selected-row ordered-token coverage, mean | 59.25% | 61.55% |
| Conversion failures | 0 | 0 |

On W4404782883, the standard parser found 3/12 selected numeric values and the
VLM found 11/12. The VLM scored better for that table but had no column-header
flags and a different grid shape. A hypothetical union of numeric values would
be 65/66 (98.5%); this is **not** a measured hybrid table score because the
cells have not been aligned and checked against their headers. Neither parser
alone meets the numeric-value gate on this small set.

The laptop had an RTX 3050 with 4 GiB VRAM. The VLM ran with a CUDA 12.6
PyTorch runtime and peaked at about 0.95 GiB CUDA-reserved memory. A Transformers
warning reported a configured pad token outside the model vocabulary; the run
completed, but the warning remains part of the model-risk record. Standard
conversion was about 30 times faster in this run. Times are local warm-cache
measurements and are not 100-paper runtime projections.

The adapter translated the 19 serialized standard-pipeline page results into
292 source-located text blocks and 11 source-located structured tables without
mapping errors. This checked the Docling-to-project contract; it did not add a
full-document or multi-page-table quality claim.

## Figure and equation scope

For Phase 1, preserve text recognized as formula/equation content and figure
captions with their source page/region when Docling provides one. Keep the
permitted original PDF as the visual source. Do not generate chart summaries,
interpret figure pixels or synthesize figure descriptions. The reviewed samples
contain no separately annotated expected figure/equation output, so accuracy for
those regions remains unmeasured.

## Reproduction

The project runtime stays free of Docling and model-weight downloads. Install the
optional parser in a disposable environment. The final standard configuration ID is
`50699be11867cbf3bbab59a6551c4a649693a15c4ab0d3629cb7fd42391bdfa3`; the VLM
configuration ID is `0b420c39bf8690e037594416d95baba24b29664de1627d09d8e68875dfb7b3f1`.
The comparison used Docling 2.130.0, Docling Core 2.98.0, Docling IBM Models
4.0.3, Docling Parse 7.21.0, RapidOCR 3.9.2, PyTorch 2.14.0+cu126 and
Transformers 5.17.0. Standard layout used the pinned `docling-layout-heron`
commit `8f39ad3c0b4c58e9c2d2c84a38465abf757272d8`; TableFormer used
`docling-project/docling-models` revision `v2.3.0` (resolved commit
`fc0f2d45e2218ea24bce5045f58a389aed16dc23`). The active RapidOCR torch weights
were fingerprinted in the ignored run summary: detection
`fbdc74c97ea7b770ab22cbdc1ba01a52bdf1975efcf3442057356d622b05d54`, classifier
`bfe13860824b3365c0c7f7ccfcddc8ff11645c60051739ff18bc9913f60c98e1`, and
recognition `0107b2ad694ccc9b1db7cf9ed3ffbc93d1795d9e08d9cf823127243a87bce516`.
Granite-Docling was pinned to revision
`982fe3b40f2fa73c365bdb1bcacf6c81b7184bfe`.

## Model and software licenses

The selected model assets are the Docling layout model (Apache-2.0), the
TableFormer assets from the `docling-models` v2.3.0 bundle (its model page lists
CDLA-Permissive-2.0 and Apache-2.0; retain the bundle notices), and RapidOCR
weights derived from PaddleOCR (Apache-2.0 with upstream attribution). The
review-only Granite-Docling model card lists Apache-2.0. These are external
model/data licenses, separate from Python package licenses.

- [Docling layout Heron at the pinned revision](https://huggingface.co/docling-project/docling-layout-heron/tree/8f39ad3c0b4c58e9c2d2c84a38465abf757272d8)
- [Docling models bundle v2.3.0](https://huggingface.co/docling-project/docling-models/tree/v2.3.0)
- [RapidOCR upstream model notices](https://github.com/RapidAI/RapidOCR/blob/main/MODEL_LICENSES.md)
- [Granite-Docling 258M model card](https://huggingface.co/ibm-granite/granite-docling-258M)

```bash
python -m venv /tmp/phase1-docling-venv
/tmp/phase1-docling-venv/bin/pip install -e '.[pdf-vlm]'
/tmp/phase1-docling-venv/bin/pip install \
  --index-url https://download.pytorch.org/whl/cu126 \
  'torch==2.14.0+cu126' 'torchvision==0.29.0+cu126'

/tmp/phase1-docling-venv/bin/python scripts/compare_pdf_extractors.py \
  --pipeline standard --no-resume
/tmp/phase1-docling-venv/bin/python scripts/compare_pdf_extractors.py \
  --pipeline granite-vlm --no-resume
/tmp/phase1-docling-venv/bin/python scripts/score_pdf_reference.py
```

The scripts verify acquisition checksums and human-review status. Full parser
JSON and Markdown and all source annotations remain under Git-ignored
`local-reference/`; the scorer writes metrics only. The installed comparison
environment was disposable and did not change `environment.yaml`, its lock, or
the project’s ordinary dependency set.

## Source references

- [Docling standard PDF and vision pipelines](https://docling-project.github.io/docling/usage/vision_models/)
- [Docling document representation and provenance](https://docling-project.github.io/docling/concepts/docling_document/)
- [Docling GPU configuration](https://docling-project.github.io/docling/usage/gpu/)
- [Granite-Docling 258M model card](https://huggingface.co/ibm-granite/granite-docling-258M)
- [PyTorch CUDA 12.6 wheel index](https://download.pytorch.org/whl/cu126/)
