# Phase 2 R8 scope 01: end-user task study review

**Status:** bounded source-first scan and primary-source review; no questions, labels, pools, rankings, or scores created
**Reviewer:** assistant-reviewed
**Reviewed:** 2026-09-28
**Accepted snapshot:** `4b11fab3-d4a5-4e7a-a58e-8654accf2c6c`

## Criterion and method

The scan criterion was fixed before query design or retrieval ranking: an eligible
study must have people actually perform a literature- or evidence-finding task with a
RAG system, compare it with conventional search or their prior workflow, and report a
user task outcome such as task success, task accuracy, completion time, or usability.
Human ratings of model answers, offline QA benchmarks, and model-only quality measures
do not qualify.

The private audit searched the complete accepted snapshot’s selected-extraction
chunks, evidence-unit text, and structured table captions/data/footnotes using the
predeclared interaction, outcome, comparison, and system term groups in
`local-reference/phase2-runs/r8-assessment-20260928/missing-evidence-scan-protocol.md`.
It produced 72 source-context hits across 40 papers. The scan used no Phase 2
questions, labels, rankings, candidate pools, run results, or origins. I source-checked
the nearest apparent matches against the primary publisher or author versions:

| Accepted paper | Why it matched the scan | Assessment against the criterion |
|---|---|---|
| `W4389518954`, *Evaluating Verifiability in Generative Search Engines* ([ACL Anthology](https://aclanthology.org/2023.findings-emnlp.467/)) | Human evaluation of commercial generative search responses. | Annotators rate response utility and citation support. They do not perform a comparative evidence-finding task or measure task completion, success, or usability against conventional search. |
| `W4404783839`, *PDFTriage: Question Answering over Long, Structured Documents* ([author version](https://arxiv.org/abs/2309.08872)) | Human judgments compare generated answers from PDFTriage with page- and chunk-retrieval baselines. | The study asks annotators to rate and rank answers. It does not test end users completing a search task or compare with conventional search or a prior workflow. |
| `W4410600121`, *Document GraphRAG: Knowledge Graph Enhanced Retrieval Augmented Generation for Document Question Answering Within the Manufacturing Domain* ([publisher](https://www.mdpi.com/2079-9292/14/11/2102)) | A focus group reviews generated answers; the paper also discusses response latency and manual search. | The focus group assesses a sample of system outputs. It does not run a user task against a measured manual-search condition; the manual-search time comparison is contextual, not an observed within-study task outcome. |
| `W3167262725`, *Pre-trained Language Model for Web-scale Retrieval in Baidu Search* ([author version](https://arxiv.org/abs/2106.03373)) | Production web search and online experiments with real search traffic. | This is a retrieval-only web-search system, not RAG. Its deployment evidence does not meet the RAG-system requirement in the fixed criterion. |
| `W4406596702`, *Clinical entity augmented retrieval for clinical information extraction* ([publisher](https://www.nature.com/articles/s41746-024-01377-1)) | Retrieval supports a clinical information-extraction task and includes human-related evaluation language. | The evaluated outcome is extraction quality on a fixed dataset, not clinicians performing evidence-finding tasks against a prior workflow. |

## Finding and limit

None of the reviewed candidates meets all parts of the fixed criterion. The scan
supports only this bounded statement: among the text and structured fields of the
accepted 100-paper snapshot, using the recorded term groups and source versions, no
direct comparative end-user RAG evidence-finding study was identified. It does not
establish absence in the wider literature, and it cannot rule out a missed study due
to terminology or extraction coverage. The scan and source-context records remain
private; this note contains no question wording, passages, judgments, or candidate
rankings.
