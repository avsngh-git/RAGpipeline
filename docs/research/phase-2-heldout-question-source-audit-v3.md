# P2-12.3 held-out question source audit

**Reviewer:** assistant · **Date:** 2026-09-27 · **Status:** active v3 split q22–q31; source review and candidate relevance review are complete. The historical v1/v2 records are retained for audit, and q21 is excluded after the integrity incident below. This is a source and review record, not a report of held-out retrieval scores.

The active v3 split retains q22–q30 with a scope clarification for q22 and adds source-checked q31. `benchmark-heldout-questions-v3.toml` is bound by SHA-256 in `benchmark-split-v3.toml`. q21 remains in the v1 files solely as an audit record and is excluded from tuning and acceptance. Source review details for q22–q30 and q31 remain in the private local review records; the sanitized q31 source check is recorded in `phase-2-heldout-replacement-q31-source-audit.md`.

## Coverage

| Category or evidence floor | Families | Count |
| --- | --- | ---: |
| Discovery | q28, q30, q31 | 3 |
| Specific evidence | q22, q23, q24, q26, q27, q28, q29, q31 | 8 |
| Table results | q22, q23, q29 | 3 |
| Cross-paper comparison | q23, q24, q27, q30 | 4 |
| Filters | q22, q23, q24, q27, q28, q29, q30, q31 | 8 |
| Missing evidence | q25, q26, q27 | 3 |
| Numeric table questions | q22, q23, q29 | 3 |
| Direct positive prose anchors | q24, q28, q31 | 3 |
| Negative or mixed cases | q22, q25, q26, q27 | 4 |

These are purposive families from this snapshot. The ten held-out families support directional paired comparisons; they do not estimate small effects precisely.

## Source checks

| Family | Source locations checked | Source-grounded target |
| --- | --- | --- |
| q21 (excluded) | M3-Embedding abstract, PDF page index 0; accepted PDF SHA-256 `b16708f475d64bcace839d7af7556a034bd35b066df6f80b84586a7aa474cbf8` | Three design dimensions, dense/sparse/multi-vector functions, and its 8,192-token long-input limit. [ACL PDF](https://aclanthology.org/2024.findings-acl.137.pdf) |
| q22 | *Is Semantic Chunking Worth the Computational Cost?*, Table 1, page index 3; SHA-256 `6e6b45b3d08b08f514df36544bd15564dc9153e56d0313a811f83246764e8657` | The visually checked MIRACL* row reports Fixed-size 69.45, Breakpoint 81.89, and Clustering 67.35 F1@5; the caption says starred datasets were stitched. The snapshot lists this work's publication year as 2025; the query describes that snapshot filter explicitly. [arXiv record](https://arxiv.org/abs/2410.13070) |
| q23 | M3-Embedding, Table 3, page index 7; mGTE, Table 4, page index 4; SHA-256 values `b16708f475d64bcace839d7af7556a034bd35b066df6f80b84586a7aa474cbf8` and `42bed71334f634f5ff7f0464866fa5dc843a331daffa8014e9b09a5582aba914` | Visual review confirms the MLDR nDCG@10 context and 8,192 input lengths. M3 reports Dense 52.5 and Sparse 62.2; mGTE-TRM reports Dense 56.6 and Dense+Sparse 71.3. These are reported results from separate papers, with each table's variants and headers retained in the source record. [M3 ACL PDF](https://aclanthology.org/2024.findings-acl.137.pdf) · [mGTE ACL PDF](https://aclanthology.org/2024.emnlp-industry.103.pdf) |
| q24 | Query2doc and Rewrite-Retrieve-Read abstracts, page index 0; SHA-256 values `b3026d44fed97a360bfa269d9e028a6ff233fa89b119bf823e1fe0f16963db86` and `47f985749bc248b330dd5b965a2c072413017972523f052c5702ae22f3bd75e3` | Query2doc generates a pseudo-document with an LLM and uses it to expand the query; Rewrite-Retrieve-Read adapts the query before retrieval using a trained rewriter. [Query2doc ACL PDF](https://aclanthology.org/2023.emnlp-main.585.pdf) · [Rewrite-Retrieve-Read ACL PDF](https://aclanthology.org/2023.emnlp-main.322.pdf) |
| q25 | Full-text screen of all accepted PDFs; the review paper's discussion at page indices 3 and 44; SHA-256 `969ab6c0ec868975b4449b40fec1505478da7b023f9f8300ca77d53368190df4` | The review mentions prompt injection as a retrieval security risk and calls for evaluation standards. The accepted-snapshot scan and source checks found no direct retrieved-instruction attack evaluation. The screen is bounded to this accepted snapshot and its recorded terms. |
| q26 | Full-text screen of all accepted PDFs; *Improving the Domain Adaptation of RAG Models* page indices 3–4; systematic-review discussion at page indices 22–23 and 28; accepted checksums are in the private review record | Re-index mentions in the matched papers concern training, pre-indexed representations, or graph-RAG discussion. The closest review passages identify an update-evaluation gap or say the effect on answer drift is unknown. No reviewed passage measured whether revising or deleting a source after persistent indexing leaves stale evidence in retrieval or answers. |
| q27 | QA-RAG testbed and results, page indices 7 and 10; FLARE retrieval procedure, page index 3; systematic-review metrics discussion, page index 29 | QA-RAG tests 500 questions whose answer is absent from its knowledge base and reports rejection counts. FLARE uses low generation confidence to trigger retrieval. The all-PDF screen found abstention and unanswerable-query work, but no accepted study in the recorded screen reported the asked-for calibrated evidence-sufficiency threshold with a risk–coverage result. This distinguishes refusal evaluation from retrieval triggering. [QA-RAG publisher paper](https://www.mdpi.com/2504-2289/8/9/115) · [FLARE ACL PDF](https://aclanthology.org/2023.emnlp-main.495.pdf) |
| q28 | PDFTriage querying method, page index 4; Table 4, “Positive Examples for Question Categories,” page index 10; SHA-256 `0e097ce70a849dbd4840edc79d1dd8d2607512cc0d9751243a20df0058b33f19` | The source describes page, section, table, figure and general retrieval operations. Table 4 includes `TableReasoning` and `StructureQuestions` rows. The query avoids document-count statements that differ across the paper. [ACL PDF](https://aclanthology.org/2024.emnlp-industry.13.pdf) |
| q29 | Structure-Aware Chunking, Table 4, page index 9; SHA-256 `85da766693abffe66e0446675b8b6b9059d6727474786c66d07e9b32f1acbe16` | The table was visually checked. Proposed Method reports Faithfulness 0.78, Content Precision 0.92, and Answer Accuracy 0.73; Baseline 2 reports Faithfulness 0.81. [Journal article](https://www.ijournalse.org/index.php/ESJ/article/view/3380) |
| q30 | FIRST Table 1 and caption, page index 5; ListT5 Table 2 header and caption, page index 4; SHA-256 values `fca02e77ff691f6de93cc21bfd5dfc56ea925b73c25f3e8dee50a1b67df67296` and `1c6ef8eb4a223db760ff2243addd357fc6094d0b5d6c62635439fad7f9900396` | Visual checks confirm FIRST uses Contriever's top 100 BEIR passages and reports nDCG@10; ListT5 reports BM25 Top-100 and Top-1000 settings and nDCG@10. This question asks for reported evaluation conditions, not a controlled score comparison. [FIRST ACL PDF](https://aclanthology.org/2024.emnlp-main.491.pdf) · [ListT5 ACL PDF](https://aclanthology.org/2024.acl-long.125.pdf) |
| q31 | *Found in the middle: Calibrating Positional Attention Bias Improves Long Context Utilization*, abstract, PDF page index 0; accepted PDF SHA-256 `d18854e7dcf46489fe7708e15151a1608f523f23f083175787875ad6a7a3038e` | The abstract states that attention follows a U-shaped positional bias favoring beginning and end tokens regardless of relevance, and that found-in-the-middle calibration helps attend to relevant context in the middle according to relevance. The exact accepted extraction and source spans were checked before q31 pooling. [ACL Anthology paper](https://aclanthology.org/2024.findings-acl.890/) |

## Missing-evidence screen and limits

The source scan verified all 100 selected PDF checksums and searched the text layer of 1,705 pages; each PDF had extractable text. It used predeclared phrase lists for prompt injection, corpus/index freshness, and abstention/calibration terms. The q25 screen matched one paper on two pages; q26 matched seven papers on 24 pages after including re-index terminology; q27 matched 16 papers on 64 pages for broad abstention/unanswerable terms. The scan retained all matching paper/page identities privately. Manual checks focused on the closest source passages: the q25 review mentions, the q26 training/re-index and graph-update passages, and the q27 QA-RAG, FLARE, and review examples. Repeated hits on the same broad terms were not each treated as independently reviewed labels.

A text-layer phrase scan can miss differently worded material, tables encoded only as images, or work outside the accepted snapshot. Therefore q25 and q26 mean “no direct support found under this recorded snapshot-bounded review,” not “the literature contains no such work.” q27 is a bounded comparison of the reviewed abstention-related examples, not a general safety claim.

The active v3 q22–q31 cards contain 1,581 evidence candidates and 245 paper candidates; every candidate has a resolved label. The active source-judgment manifest has 21 anchors mapped to 34 review-candidate links, reserved through an independent source-found channel and not inserted into system rankings. q25 and q26 each reached the 200-evidence-candidate cap. Historical v1 counts remain in the restricted run records; q21 is excluded. No held-out scores have been used for configuration choices. See the [source coverage audit](phase-2-benchmark-source-coverage-audit.md) and [dataset card](../reference/phase-2-benchmark-dataset-card.md).


## Heldout integrity incident

On 2026-09-27, a broad filename glob used while sampling q21 review cards also opened q21's private origin ledgers, exposing retrieval ranks and scores to the reviewer. This was accidental. q21 is excluded from heldout tuning and acceptance, and its cards and result records must not be used to complete Phase 2. No heldout score was used to choose a configuration. Versioned v2 manifests retained q22–q30 and added the independently source-checked q31 before replacement retrieval. Active v3 binds the q22 scope clarification and q31 replacement before v3 pooling. Other heldout origin ledgers remain outside the review path.
