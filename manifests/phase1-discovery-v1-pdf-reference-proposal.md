# Phase 1 ten-paper PDF reference set proposal

**Status:** Approved for local storage and indexing; PDF evidence review remains pending.  
**Prepared:** 2026-09-24  
**User approval:** 2026-09-24 (public passage display remains disabled)  
**Parent manifest:** `1d84a2eb-8379-45ee-923b-fd6dd219a103`, approved version 1

This sample is a subset of the approved 67-paper set. All ten records
reported an OpenAlex cached PDF, a `cc-by` `best_oa_location.license`, and a
`publishedVersion` at the 2026-09-24 metadata preflight. The tags below are the
approved manifest's coverage tags, not independent evidence that a paper proves
a particular result. The sample mixes retrieval and reranking studies, papers
covering multiple questions, and chunking/citation work, including a review and
a paper specifically about complex tables.

OpenAlex says cached PDFs retain their original copyright and it grants no
additional content rights. It directs users to check `best_oa_location.license`;
that recorded license and the current content-availability metadata must be
rechecked before any acquisition. When this proposal was prepared, no PDF had
yet been requested; the subsequent approval and acquisition are documented
below. See the [OpenAlex full-text terms](https://help.openalex.org/access/fulltext/)
and [license vocabulary](https://help.openalex.org/data/licenses/).

| Year | Paper | OpenAlex ID | DOI | Manifest coverage tags | Sample role |
| ---: | --- | --- | --- | --- | --- |
| 2022 | ColBERTv2: Effective and Efficient Retrieval via Lightweight Late Interaction | W3217305727 | [10.18653/v1/2022.naacl-main.272](https://doi.org/10.18653/v1/2022.naacl-main.272) | hybrid/dense | Late-interaction retrieval |
| 2022 | Re2G: Retrieve, Rerank, Generate | W4287887100 | [10.18653/v1/2022.naacl-main.194](https://doi.org/10.18653/v1/2022.naacl-main.194) | reranking/latency | Explicit retrieve-rerank pipeline |
| 2023 | Improving the Domain Adaptation of Retrieval Augmented Generation (RAG) Models for Open Domain Question Answering | W4317898419 | [10.1162/tacl_a_00530](https://doi.org/10.1162/tacl_a_00530) | hybrid/dense | Domain-specific RAG evaluation |
| 2024 | Searching for Best Practices in Retrieval-Augmented Generation | W4404782883 | [10.18653/v1/2024.emnlp-main.981](https://doi.org/10.18653/v1/2024.emnlp-main.981) | hybrid/dense; reranking/latency; chunking/citation | One study spanning all three questions |
| 2024 | mGTE: Generalized Long-Context Text Representation and Reranking Models for Multilingual Text Retrieval | W4404783220 | [10.18653/v1/2024.emnlp-industry.103](https://doi.org/10.18653/v1/2024.emnlp-industry.103) | hybrid/dense; reranking/latency | Retrieval and reranker comparison |
| 2024 | Retrieval Augmented Generation or Long-Context LLMs? A Comprehensive Study and Hybrid Approach | W4404783788 | [10.18653/v1/2024.emnlp-industry.66](https://doi.org/10.18653/v1/2024.emnlp-industry.66) | hybrid/dense | Comparative and hybrid approach |
| 2025 | A Systematic Literature Review of Retrieval-Augmented Generation: Techniques, Metrics, and Challenges | W7114889968 | [10.3390/bdcc9120320](https://doi.org/10.3390/bdcc9120320) | none | Review with likely dense tabular content; inspect PDF before annotation |
| 2025 | Document GraphRAG: Knowledge Graph Enhanced Retrieval Augmented Generation for Document Question Answering Within the Manufacturing Domain | W4410600121 | [10.3390/electronics14112102](https://doi.org/10.3390/electronics14112102) | chunking/citation | Document structure and graph retrieval |
| 2025 | Comparative Evaluation of Advanced Chunking for Retrieval-Augmented Generation in Large Language Models for Clinical Decision Support | W4415813536 | [10.3390/bioengineering12111194](https://doi.org/10.3390/bioengineering12111194) | chunking/citation | Direct chunking comparison |
| 2026 | Structure-Aware Chunking for Complex Tables in Retrieval-Augmented Generation Systems | W7127049495 | [10.28991/esj-2026-010-01-09](https://doi.org/10.28991/esj-2026-010-01-09) | chunking/citation | Complex-table layout case |

## Approval and acquisition

The user approved this exact set for local storage and indexing on 2026-09-24.
Public passage display is not permitted. Each work was rechecked immediately
before its download; all ten still reported a cached PDF, a CC BY
best-open-access license, and a published version. Each file was stored under the
Git-ignored data/artifacts directory, hashed, linked to its published-version
document record, and paired with immutable permission evidence in the isolated
research_phase1_review database.

The [acquisition inventory](phase1-discovery-v1-pdf-acquisition.json) records
the document IDs, metadata check times, permission evidence IDs, SHA-256 checksums,
byte sizes, artifact paths and API budget snapshots. Ten PDFs total 11,587,433
bytes. OpenAlex showed $0.96 of the $1.00 daily free allowance before the ten
successful requests and $0.86 after them; prepaid balance remained $0. One
earlier request was billed $0.01 but could not write its file because Docker had
created the local artifact directory as root. The directory ownership was fixed,
and all ten approved PDFs were then acquired. Total Phase 1 content usage for the
ten files plus that failed attempt was $0.11; no paid balance was used.

## Remaining human review

The human reviewer must verify the selected PDF evidence and annotations before
parser comparison. Use the [compact review index](phase1-discovery-v1-pdf-review.md)
to open each file and the [reference protocol](../docs/reference/phase-1-reference-protocol.md)
for the required checks. The acquisition inventory marks this review as pending.
The PDFs and any full-text annotations remain outside Git.
