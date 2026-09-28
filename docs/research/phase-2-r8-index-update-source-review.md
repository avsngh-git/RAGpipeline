# Phase 2 R8 scope 03: index-update source review

**Status:** bounded primary-source review; no questions, labels, pools, rankings, or benchmark results created  
**Reviewer:** assistant-reviewed  
**Reviewed:** 2026-09-28  
**Accepted snapshot:** `4b11fab3-d4a5-4e7a-a58e-8654accf2c6c`

## Scope and method

This review checks whether an accepted study changes or removes source content after constructing a persistent retrieval index, then measures whether the revised index prevents stale evidence from affecting retrieval or answers. It is a source-evidence check, not a benchmark annotation.

I read only the supplied scope note and its hit-context TSV from the R8 assessment folder, then checked the original paper or official publisher/venue page for each candidate. The TSV contains 66 rows representing 10 distinct accepted paper IDs. I checked the cited sections, figures, tables, or paper examples against the stated criterion. No held-out questions, labels, pools, rankings, results, origins files, or other Phase 2 run material were consulted. No question wording or benchmark judgment is reproduced here.

## Candidate dispositions

1. **`W4389519321` — [Empower Large Language Model to Perform Better on Industrial Domain-Specific Question Answering](https://aclanthology.org/2023.emnlp-industry.29/).** The source compares retrieval-based baselines with a domain-specific model interaction method. Its retrieved-document setup does not test post-index source revision or deletion; the apparent match concerns restricted domain data and fine-tuning privacy. See Section 1 for the privacy context and Section 5.1 for retrieval baselines in the [official paper PDF](https://aclanthology.org/2023.emnlp-industry.29.pdf).

2. **`W4404783788` — [Retrieval Augmented Generation or Long-Context LLMs? A Comprehensive Study and Hybrid Approach](https://aclanthology.org/2024.emnlp-industry.66/).** The paper compares RAG, long-context models, and a routing method across static public evaluation datasets. It reports no persistent-index update or source-deletion experiment. See Sections 3–4 in the [official paper PDF](https://aclanthology.org/2024.emnlp-industry.66.pdf).

3. **`W4404784153` — [Model Internals-based Answer Attribution for Trustworthy Retrieval-Augmented Generation](https://aclanthology.org/2024.emnlp-main.347/).** The apparent circulation terms occur in a retrieved passage used as an answer-attribution example. The paper evaluates attribution of generated claims to retrieved context, not changes to the indexed source corpus. See Section 5 and Table 4 in the [official paper PDF](https://aclanthology.org/2024.emnlp-main.347.pdf).

4. **`W4406596702` — [Clinical entity augmented retrieval for clinical information extraction](https://www.nature.com/articles/s41746-024-01377-1).** The paper excludes notes for patients appearing in both training and test data to prevent leakage. That is a dataset-splitting step, not removal from a persistent retrieval index. Its retrieval experiment compares entity-directed retrieval with chunk-embedding and full-note approaches; it does not revise or delete indexed source notes. See the Methods and the data-leakage description in the [publisher article](https://www.nature.com/articles/s41746-024-01377-1).

5. **`W4412945639` — [RAGEval: Scenario Specific RAG Evaluation Dataset Generation Framework](https://aclanthology.org/2025.acl-long.418/).** The Related Work section names CRUD-RAG and summarizes its Create/Read/Update/Delete categories. RAGEval’s own contribution generates scenario-specific evaluation material and reports RAG evaluation experiments; it does not test post-index source updates or deletions. See Section 2 for the benchmark reference and Sections 3–5 for RAGEval’s framework and experiments in the [official paper PDF](https://aclanthology.org/2025.acl-long.418.pdf).

6. **`W7114889968` — [A Systematic Literature Review of Retrieval-Augmented Generation: Techniques, Metrics, and Challenges](https://www.mdpi.com/2504-2289/9/12/320).** The review discusses stale material, refresh cadence, and the scarcity of measured index-update overhead, and recommends future work on refresh and provenance. These are literature synthesis and research-gap statements, not an experiment by this paper that changes indexed documents and measures stale-evidence behavior. See the Discussion and Future Work in the [publisher article](https://www.mdpi.com/2504-2289/9/12/320).

7. **`W3015883388` — [Dense Passage Retrieval for Open-Domain Question Answering](https://aclanthology.org/2020.emnlp-main.550/).** The paper builds a FAISS index from a fixed Wikipedia dump and reports index construction and retrieval performance. It does not test source additions, revisions, or deletion after index construction. See Section 4.1 for the fixed corpus and Section 5 for index construction costs in the [official paper PDF](https://aclanthology.org/2020.emnlp-main.550.pdf).

8. **`W3203288040` — [Adversarial Retriever-Ranker for Dense Text Retrieval](https://openreview.net/forum?id=MR7XubKUFB) ([Microsoft Research publication page](https://www.microsoft.com/en-us/research/publication/adversarial-retriever-ranker-for-dense-text-retrieval/)).** This is a close index-refresh case: Section 3.3 refreshes the ANN index during retriever/ranker training by re-encoding the same corpus with updated retriever parameters. The source documents themselves are not revised or removed, and the experiments do not test whether an old source can still be retrieved after a content update or deletion. See Section 3.3 and Algorithm 1 in the [paper PDF](https://arxiv.org/pdf/2110.03611).

9. **`W4317898419` — [Improving the Domain Adaptation of Retrieval Augmented Generation (RAG) Models for Open Domain Question Answering](https://aclanthology.org/2023.tacl-1.1/).** This is another close match: Sections 3.2–3.3 re-encode and re-index the knowledge base when the passage encoder changes during training. The corpus content remains the training knowledge base; the paper studies retriever/generator adaptation and QA performance, not source-document revision/deletion or stale-content suppression. See Sections 3.2–3.3 and the [official paper PDF](https://aclanthology.org/2023.tacl-1.1.pdf).

10. **`W4389520670` — [Enabling Large Language Models to Generate Text with Citations](https://aclanthology.org/2023.emnlp-main.398/).** The apparent removal operation in Appendix C, Table 27 removes already-used full-text passages from the model’s prompt context during interactive generation. It does not remove documents from the persistent retrieval corpus or test source updates. See Section 3 and Appendix C in the [official paper PDF](https://aclanthology.org/2023.emnlp-main.398.pdf).

## Finding and coverage

No supplied candidate provides direct evidence for the stated source-lifecycle criterion. The closest papers, AR2 and RAG-end2end, rebuild retrieval indexes after changing the encoder during training; neither changes or removes source documents. The other matches concern retrieval examples, train/test separation, context-window management, static-corpus retrieval, or review-level discussion.

This note source-checks the 10 distinct candidates in the supplied TSV. The scope note says the upstream scan searched the accepted snapshot’s extracted chunks, evidence units, and structured table material, but I did not independently rerun that full scan or inspect other accepted-paper records. Therefore the finding is bounded to these supplied candidates and does not certify that no other record in the snapshot contains relevant evidence. It also makes no claim about literature beyond the accepted snapshot.
