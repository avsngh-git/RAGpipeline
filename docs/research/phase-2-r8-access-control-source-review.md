# Phase 2 R8 scope 02: access-control source review

**Status:** bounded primary-source review; no questions, labels, pools, rankings, or benchmark results created  
**Reviewer:** assistant-reviewed  
**Reviewed:** 2026-09-28  
**Accepted snapshot:** `4b11fab3-d4a5-4e7a-a58e-8654accf2c6c`

## Scope and method

This review checks whether an accepted paper evaluates retrieval from a persistent corpus with user-, role-, or tenant-specific document permissions and tests whether retrieval blocks unauthorized material or cross-scope leakage. General privacy discussion, access-control examples in source text, train/test separation, and permission statements without a retrieval leakage experiment do not qualify.

I read the private scope note and source-context TSV for access-control hits, then checked the original paper or official publisher/venue source for each distinct candidate. The access-control subset contains 24 context rows across six accepted papers. Candidate matching did not use Phase 2 questions, judgments, retrieval rankings, pools, run outputs, or origin files. No held-out material was consulted, and this review creates no benchmark items.

## Candidate dispositions

1. **`W4389519321` — [Empower Large Language Model to Perform Better on Industrial Domain-Specific Question Answering](https://aclanthology.org/2023.emnlp-industry.29/).** The confidentiality hit concerns risks while fine-tuning on restricted domain data. The paper compares a model-interaction approach with retrieval methods but does not test authorization filtering or cross-user leakage in a persistent retrieval corpus. See Sections 1 and 4–5 in the [official paper PDF](https://aclanthology.org/2023.emnlp-industry.29.pdf).

2. **`W4404783788` — [Retrieval Augmented Generation or Long-Context LLMs? A Comprehensive Study and Hybrid Approach](https://aclanthology.org/2024.emnlp-industry.66/).** The paper compares RAG and long-context methods on fixed evaluation material. The inspected access-control candidates do not describe per-user, role, or tenant permissions or test unauthorized retrieval. See the [official paper PDF](https://aclanthology.org/2024.emnlp-industry.66.pdf).

3. **`W4404784153` — [Model Internals-based Answer Attribution for Trustworthy Retrieval-Augmented Generation](https://aclanthology.org/2024.emnlp-main.347/).** The apparent authorization match is a library-alarm passage used to illustrate citation attribution. The experiment evaluates whether generated claims are attributed to retrieved passages; it does not enforce document permissions or test cross-scope leakage. See Section 5 and Table 4 in the [official paper PDF](https://aclanthology.org/2024.emnlp-main.347.pdf).

4. **`W4406596702` — [Clinical entity augmented retrieval for clinical information extraction](https://www.nature.com/articles/s41746-024-01377-1).** The leakage discussion removes patients represented in both training and test partitions. This protects evaluation separation; it is not user-specific authorization for retrieving clinical notes. The retrieval comparison measures information-extraction performance and does not test ACL leakage. See the Methods sections on data leakage and chunk-embedding comparison in the [publisher article](https://www.nature.com/articles/s41746-024-01377-1).

5. **`W4412945639` — [RAGEval: Scenario Specific RAG Evaluation Dataset Generation Framework](https://aclanthology.org/2025.acl-long.418/).** Privacy appears as a general challenge in creating evaluation datasets. RAGEval generates scenario-specific evaluation material and measures RAG quality; it does not test permission-filtered retrieval over a multi-user persistent corpus. See the Introduction and framework/experiment sections in the [official paper PDF](https://aclanthology.org/2025.acl-long.418.pdf).

6. **`W7114889968` — [A Systematic Literature Review of Retrieval-Augmented Generation: Techniques, Metrics, and Challenges](https://www.mdpi.com/2504-2289/9/12/320).** Security and privacy are discussed as broader RAG challenges. A review-level discussion is not a primary experiment of user/role/tenant authorization and leakage in retrieval.

## Finding and coverage

None of the six supplied candidates directly tests whether persistent-corpus retrieval enforces per-user, role, or tenant permissions against unauthorized-document or cross-scope leakage. The apparent matches concern restricted data during fine-tuning, citation examples, evaluation-set separation, general privacy discussion, or fixed-corpus quality comparisons.

The upstream source-first protocol covers all 100 accepted snapshot members and their selected extraction text, evidence units, and structured table material. This note checks the six distinct works represented by the access-control rows supplied in that scan; it does not independently rerun the scan or inspect every source record. The finding is therefore bounded to the supplied candidate set and accepted snapshot, not the wider literature.
