# Phase 2 R8 source-anchor screening

**Status:** preparatory source screen; no question families, labels, pools, or scores created
**Reviewer:** assistant-reviewed source screen
**Reviewed:** 2026-09-28
**Snapshot:** `4b11fab3-d4a5-4e7a-a58e-8654accf2c6c` (accepted Phase 1 100-paper snapshot; see the [acceptance report](../reference/phase-1-100-paper-acceptance-report.md))

## Scope and method

This screen supports planning a new Phase 2 assessment under the [evaluation
protocol](../plans/phase-2-evaluation-protocol.md) and [frozen sampling
plan](../reference/phase-2-benchmark-sampling-plan.md). The protocol requires six
categories, source-checked prose and table evidence, negative or mixed findings, and
separate family-level splits. This report identifies possible sources only. It does
not propose question wording or assign relevance labels.

Membership was checked against the exact finalized snapshot using a read-only
transaction over `snapshot_items` joined to `papers`. The inventory query retrieved
only stable paper ID, title, and publication year; a second query, restricted to the
selected member IDs, retrieved only DOI metadata. The query returned 100 members.
No paper passages, extraction text, Phase 2 question sets, labels, pools, rankings,
per-query results, or raw run artifacts were read.

For each candidate, I checked the publisher, venue, or repository record and the
primary paper or its official full text. The evidence locations below are navigation
anchors for later source review, not final annotation coordinates. Source outcome
tags summarize the publication’s reported result and are not benchmark outcomes.

The tracked public source leads and coverage notes were used to avoid their disclosed
family subjects, including long-context comparisons, multilingual representation,
query transformation, structured-document QA, legal-document chunking, retrieval
versus answer evaluation, complex-table chunking, citation-graph retrieval, and
energy measurement. I did not inspect local-reference Phase 2 files, origin files,
held-out questions, labels, pools, rankings, or candidate records. Public audit notes
do not disclose all previously spent family topics. Treat every entry as a candidate,
not a final family.

## Candidate anchors

| Priority | Accepted snapshot member and primary source | Potential category / modality / source-level outcome | Verified evidence locations |
|---|---|---|---|
| Core | `W3201233724` — [Simple Entity-Centric Questions Challenge Dense Retrievers](https://aclanthology.org/2021.emnlp-main.496/), DOI [10.18653/v1/2021.emnlp-main.496](https://doi.org/10.18653/v1/2021.emnlp-main.496) | Discovery; specific evidence; table result. Prose and numeric table. **Mixed/negative:** dense retrievers do well on one common QA set but trail BM25 on the paper’s entity-centric set; performance varies by question pattern. | Table 1 and Sections 3–4, especially the entity-pattern analysis. |
| Core | `W3201145629` — [Combining Lexical and Dense Retrieval for Computationally Efficient Multi-hop Question Answering](https://aclanthology.org/2021.sustainlp-1.7/), DOI [10.18653/v1/2021.sustainlp-1.7](https://doi.org/10.18653/v1/2021.sustainlp-1.7) | Specific evidence; table result; possible cross-paper comparison. Prose and numeric table. **Positive with a resource trade-off:** the paper reports a lexical/dense hybrid for multi-hop retrieval and evaluates constrained compute settings. | Table 1 and Sections 4.1–4.2 (overall retrieval and resource settings). |
| Core | `W4385573344` — [Evaluating Token-Level and Passage-Level Dense Retrieval Models for Math Information Retrieval](https://aclanthology.org/2022.findings-emnlp.78/), DOI [10.18653/v1/2022.findings-emnlp.78](https://doi.org/10.18653/v1/2022.findings-emnlp.78) | Discovery; specific evidence; table result. Prose and numeric tables. **Mixed:** structured formula search remains strong; dense retrieval can add recall through fusion, while dense reranking is not consistently useful. | Table 1 and Sections 4.1–4.2; Tables 2–4 and Sections 4.3–5 for fusion, reranking, and discussion. |
| Core | `W3184402450` — [Domain-matched Pre-training Tasks for Dense Retrieval](https://aclanthology.org/2022.findings-naacl.114/), DOI [10.18653/v1/2022.findings-naacl.114](https://doi.org/10.18653/v1/2022.findings-naacl.114) | Specific evidence; table result; possible cross-paper comparison. Prose and numeric tables. **Mixed:** retrieval-specific pretraining improves some comparisons, while the reported effect of model size varies by model and training condition. | Tables 1–3; Sections 4.1 and 5.1–5.3, including the model-size analysis. |
| Core | `W3196679537` — [Robust Retrieval Augmented Generation for Zero-shot Slot Filling](https://aclanthology.org/2021.emnlp-main.148/), DOI [10.18653/v1/2021.emnlp-main.148](https://doi.org/10.18653/v1/2021.emnlp-main.148) | Specific evidence; table result; possible cross-paper comparison. Prose and numeric tables. **Mixed:** retrieval and provenance measures vary across the slot-filling datasets and training variants; keep retrieval metrics distinct from generated slot accuracy. | Tables 1 and 4; Sections 4.3–4.4. Table 4 reports retrieval and downstream metrics together, so any later evidence anchor must select the retrieval columns only. |
| Core | `W4385570359` — [Towards Robust Ranker for Text Retrieval](https://aclanthology.org/2023.findings-acl.332/), DOI [10.18653/v1/2023.findings-acl.332](https://doi.org/10.18653/v1/2023.findings-acl.332) | Specific evidence; table result; possible cross-paper comparison. Prose and numeric tables. **Positive:** reports reranking and retriever-distillation comparisons using multiple negative generators. | Tables 1–3; Sections 4.1–4.2 (BM25 reranking, full ranking, and negative-generator analysis). |
| Core | `W4401042735` — [Reducing hallucination in structured outputs via Retrieval-Augmented Generation](https://aclanthology.org/2024.naacl-industry.19/), DOI [10.18653/v1/2024.naacl-industry.19](https://doi.org/10.18653/v1/2024.naacl-industry.19) | Specific evidence; table result; potential filter and cross-paper use. Numeric table. **Mixed:** scaling an off-the-shelf encoder alone does not consistently improve workflow-step and table retrieval; the paper reports stronger results after fine-tuning with its negative-sampling setup. | Section 4.2 defines the retrieval metrics; Table 3 and Section 5.1 report step/table Recall@K and sampling-strategy comparisons. Keep workflow retrieval separate from final-output hallucination metrics. |
| Core, with scope check | `W4406596702` — [Clinical entity augmented retrieval for clinical information extraction](https://www.nature.com/articles/s41746-024-01377-1), DOI [10.1038/s41746-024-01377-1](https://doi.org/10.1038/s41746-024-01377-1) | Discovery; specific evidence; table result; possible cross-paper comparison. Prose, figure, and numeric table. **Positive with task limits:** entity-directed retrieval is evaluated as context for clinical extraction; the headline results concern downstream extraction, not general-purpose retrieval ranking. | “Clinical entity augmented retrieval” methods section and Figure 3; Results Table 1 and Supplementary Table 6 for CLEAR versus chunk-embedding/full-note comparisons. Preserve the clinical task and downstream metric distinction. |
| Reserve | `W4385573970` — [Large Dual Encoders Are Generalizable Retrievers](https://aclanthology.org/2022.emnlp-main.669/), DOI [10.18653/v1/2022.emnlp-main.669](https://doi.org/10.18653/v1/2022.emnlp-main.669) | Specific evidence; table result; possible cross-paper comparison. Figure and numeric tables. **Positive/mixed:** scaling improves reported out-of-domain retrieval averages, while reduced fine-tuning data affects in-domain and out-of-domain results differently. | Figure 1; Tables 3–5; Sections 5.1–5.3. Table 3 includes per-dataset BEIR results; Table 4 compares data amounts. |
| Reserve | `W4385570470` — [Task-Aware Specialization for Efficient and Robust Dense Retrieval for Open-Domain Question Answering](https://aclanthology.org/2023.acl-short.159/), DOI [10.18653/v1/2023.acl-short.159](https://doi.org/10.18653/v1/2023.acl-short.159) | Specific evidence; table result; possible cross-paper comparison. Numeric tables. **Mixed:** parameter sharing improves some retrieval settings and efficiency, while pretraining effects vary across out-of-domain datasets. | Tables 1–2; Sections 4.1–4.2. Table 2 reuses EntityQuestions, so avoid treating it as an independent topic from the first anchor. |
| Reserve | `W4382449327` — [Aggretriever: A Simple Approach to Aggregate Textual Representations for Robust Dense Passage Retrieval](https://aclanthology.org/2023.tacl-1.26/), DOI [10.1162/tacl_a_00556](https://doi.org/10.1162/tacl_a_00556) | Specific evidence; table result; possible cross-paper comparison. Numeric tables. **Mixed:** aggregation often improves the reported dense-retrieval baselines, with exceptions across model and transfer conditions. | Tables 2–5; Sections 5.1–5.2. Tables 4–5 cover near-domain and multi-domain transfer; the EntityQuestions overlap with the first anchor is a freshness risk. |
| Reserve | `W4287887100` — [Re2G: Retrieve, Rerank, Generate](https://aclanthology.org/2022.naacl-main.194/), DOI [10.18653/v1/2022.naacl-main.194](https://doi.org/10.18653/v1/2022.naacl-main.194) | Specific evidence; table result; possible cross-paper comparison. Numeric tables. **Mixed:** retrieval changes vary by task, including a reported decline in one retrieval setting despite downstream answer gains. | Table 2 and Section 4.1 for retrieval; Table 3 and Section 4.2 for ablations. Restrict later use to retrieval measurements and avoid an answer-evaluation family. |

## Coverage implications

- **Discovery and specific evidence:** several primary sources define distinct retrieval tasks and give source-located evidence. Later family design still needs a narrow information need tied to one source condition.
- **Table results:** the core and reserve sources provide more than the required number of numeric table anchors. The Math IR and workflow-retrieval papers also preserve useful metric/condition distinctions for checking whether a value is interpreted in context.
- **Cross-paper comparison:** candidate pairs include multi-hop hybrid retrieval with slot-filling retrieval, and general dense retrieval with task-specific workflow or clinical retrieval. Compare task setup, evidence unit, filters, and metric definitions; do not compare raw scores across incompatible datasets.
- **Filters:** the accepted inventory contains candidates from 2021–2025. A later filter family can be tested against snapshot metadata, but its exact query and eligible-record expectation must be built separately from the private benchmark records.
- **Prose and negative/mixed findings:** all core sources include relevant method or analysis sections; the entity-centric, Math IR, domain-pretraining, slot-filling, and workflow-retrieval sources provide several candidate negative or mixed findings. This is source availability, not a claim that a held-out quota has been met.
- **Missing evidence:** a positive source anchor cannot establish a missing-evidence family. That category requires a separately scoped, source-first scan of the complete accepted snapshot, with an explicit absence bound and no retrieval-ranking input. This preparatory screen does not choose that topic or establish full six-category
coverage.

## Limits

The candidate set is tied to the accepted snapshot, and the cited result locations were
checked on official venue or publisher pages. However, the public source-coverage
audit deliberately withholds prior family identities. I can exclude subjects
disclosed in tracked public notes, but cannot certify novelty against every previously
spent set under the current access restrictions. No candidate here should be treated
as a final R8 family.
