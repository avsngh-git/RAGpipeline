# Phase 2 benchmark family source leads

**Purpose:** source-first question-design leads from the accepted 100-paper snapshot. This note was prepared before retrieval results were generated and before the family split was assigned. The leads informed the q11–q20 drafts; they are not themselves relevance judgments or source anchors. The split is recorded in `benchmarks/phase2/benchmark-split-v1.toml`, and source review is tracked in the Phase 2 handoff.

## Candidate topics

- **Discovery — retrieval versus long context:** Explore when a direct long-context approach and RAG differ across task, model, and context conditions, including the paper’s proposed routing idea. Accepted paper `W4404783788`, *Retrieval Augmented Generation or Long-Context LLMs? A Comprehensive Study and Hybrid Approach* (EMNLP 2024). Its ACL record describes comparisons across public datasets and models, with quality and cost considerations. A useful family should name a particular condition rather than ask for a broad paper summary.
- **Specific evidence — multilingual, long-context retrieval:** Ask what input-length and model-design choices distinguish the mGTE text representation model and reranker, then probe how evaluation conditions affect the reported retrieval results. Accepted paper `W4404783220`, *mGTE: Generalized Long-Context Text Representation and Reranking Models for Multilingual Text Retrieval* (EMNLP 2024). The official record describes an 8,192-token encoder and multilingual retrieval evaluation; verify exact table context and model comparisons against the accepted PDF before fixing a question.
- **Filters plus cross-paper method comparison — query transformation:** Apply a 2023 publication-year filter, then compare LLM-generated pseudo-document expansion with Rewrite-Retrieve-Read and its learned rewriter. Accepted papers `W4389520758` (*Query2doc*, EMNLP 2023) and `W4389518671` (*Query Rewriting in Retrieval-Augmented Large Language Models*, EMNLP 2023). Their official records describe distinct intervention points and evaluation setups. Compare methods and conditions, not their raw scores, because the tasks and systems differ.
- **Discovery — structured-document QA:** Ask which document structures and question classes motivate retrieval beyond flattened text, and what kind of benchmark the paper reports. Accepted paper `W4404783839`, *PDFTriage: Question Answering over Long, Structured Documents* (EMNLP Industry 2024). The ACL record describes pages, tables, sections, and a multi-category document-QA benchmark. The paper concerns document QA broadly, so keep any family tied to its actual evidence rather than assuming it evaluates scientific-paper retrieval.
- **Table result / mixed finding — source-document identity versus snippet quality:** Explore whether summary-augmented chunking changes document-level retrieval mismatch and text-level precision/recall in the same way, and how generic versus expert-guided summaries compare. Accepted paper `W4416033570`, *Towards Reliable Retrieval in RAG Systems for Large Legal Datasets* (NLLP 2025). The ACL PDF defines separate document-level and character-level retrieval measures and includes comparisons across chunk/summary settings and lexical/semantic mixtures. The question must retain the metric definitions and retrieval depth; a lower document mismatch alone does not establish better passage support.
- **Cross-paper evaluation scope — retrieval versus answer evaluation:** Contrast the evidence unit and evaluation target in `W4403006857` (*LegalBench-RAG*, arXiv v1, 2024) and `W4412945639` (*RAGEval*, ACL 2025). The former is a legal retrieval benchmark centered on source snippets; the latter proposes completeness, hallucination, and irrelevance measures for generated answers. This can test whether a reader distinguishes retrieval quality from generation quality. LegalBench-RAG is a preprint in the accepted snapshot, so describe its publication status accurately.
- **Table-result lead / possible missing-evidence family — scientific result tables:** `W7127049495`, *Structure-Aware Chunking for Complex Tables in Retrieval-Augmented Generation Systems* (Emerging Science Journal, 2026), describes nested table structures in university course documents and evaluates a structure-aware chunking approach. It may ground a numeric table question. It also suggests a bounded missing-evidence question: does the accepted snapshot contain comparable evaluation on scientific-paper result tables, rather than course/catalog tables? That is an open corpus-review question; this note makes no absence claim.

## Additional source checks for development-question candidates

- **q12 — retrieval segmentation metrics:** accepted paper `W4412888476`,
  *Document Segmentation Matters for Retrieval-Augmented Generation* (Findings of
  ACL 2025). The [ACL record](https://aclanthology.org/2025.findings-acl.422/)
  describes summary-guided segmentation and reports retrieval and end-to-end QA
  evaluation. Verify the exact metric names, dataset rows and numeric values against
  the accepted PDF before labeling a table result.
- **q15 — citation-graph screening lead:** accepted paper `W4386576685`, *MTEB:
  Massive Text Embedding Benchmark* ([arXiv record](https://arxiv.org/abs/2210.07316)).
  Its source describes embedding evaluation tasks including retrieval; a local text
  match for “citation graph” is only a screening lead and does not by itself show
  retrieval by traversing verified scholarly citation links. Inspect the matching
  passage and full evaluation scope before deciding this missing-evidence family.
- **q19 — energy-measurement screening lead:** accepted paper `W7114889968`, *A
  Systematic Literature Review of Retrieval-Augmented Generation: Techniques,
  Metrics, and Challenges* ([publisher record](https://www.mdpi.com/2504-2289/9/12/320)).
  The publisher abstract calls for future benchmarks to report energy consumption.
  That is a lead for screening only; it does not establish per-query local energy
  measurement. The publisher page could not be fetched during this check, so detailed
  claims need direct local-PDF review.

These additional checks supported question wording only. They do not assign
relevance labels, source anchors, or unsupported status. Partial source reviews for
q11–q20 are recorded privately under
`local-reference/phase2-runs/benchmark-v1/source-reviews-v1/`. q12 and q14 table
candidate mapping and visual-review limitations are recorded in the
[q12/q14 table audit](phase-2-q12-q14-table-candidate-audit.md); q13 has a
documented source-version count inconsistency, and q20 remains partially unblinded
as disclosed in the handoff.

## Primary-source register

Links below point to the venue or repository record and, where listed, the paper PDF. Accepted IDs and selected versions were checked against the local Phase 1 membership proposal; `publishedVersion` is recorded there unless noted.

| Accepted OpenAlex ID | Primary source |
| --- | --- |
| `W4404783788` | [ACL record](https://aclanthology.org/2024.emnlp-industry.66/) · [PDF](https://aclanthology.org/2024.emnlp-industry.66.pdf) |
| `W4404783220` | [ACL record](https://aclanthology.org/2024.emnlp-industry.103/) · [PDF](https://aclanthology.org/2024.emnlp-industry.103.pdf) |
| `W4389520758` | [ACL record](https://aclanthology.org/2023.emnlp-main.585/) · [PDF](https://aclanthology.org/2023.emnlp-main.585.pdf) |
| `W4389518671` | [ACL record](https://aclanthology.org/2023.emnlp-main.322/) · [PDF](https://aclanthology.org/2023.emnlp-main.322.pdf) |
| `W4404783839` | [ACL record](https://aclanthology.org/2024.emnlp-industry.13/) · [PDF](https://aclanthology.org/2024.emnlp-industry.13.pdf) |
| `W4416033570` | [ACL record](https://aclanthology.org/2025.nllp-1.3/) · [PDF](https://aclanthology.org/2025.nllp-1.3.pdf) |
| `W4403006857` | [arXiv v1 record](https://arxiv.org/abs/2408.10343v1) · [v1 PDF](https://arxiv.org/pdf/2408.10343v1) |
| `W4412945639` | [ACL record](https://aclanthology.org/2025.acl-long.418/) · [PDF](https://aclanthology.org/2025.acl-long.418.pdf) |
| `W7127049495` | [Journal record](https://www.ijournalse.org/index.php/ESJ/article/view/3380) · [DOI](https://doi.org/10.28991/ESJ-2026-010-01-09) |

## Limits and follow-up

Selection used accepted paper metadata and authoritative venue/repository records, not search-result rankings. This source note does not contain relevance labels or evidence groups. q11–q13 have partial source reviews; q12 table rows and q13–q20 still need source review against the exact accepted PDFs, including visual table checks where needed. The Emerging Science Journal page’s title and abstract were available in the publisher search result, but a direct page fetch failed during this check; its detailed results remain unverified and should be treated as a lead only. The legal benchmark comparison also mixes a preprint with a later peer-reviewed workshop paper, so it should test metric scope rather than imply equal publication status or independent validation.
