# Phase 2 calibration set

| Field | Value |
| --- | --- |
| Version | 1 |
| Reviewed | 2026-09-26 |
| Reviewer | assistant |
| Split | All ten families are development material |
| Snapshot | 4b11fab3-d4a5-4e7a-a58e-8654accf2c6c |

This file records paraphrased questions, source-grounded judgments and workload
decisions. Its validated machine-readable companion is
[calibration-v1.toml](../../benchmarks/phase2/calibration-v1.toml). It contains no
source excerpts or table values. The accepted PDFs are
stored locally; each source below is pinned by its SHA-256 and zero-based PDF page.
The original PDF page controls when extracted text or table metadata disagrees.

## Judgment rules used

Paper relevance and source-evidence relevance are separate ordinal labels:

| Label | Meaning |
| --- | --- |
| 0 | Does not support the requested information |
| 1 | Useful context or incomplete support |
| 2 | Directly supports a requested part |

For a table result, direct evidence includes its dataset/model row, metric and cutoff
column, units or limits where relevant, and footnote or benchmark context needed to
interpret the cell. A favorable result is not required for label 2. Every new
judgment here is assistant-reviewed; none is represented as human-validated.

## Calibration question families

### Q01 — Retrieval-method discovery

**Category:** discovery; specific evidence

**Question:** Which paper in this snapshot evaluates retrieval methods on TREC-DL19
and TREC-DL20, and what methods and ranking metrics does its results table compare?

**Paraphrased answer:** Searching for Best Practices in Retrieval-Augmented Generation.
Its retrieval table separates the two benchmarks and reports multiple ranking metrics
and latency for the listed retrieval methods; the paper also marks possible retriever
training overlap in the table context.


**Paper judgment:** W4404782883 = 2.

**Evidence group G1:** Table 7, source B1, page index 15 = 2. Dataset headings,
retrieval-method rows, ranking-metric columns and latency are all required.

### Q02 — Positive-passage position

**Category:** specific evidence; table result

**Question:** How does ListT5 behave when the positive passage moves among the input
positions on TREC-COVID and FiQA, compared with the listed reranking baselines?

**Paraphrased answer:** Its position sensitivity is lower in the reported comparison,
with stronger agreement and lower position-to-position variation; the two dataset
blocks and all position columns still need to be checked.


**Paper judgment:** W4402671832 = 2.

**Evidence group G1:** Table 4, source L1, page index 6 = 2. Match each method row to
the dataset block, positive-passage position, standard-deviation and agreement columns.

### Q03 — Hybrid-search setting

**Category:** table result; mixed finding

**Question:** Does one hybrid-search alpha maximize both mAP and nDCG@10 on both
TREC-DL test sets?

**Paraphrased answer:** No. The preferred row differs by metric on one benchmark,
while the two metrics share a preferred row on the other. There is no setting that
universally wins both metrics across both benchmarks.


**Paper judgment:** W4404782883 = 2.

**Evidence group G1:** Table 9, source B2, page index 16 = 2. Compare the alpha rows
under both metric columns separately inside each benchmark block; do not infer from
bolding in only one block.

### Q04 — Cross-paper metric scope

**Category:** cross-paper comparison

**Question:** What does the TREC retrieval table in Searching for Best Practices
measure, and how does that differ from RadioRAG’s radiology-QA statistical table?
What can each table establish, and why should their scores not be compared directly?

**Paraphrased answer:** The first reports retrieval-ranking measures and latency on
TREC-DL benchmarks. RadioRAG reports answer accuracy and pairwise statistical tests
for two radiology-QA datasets. Their task definitions and scales differ, so the
numerical scores are not directly comparable; each supports a conclusion only in its
own evaluation setting.


**Paper judgments:** W4404782883 = 2; W4402853403 = 2.

**Evidence group G1:** Searching for Best Practices Table 7, source B1, page index
15 = 2.

**Evidence group G2:** RadioRAG Table 3, source R1, page index 14 = 2. G2 requires
the dataset section, model-accuracy column, p-value block and its comparison note.

### Q05 — Publication-year filter

**Category:** filters; specific evidence

**Question:** Restrict to papers published in 2024. Which zero-shot listwise
reranking study tests sensitivity to positive-passage position, and on which datasets?

**Paraphrased answer:** ListT5; the position study covers TREC-COVID and FiQA.


**Paper judgments:** W4402671832 = 2. W4411113004 = 0 for this filtered request because
its publication year is outside the requested range; that does not make it generally
irrelevant to retrieval research.

**Evidence group G1:** ListT5 Table 4, source L1, page index 6 = 2. The inclusive
publication-year filter is metadata; the method and dataset conditions come from the
source paper.

### Q06 — Missing clinical-trial evidence

**Category:** missing evidence; filters

**Question:** Does any paper in the accepted snapshot report a randomized clinical
trial comparing a RAG system with usual care using patient outcomes? Distinguish an
evaluation of clinical queries or clinical/RCT source documents from a trial of the
RAG system in care.

**Paraphrased answer:** No directly supporting source was found in this fixed
100-paper snapshot. The closest sources cover clinical RAG or use clinical-trial
literature, but do not report the requested system-versus-usual-care patient trial.
This is a bounded corpus finding, not a claim that no such work exists elsewhere.

**Paper and candidate-evidence judgments:**

| Paper ID | Paper label | Evidence label | Source check and rationale |
| --- | ---: | ---: | --- |
| W4415813536 | 1 | 1 | Clinical RAG chunking experiment on postoperative questions; the source describes a controlled pipeline comparison and discusses a randomized design as future work. It does not report patient outcomes from a RAG-versus-usual-care trial. |
| W4414925442 | 1 | 1 | Public-health RAG; trial literature is a source type, not a trial of this system. Its answer-generation evaluation is incomplete support for the requested clinical intervention comparison. |
| W4406596702 | 1 | 1 | Clinical-information RAG evaluated on note-extraction tasks; a clinical-trials-network phrase occurs in funding context. Neither is the requested trial. |
| W3121076170 | 0 | 0 | RCT articles are inputs to an explanation-generation task, not an RAG clinical intervention. |
| W4403006857 | 0 | 0 | The RCTS hit is a recursive text-splitting method name, not a randomized controlled trial. |
| W3204250176 | 0 | 0 | The randomization hit concerns a retrieval-model transform. |
| W4402671832 | 0 | 0 | The randomization hits concern training-example sampling and ordering. |
| W4402671970 | 0 | 0 | The randomization hit concerns an indexing method. |
| W4412886806 | 0 | 0 | The randomization hit concerns shuffling benchmark inputs. |

**Evidence groups:** none receive label 2. The three label-1 papers above are useful
near-matches, not positives. No negative label is generalized to all unreviewed
passages in the corpus.

### Q07 — Granularity and downstream QA

**Category:** table result; mixed finding

**Question:** In Dense X Retrieval, does proposition-level indexing lead every
retriever to the best downstream QA result across all datasets and both context
limits?

**Paraphrased answer:** No. The preferred granularity varies across retriever,
dataset and context-limit columns. Keep the closed-book comparator, prompt limit,
retriever class and Exact Match metric attached to each result.


**Paper judgment:** W4404783040 = 2.

**Evidence group G1:** Table 5, source D2, page index 7 = 2. Preserve retriever,
granularity, dataset, exact-match metric and context-limit associations.

### Q08 — QA-similarity table

**Category:** table result; mixed finding

**Question:** In the semantic-chunking paper’s QA Similarity table, does one chunking
strategy have the highest result for every dataset?

**Paraphrased answer:** No. The leading or tied strategy changes across dataset rows.


**Paper judgment:** W4411113004 = 2.

**Evidence group G1:** source S1, page index 12, visually checked crop T075 = 2.
Retain the QA Similarity caption, dataset row, and Fixed-size/Breakpoint/Clustering
column associations.

**Source correction:** The ignored table packet describes this crop as “Table 18:
BERTScore.” The exact accepted PDF crop visibly labels it “Table 10: QA Similarity.”
The calibration anchor follows the original PDF image and its SHA-256, not that
extracted caption. This judgment is tied to the accepted artifact version.

### Q09 — Pairwise significance table

**Category:** table result; negative finding

**Question:** Does RadioRAG Table 3 show a statistically significant difference for
every listed comparison on both datasets?

**Paraphrased answer:** No. Some pairwise cells do not meet the table’s significance
criterion. The comparison direction and significance must be read alongside the
accuracy rows, dataset section and note defining the p-value comparisons.


**Paper judgment:** W4402853403 = 2.

**Evidence group G1:** Table 3, source R1, page index 14 = 2. A p-value alone does
not supply the direction or practical size of an accuracy difference.

### Q10 — Quality and latency trade-off

**Category:** table result; specific evidence

**Question:** In Searching for Best Practices Table 1, does the configuration with
the strongest average quality also minimize latency and lead every individual task?

**Paraphrased answer:** No. The table shows a quality/latency trade-off and task-level
variation; an average cannot replace the task columns.


**Paper judgment:** W4404782883 = 2.

**Evidence group G1:** Table 1, source B0, page index 7 = 2. Keep each task’s metric
separate from the average-score and seconds-per-query columns.

## Source register

All work IDs refer to papers in the accepted snapshot. PDF checksums below were
verified against the local artifacts. Table crops are private local review aids;
their keys identify the reviewed source region. Page indices are zero-based.

| Key | Paper / work ID | Document ID | Accepted extraction ID | Source PDF SHA-256 | Source anchor |
| --- | --- | --- | --- | --- | --- |
| B | Searching for Best Practices in Retrieval-Augmented Generation / W4404782883 | d14ab068-d140-48ab-8f8d-c9745e380982 | 11bd505f-e935-5e7e-aaee-c111d16c49bd | 045d0bf2712448fcadd850760be8eb92c2576b68643a01f52704d15e13e8456e | Table 1 p.7 (T004); Table 7 p.15 (T006); Table 9 p.16 (T008). [ACL Anthology](https://aclanthology.org/2024.emnlp-main.981/) |
| L | ListT5 / W4402671832 | 6f6b8dc9-153c-4f31-9443-7f1496bdc523 | a1ec3b86-a125-5e36-a9ba-c4dd5c6e0d68 | 1c6ef8eb4a223db760ff2243addd357fc6094d0b5d6c62635439fad7f9900396 | Table 4 p.6 (T090); Table 11 p.15 (T091). [ACL Anthology](https://aclanthology.org/2024.acl-long.125/) |
| D | Dense X Retrieval / W4404783040 | 9d3572dd-32b5-4874-acb9-a38330498295 | 715e72c5-0466-5dbb-9a3d-aeb54efd177b | 28296441e7a995a64436dd9e065814faac24a395fd6754ccd2c58149f3ace660 | Table 3 p.4 (T097); Table 5 p.7 (T098). [ACL Anthology](https://aclanthology.org/2024.emnlp-main.845/) |
| R | RadioRAG / W4402853403 | 0a465448-2b15-48ca-a7ee-3cc2c075ca7d | 089489b7-97cf-50bf-9893-b38c40c36807 | 131faf4e0770f295b274b1b6d7fc8e7089b176f6de5aab70c17614aff0a51cc7 | Table 3 p.14 (T071). [RSNA publisher](https://doi.org/10.1148/ryai.240476) |
| S | Is Semantic Chunking Worth the Computational Cost? / W4411113004 | 1fb2e6de-6e8e-40de-b5da-1c46b77b1bda | ff2f4911-65e0-5d8f-a1dc-80b56a57193b | 6e6b45b3d08b08f514df36544bd15564dc9153e56d0313a811f83246764e8657 | Table printed as Table 10: QA Similarity, p.12 (T075). [ACL Anthology](https://aclanthology.org/2025.findings-naacl.114/) |

The T-crop packet uses an older extraction identity for B and L. The identities above
are the current accepted-snapshot extractions; source anchors remain PDF-based and
are tied to the same document and verified PDF checksum. Do not carry the old
extraction IDs into chunk-to-anchor mappings.

### Q06 candidate-source trace

| Paper ID | Document ID | Accepted extraction ID | PDF SHA-256 | Source page indices | Public source |
| --- | --- | --- | --- | --- | --- |
| W4415813536 | b7e2c317-a747-4f84-965d-dae8b608945d | a9edaee6-5e3d-5bf9-a5dc-8fd7bb0df13c | 9f908ec5832122c08f3f37b8373d111bd64c37bfaf67e66a410adcbb7dcb3b50 | 0, 12, 16 | [Publisher article](https://www.mdpi.com/2306-5354/12/11/1194) |
| W4414925442 | ea3d87b9-f647-4256-aa92-3c8605ccc2b3 | 5a0e45f9-6a00-5eb1-9b65-ee010c9ba30d | 06062b5fbb4a21b513020e64e0f9d501e3abfbe3861e3a7e20649ee3acd52741 | 1, 11 | [Frontiers article](https://www.frontiersin.org/journals/public-health/articles/10.3389/fpubh.2025.1635381/full) |
| W4406596702 | 122388d0-892e-4a6c-9e58-a7357151d473 | 15cc707a-d0db-519c-9fb2-d1cba7729893 | 16eb0c33415b3cf8d22112d98998110b0f67b3f54978f0a3825ecee5194a15b2 | 1–8, 9 | [npj Digital Medicine](https://www.nature.com/articles/s41746-024-01377-1) |
| W3121076170 | baca0764-8f59-457d-8893-43b0ca831ca7 | e69e8de5-0f02-5ca1-a09a-1ca0bcaa9a14 | fc8b2f668c5c9585d1fddf6cced827c608d7a4809011634aa3b6d14188f78d69 | 4, 9 | [ACL Anthology](https://aclanthology.org/2021.emnlp-main.301/) |
| W4403006857 | 28c349ee-c79c-4e97-8822-88ffeda97563 | 3968664d-6854-5073-9552-4498d5a90bfd | 49f456c744cac4048018588550bf5ccb68ad29b49442d7bd227f21c9398824cd | 5–7 | [arXiv](https://arxiv.org/abs/2408.10343) |
| W3204250176 | 9ae81271-8629-49a0-8115-e66554f4fd6f | 0c412c28-f723-511b-9de2-ad75a1707a5b | 686024497fb84050880405acd9197094adfa7ac8ea2c1450eb975840fa756eb7 | 7 | Source PDF SHA-256 above |
| W4402671832 | 6f6b8dc9-153c-4f31-9443-7f1496bdc523 | a1ec3b86-a125-5e36-a9ba-c4dd5c6e0d68 | 1c6ef8eb4a223db760ff2243addd357fc6094d0b5d6c62635439fad7f9900396 | 3 | [ACL Anthology](https://aclanthology.org/2024.acl-long.125/) |
| W4402671970 | 99b5e309-be96-4a41-9528-bdfb1344e4e6 | 27a7a023-c879-52d1-b21d-5e3452328c02 | f7c2cb7cb070a2143062bd6a7762fb25ccd4b4582899ff64ab5ddd0b6163bb74 | 3 | Source PDF SHA-256 above |
| W4412886806 | 68a0d60f-0e1e-4719-8dd6-cce5e5535152 | b3d5123c-2415-5948-8bce-d8dbf1ab0df5 | c1a987e84a5ed60b5cf244480e3c68a728da636ab90cab315b58bbf203bebde3 | 3 | Source PDF SHA-256 above |

The accepted PDF page and extracted source locations were checked for all nine
lexical candidate papers. Publisher pages were independently consulted for the
clinical near-matches. The local phrase screen covered all 100 selected extractions
and their table data using randomization/RCT, clinical-trial, controlled-trial,
usual-care and patient/clinical-outcome terms. Term hits were not treated as
positive evidence without reading their source context. Private excerpts and page
images remain under ignored local-reference storage.

## Review effort and benchmark-size decision

The source-review pass ran from approximately 15:10 UTC to 15:42 UTC on
2026-09-26: about 32 minutes for ten families, nine visual table regions across five
answer-bearing PDFs, and the 100-paper missing-topic screen. That is about three
minutes per calibration family including source identification and the corpus-wide
negative-case screen. The screen returned nine unique lexical candidate papers for
the missing-topic query: three useful but incomplete clinical-RAG near-matches, one
RCTS acronym collision, one RCT-as-input-dataset case, and four generic
randomization/sampling mentions. It found no directly relevant clinical trial.

Across the ten families, source review established ten query-paper positive
judgments across five answer-bearing papers; Q06 has no label-2 paper or evidence
candidate. Search-result pools do not yet exist because the retrieval baselines
have not been built. These counts describe source-found calibration evidence, not
system recall or a pooled benchmark.

For P2-12, use 30 families total: 20 development and 10 held-out. Keep all ten
calibration families in development and add ten development families. Require at
least five families per agreed category in development and three in held-out;
categories may overlap within one family. Ten held-out families support directional
paired conclusions only, not a precise estimate of small effects.

Pool the top 50 evidence candidates from each named core profile (BM25, dense,
hybrid, and reranked), canonicalize and deduplicate by source anchor, and review the
full pool up to 200 unique evidence candidates per family. Add independently
source-found positives as judgments, never as retrieved run results. Pool the top
20 paper candidates per profile, up to 80 unique papers per family. Preserve source
rank and profile provenance for analysis, hide them from the source judgment view
where practical, and report judgment coverage and any cap/truncation.

Budget 12 reviewer-hours for creating and reviewing the 30-family source and
retrieval pools (24 minutes per family on average). Recheck the estimate after the
first five newly pooled development families. If observed effort exceeds the
budget, record the actual coverage and obtain a revised size decision before
held-out scoring; do not reduce the held-out set in response to system scores.

All ten calibration families remain development-only. No held-out questions or
scores were used in this decision.
