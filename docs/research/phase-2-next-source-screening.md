# Phase 2 next-set source screen

**Status:** assistant-reviewed preparatory source screen; no question families, wording, relevance judgments, pools, or scores created

**Date:** 2026-09-29
**Snapshot:** accepted Phase 1 100-paper snapshot `4b11fab3-d4a5-4e7a-a58e-8654accf2c6c`

## Method and boundaries

This screen prepares candidate sources for a fresh Phase 2 benchmark under the
[approved evaluation protocol](../plans/phase-2-evaluation-protocol.md) and the
[current v2 sampling plan](../reference/phase-2-benchmark-sampling-plan.md).
It does not create families or labels. Potential category tags below are navigation
ideas for later family design, not split assignments or completed coverage.

I checked the exact finalized snapshot through a read-only join of `snapshot_items`
and `papers`. The metadata query returned 100 distinct members and selected only publication
title and year. I then checked each candidate's official venue page and primary paper
or final published author copy for the evidence locations below. I did not use local
extracted text. No Phase 2 questions, judgments, candidate pools, ranking outputs, or
`*origins.json` files were used.

To reduce known overlap, I excluded topics that the public R8 screen already names:
long-context comparisons, multilingual representation, query transformation,
structured-document QA, legal-document chunking, retrieval-versus-answer evaluation,
complex-table chunking, citation-graph retrieval, and energy measurement. The public
coverage audit and screen do not disclose every previously spent family identity.
Therefore full novelty against prior splits cannot be certified; every source below
remains a candidate only.

## Candidate source anchors

| Priority | Accepted-snapshot primary source | Potential category / modality | Source-level reported outcome and exact anchors |
|---|---|---|---|
| Core | [COIL: Revisit Exact Lexical Match in Information Retrieval with Contextualized Inverted List](https://aclanthology.org/2021.naacl-main.241/) | Specific evidence; table result; cross-paper comparison. Prose and numeric tables. | **Positive with scope limits:** the paper reports strong exact-match retrieval with contextualized token scores, with further gains from a semantic bridge; its speed/effectiveness trade-offs depend on the collection and setup. Check §5.1, Tables 1–2 (passage and document results), and §5.2, Table 3 (dimension and efficiency trade-off). |
| Core | [Modularized Transfomer-based Ranking Framework (MORES)](https://aclanthology.org/2020.emnlp-main.342/) | Specific evidence; table result; cross-paper comparison. Prose and numeric tables. | **Positive with resource trade-offs:** the reported ranking quality varies with interaction depth; precomputed document representations produce large measured speedups at a storage cost. Check §4.2, Table 2 (ranking effectiveness), and §4.3, Table 4 (CPU/GPU timing and representation storage). |
| Core | [A Test Collection of Synthetic Documents for Training Rankers: ChatGPT vs. Human Experts](https://dare.uva.nl/search?identifier=a3aac532-b09e-40b0-9074-9ae8be2fb4c5) ([final published-version PDF](https://pure.uva.nl/ws/files/169472407/3583780.3615111.pdf), [DOI](https://doi.org/10.1145/3583780.3615111)) | Specific evidence; table result; cross-paper comparison. Prose and numeric tables. | **Mixed:** cross-encoder rankers trained on human responses perform better in-domain, while synthetic-response training helps on some out-of-domain collections. Check §4.1, Table 2 (in-/out-of-domain comparison), and §4.2, Table 3 (domain-level results). The repository record identifies this as the final published version under CC BY. |
| Core | [IIRC: A Dataset of Incomplete Information Reading Comprehension Questions](https://aclanthology.org/2020.emnlp-main.86/) | Discovery; specific evidence; table result. Prose and numeric tables. **Context-insufficiency concept only.** | **Limitation:** the paper distinguishes questions answerable from the supplied context from questions needing linked material or having no answer; its baseline remains below reported human performance. Check §2.4, Table 1 (task-type analysis), and §4.3, Table 3 (baseline/oracle/human results). This is not evidence of absence from the accepted Phase 1 snapshot and cannot alone satisfy a missing-evidence family. |
| Core | [Relevance-guided Supervision for OpenQA with ColBERT](https://aclanthology.org/2021.tacl-1.55/) | Specific evidence; table result; cross-paper comparison. Prose and numeric tables. | **Positive for the paper's retrieval measure:** iterative self-supervision improves reported Success@k, while the paper reports downstream answer extraction separately. Check §4.3, Table 1, and §4.4, Table 2 (retrieval quality by depth). Keep retrieval results separate from the answer EM analysis. |
| Reserve | [DiPair: Fast and Accurate Distillation for Trillion-Scale Text Matching and Pair Modeling](https://aclanthology.org/2020.findings-emnlp.264/) | Specific evidence; table result; cross-paper comparison. Prose and numeric tables. | **Mixed quality/speed trade-off:** the pair-scoring model is substantially faster than its cross-attention teacher in the reported tasks, while the simplest scoring variant is fastest but less effective. Check §4.5, Tables 2–3, and §4.6, Table 4. This is pair modeling, not first-stage full-corpus retrieval, so it is a lower-priority reranking context. |
| Reserve | [Learning Dense Representations of Phrases at Scale](https://aclanthology.org/2021.acl-long.518/) | Discovery; specific evidence; table result; cross-paper comparison. Prose and numeric tables. | **Positive with scope limits:** phrase retrieval improves over earlier phrase-retrieval baselines on several reported QA datasets, but some comparisons are answer-task metrics and the paper reports substantial indexing/storage requirements. Check §7.2, Tables 1–3; keep retrieval, answer, and resource outcomes distinct. |

## Proposed first-five source-review sequence

This is a source-review order only. It does not assign benchmark splits, draft
questions, or establish category coverage.

1. **COIL:** start with its passage and document tables to establish a direct,
retrieval-only numeric source anchor and its metric conditions.
2. **MORES:** check the paired quality and timing tables, including what was
precomputed and the storage reported for that setup.
3. **Synthetic-document rankers:** review the in-domain/out-of-domain contrast and
retain its mixed direction rather than collapsing it into one overall claim.
4. **IIRC:** check how the source distinguishes context insufficiency from no answer;
do not transfer that distinction into a snapshot-wide absence judgment.
5. **ColBERT-QA:** review retrieval Success@k independently of downstream answer
metrics and decide whether its retrieval evidence supports a distinct family.

DiPair and DensePhrases remain reserves because their pair-scoring or phrase-level
task units need an explicit fit check against the Phase 2 paper/evidence retrieval
contract before family design.

## Coverage and next-step constraints

- The current v2 sampling plan requires 21 development and 10 held-out families over
  six categories, plus prose/table and negative-or-mixed-finding floors. This source
  screen contributes no families toward those counts. Family splits must be explicit
  before pooling; all paraphrases stay with their family.
- The listed studies offer prose and numeric-table anchors, but do not establish the
  required source-checked direct-prose or table-family counts. A later review must
  inspect the exact primary-source location, source version, and table context before
  creating any family or judgment.
- A filter family should be designed from the accepted snapshot's metadata and its
  exact eligible-record count; this screen did not choose a filter or compute a
  family-specific count.
- A missing-evidence family requires a separately scoped source-first scan across the
  accepted snapshot and an explicit search boundary. IIRC's local-context
  unanswerability does not establish that no support exists anywhere in the accepted
  corpus.
- The v2 plan allocates 13 reviewer-hours for the 31-family candidate/source review
  and remeasures effort after its two new development families. This source screen
  contributes no review-time measurement.

## Sources checked

**Project method and snapshot:**

- [`scientific-research-platform-source-of-truth.md`](../agents/scientific-research-platform-source-of-truth.md), including the Phase 2 policy and operating checklist.
- [`phase-2-agent-handoff.md`](../plans/phase-2-agent-handoff.md), [`phase-2-evaluation-protocol.md`](../plans/phase-2-evaluation-protocol.md), and [`phase-2-benchmark-sampling-plan.md`](../reference/phase-2-benchmark-sampling-plan.md), including its TOML manifest.
- [`phase-2-r8-source-screening.md`](phase-2-r8-source-screening.md) and [`phase-2-benchmark-source-coverage-audit-v3.md`](phase-2-benchmark-source-coverage-audit-v3.md), used for public topic-overlap limits and bounded-coverage context.
- [`phase-1-100-paper-acceptance-report.md`](../reference/phase-1-100-paper-acceptance-report.md) and the accepted snapshot's read-only `snapshot_items`/`papers` metadata query (title/year only; 100 distinct members).

**Primary papers:** the seven linked venue or repository records and PDFs in the candidate table. For the synthetic-document paper, the checked copy is the UvA repository's final published version; the other six sources are the official ACL Anthology venue records and PDFs.

No candidate paper IDs, query wording, relevance labels, passages, held-out item data,
or ranking outputs are included in this report.
