# Phase 1 discovery v1: screening proposal

**Status: manifest v1 is approved. The user approved all candidate-level decisions and the coverage assessment in chat on 2026-09-24.** The row number is the item's position in `phase1-discovery-v1.json` (starting at 1); the OpenAlex ID identifies the record. Decisions follow the plan's initial scope: English-language research on RAG, retrieval, reranking, and chunking from 2020 onward, prioritizing substantive method comparisons, benchmarks, and evaluations. App papers are included only when their experiment directly informs one of the three stated questions. Negative or mixed findings remain eligible.

## Screening decisions

Tags: **H** = dense/hybrid retrieval; **R** = reranking and quality/latency; **C** = chunking and evidence retrieval. **Include** means approved for the v1 shortlist and next source/rights review; it does not grant full-text permissions. **Exclude** means excluded from the v1 shortlist because it does not substantively inform the approved questions, is an application showcase, or duplicates a preferred published version.

| # | OpenAlex ID | Decision | Topic | Screening reason |
|---:|---|---|---|---|
| 1 | W3034881347 | Exclude | — | Retrieve-edit-rerank is for generation tasks, not document retrieval or RAG retrieval. |
| 2 | W3036320503 | Include | H | Dense search compared with Boolean retrieval; useful retrieval evidence, though not RAG-specific. |
| 3 | W3123811550 | Include | H | Evaluates retrieval-augmented code summarization; retain as a task-specific RAG evaluation. |
| 4 | W3155807546 | Include | R | Tests retrieval augmentation and ranking in dialogue, including human evaluation. |
| 5 | W3186138538 | Include | H | Evaluates live-search RAG against a fixed retrieval setup. |
| 6 | W3217305727 | Include | H | ColBERTv2 is a substantial neural retrieval method; abstract was absent from the export, so verify scope/details at source review. |
| 7 | W4226069413 | Include | Review | Directly on-topic RAG survey; retain selectively to map prior retrieval-augmented generation evidence. |
| 8 | W4287367114 | Exclude | — | Survey concerns visual instance retrieval, outside text RAG. |
| 9 | W4287887100 | Include | R | Re2G directly studies retrieve-rerank-generate; abstract absent, but source record identifies the method. |
| 10 | W4301243929 | Include | H | Atlas evaluates retrieval-augmented language models and index choices. |
| 11 | W4312854033 | Include | H | Evaluates retrieval-augmented knowledge-grounded dialogue. |
| 12 | W4317898419 | Include | H | Direct study of retriever domain adaptation for RAG. |
| 13 | W4318719006 | Exclude | — | Preprint duplicate of the published REPLUG record at row 47; prefer the published version. |
| 14 | W4384388099 | Exclude | — | Broad information-retrieval survey, not focused on the approved RAG questions. |
| 15 | W4384652670 | Include | R | Studies efficient RAG with source-pointer reranking and effectiveness/latency considerations. |
| 16 | W4384918448 | Exclude | — | ICU simulation study does not address retrieval methods. |
| 17 | W4385571271 | Include | H | IRCoT evaluates retrieval interleaved with reasoning for multi-hop QA. |
| 18 | W4385572856 | Exclude | — | Commit-message generation application retrieves exemplars but does not answer the approved retrieval questions. |
| 19 | W4385573057 | Include | R | Evaluates passage retrieval improvements for open QA; relevant even though it is not a cross-encoder latency study. |
| 20 | W4385573236 | Exclude | — | Multimodal image-text RAG falls outside the initial text-focused corpus. |
| 21 | W4386556635 | Exclude | — | RGB benchmark preprint duplicates the published AAAI version at row 34. |
| 22 | W4387800173 | Exclude | — | Career-advice prototype has too little evaluation of retrieval methods. |
| 23 | W4388778348 | Include | H | Studies in-context retrieval-augmented language models and retrieval/ranking behavior. |
| 24 | W4389761608 | Include | H | PaperQA evaluates a scientific-research RAG system on a relevant corpus. |
| 25 | W4389921502 | Include | Review, H | Dense retrieval survey; retain selectively because it synthesizes evidence relevant to retrieval methods. |
| 26 | W4389984066 | Include | Review | Directly on-topic RAG survey; retain selectively to map prior RAG evidence. |
| 27 | W4390872247 | Exclude | — | Retrieval is for human-motion generation, outside text RAG. |
| 28 | W4391221150 | Exclude | — | Clinical assistant evaluation is an application study without a retrieval-method contribution relevant to the questions. |
| 29 | W4391631359 | Include | H | Tests query fusion and reciprocal-rank fusion in RAG; retain with lower priority because evaluation is limited and mixed. |
| 30 | W4391709255 | Include | C | Direct comparison of financial-report chunking strategies for RAG. |
| 31 | W4392487838 | Include | H | Compares RAG with fine-tuning and evaluates retrieval models for less-popular knowledge. |
| 32 | W4392544551 | Exclude | — | Liver-disease chatbot application, without a general retrieval-method evaluation. |
| 33 | W4392597393 | Exclude | — | Nephrology-focused overview/application article, not a direct retrieval-method study. |
| 34 | W4393147129 | Include | H | Published RGB RAG benchmark; use this version instead of row 21. |
| 35 | W4393299232 | Include | Review | RAG survey; retain selectively as a synthesis of the field. |
| 36 | W4394947112 | Include | Review | RAG text-generation survey; retain selectively as a synthesis of the field. |
| 37 | W4395050972 | Include | C | Evaluates document structuring and formatting choices in a guideline RAG system. |
| 38 | W4396758745 | Include | R | Direct RAG reranking/truncation method with relevance-versus-noise evaluation. |
| 39 | W4396823873 | Exclude | — | Customer-service KG-RAG application; structured retrieval is not directly compared with the target methods. |
| 40 | W4396913672 | Exclude | — | Preprint duplicate of the later published evaluation survey at row 74; row 74 is the preferred version if reviews are included. |
| 41 | W4398173700 | Include | C, R | Evaluates sentence-window/parent-child retrieval and reranking in RAG. |
| 42 | W4399356589 | Include | C | Direct dynamic-granularity chunking study with experiments. |
| 43 | W4399530612 | Include | H, R, C | RAG failure analysis reports practical negative/mixed evidence across retrieval and pipeline stages. |
| 44 | W4399932275 | Include | H | Case-based legal QA compares retrieval representations and hybrid similarities; retain as a domain-specific method evaluation. |
| 45 | W4400128031 | Exclude | — | Medical application centered on self-reflection rather than the target retrieval comparisons. |
| 46 | W4401042753 | Include | H | Adaptive-RAG study selects retrieval behavior by query complexity. |
| 47 | W4401042773 | Include | H | Published REPLUG paper; use instead of the preprint at row 13. |
| 48 | W4401042808 | Exclude | — | ARES evaluates RAG quality rather than comparing retrieval, reranking, or chunking methods. |
| 49 | W4401448427 | Exclude | — | Marketing AI-human hybrid study is unrelated to retrieval hybridization. |
| 50 | W4401857375 | Include | Review | RAG survey; retain selectively as a synthesis of the field. |
| 51 | W4402111798 | Include | R | Uses answer-reranking feedback to train retrieval-augmented QA systems; relevant to ranking signals, though not a latency comparison. |
| 52 | W4402409840 | Exclude | — | Code-generation control application, not a general retrieval-method evaluation. |
| 53 | W4402595050 | Include | C | Direct comparison of chunking approaches for regulatory-document RAG. |
| 54 | W4402670290 | Include | H | MIRAGE benchmarks RAG retrievers, corpora, and model backbones; retain with a medical-domain tag. |
| 55 | W4402670423 | Exclude | — | Discusses privacy in RAG, outside the retrieval questions. |
| 56 | W4402683011 | Exclude | — | Multilingual RAG study is outside the English-language initial scope. |
| 57 | W4403248625 | Include | Review | Systematic RAG review; retain selectively because it synthesizes relevant studies. |
| 58 | W4403420914 | Include | H | Blended RAG directly combines sparse and dense retrieval and evaluates retrieval/RAG outcomes. |
| 59 | W4403442464 | Exclude | — | “Hybrid” refers to cloud deployment, not hybrid retrieval. |
| 60 | W4403458599 | Exclude | — | Domain-specific ontology-generation RAG application; no direct comparison for the target questions. |
| 61 | W4403589311 | Exclude | — | GraphRAG survey is secondary and focused on graph retrieval; omit under the proposed primary-study focus. |
| 62 | W4404129812 | Include | H, C | Compares hybrid/semantic retrieval and chunking for RAG; retain with an e-learning domain tag. |
| 63 | W4404351611 | Exclude | — | Financial KG-plus-vector architecture is not the sparse-plus-dense hybrid comparison in question 1. |
| 64 | W4404782883 | Include | H, R, C | “Searching for Best Practices in RAG” reports systematic primary experiments relevant to all three questions. |
| 65 | W4404783220 | Include | H, R | mGTE evaluates text retrieval/reranking; retain if its results include English evaluation, as expected for this general text benchmark. |
| 66 | W4404783788 | Include | H | Directly compares RAG with long-context approaches and reports tradeoffs, including RAG resource cost. |
| 67 | W4404783805 | Exclude | — | Workshop version duplicates the published NAACL industry paper at row 93. |
| 68 | W4405205161 | Include | H | Presents and evaluates an inverted-question-matching retrieval architecture for RAG. |
| 69 | W4406031095 | Exclude | — | GraphRAG overview/design discussion does not provide a clearly in-scope primary comparison. |
| 70 | W4406320500 | Include | C | BiomedRAG experiments analyze chunk granularity and noise/relevance across tasks. |
| 71 | W4406420357 | Include | C, R | Direct dynamic chunking plus cross-encoder reranking evaluation; retain as lower priority because evidence is less established. |
| 72 | W4406421570 | Include | Review | Clinical RAG systematic review/meta-analysis; retain as a domain-specific synthesis of RAG evidence. |
| 73 | W4406458829 | Exclude | — | Federated recommender application is outside the approved retrieval questions. |
| 74 | W4406771321 | Include | Review | Published RAG evaluation survey; retain this version and exclude its preprint at row 40. |
| 75 | W4406813548 | Exclude | — | Healthcare RAG perspective, not a direct method evaluation. |
| 76 | W4406892307 | Include | H | Directly compares hybrid and semantic retrieval; retain with a note that its evaluated corpus is Serbian. |
| 77 | W4407638153 | Include | C | Evaluates document chunk/knowledge-graph structure and retrieval post-processing. |
| 78 | W4407693761 | Include | C | Directly studies chunk merging/order and downstream RAG outcomes. |
| 79 | W4407835627 | Exclude | — | Building-engineering system combines vector, graph, and keyword retrieval, but is a domain prototype rather than a clean test of the target hybrid comparison. |
| 80 | W4407856367 | Exclude | — | Smart-manufacturing KG/vector application without a general target-method comparison. |
| 81 | W4408188072 | Exclude | — | Industrial knowledge-management application, not a direct retrieval-method study. |
| 82 | W4408985588 | Include | H | Tests dense-plus-keyword retrieval for RAG across domains; retain at lower priority pending source-quality review. |
| 83 | W4409157497 | Exclude | — | Medical fitness chatbot comparison does not isolate the target retrieval methods. |
| 84 | W4409256346 | Exclude | — | Tourism recommender application, with no abstract evidence of a relevant retrieval-method comparison. |
| 85 | W4409348640 | Exclude | — | Education chatbot survey is not a direct primary study and is not focused on the core retrieval questions. |
| 86 | W4409657176 | Exclude | — | Medical KG-RAG application without a target-method comparison. |
| 87 | W4409852347 | Include | C | Evaluates hierarchical segmentation/chunking against traditional chunking on QA datasets. |
| 88 | W4410030662 | Include | H | RAG-versus-long-context QA study analyzes retrieval depth/density; retain as adjacent evidence, with a medical-domain tag. |
| 89 | W4410600121 | Include | C | Evaluates document-structure graphs for retrieval on QA and manufacturing material. |
| 90 | W4410929991 | Exclude | — | General enterprise-search RAG description lacks a clear substantive method comparison. |
| 91 | W4410952162 | Exclude | — | Broad knowledge-assets article discusses pipeline components but does not clearly report a primary evaluation. |
| 92 | W4411119292 | Include | H | NAACL primary study of knowledge-graph-guided RAG retrieval. |
| 93 | W4411120044 | Include | H | Published NAACL HyPA-RAG version; use instead of workshop row 67. |
| 94 | W4411120331 | Include | H | NAACL method study of rationale-guided retrieval for QA; retain with a medical-domain tag. |
| 95 | W4411203672 | Exclude | — | Healthcare systematic review is secondary and application-specific under the proposed primary-study focus. |
| 96 | W4411310251 | Include | C | CAiSE study compares API-document chunking approaches and reports retrieval precision/recall. |
| 97 | W4411403197 | Exclude | — | Cache reuse/latency study is about inference systems, not retrieval quality, reranking, or chunking. |
| 98 | W4412377094 | Exclude | — | Personalized collaborative-filtering retrieval is a domain application. |
| 99 | W4412886844 | Exclude | — | Hybrid graph-plus-text knowledge bases do not test sparse-plus-dense retrieval or the other core questions. |
| 100 | W4412887933 | Exclude | — | Multimodal RAG survey is both secondary and outside the initial text scope. |
| 101 | W4412889429 | Include | H | Evaluates question decomposition as a multi-hop RAG retrieval method. |
| 102 | W4412889884 | Include | H | SeaKR evaluates self-aware/adaptive retrieval in RAG. |
| 103 | W4412889887 | Exclude | — | Knowledge-graph RAG recommendation application is outside the target questions. |
| 104 | W4412945697 | Include | C | ACL study evaluates chunking learners and chunk-quality measures in RAG. |
| 105 | W4413157284 | Include | H, R | Compares hybrid retrieval and reranking under compute constraints on a large document collection. |
| 106 | W4414128336 | Exclude | — | Healthcare RAG review is secondary and domain-focused under the proposed primary-study focus. |
| 107 | W4414371540 | Exclude | — | RAG caching/latency system does not evaluate retrieval, reranking, or chunking choices. |
| 108 | W4415813536 | Include | C | Compares fixed, semantic, proposition, and adaptive chunking; retain with a small-sample clinical-evaluation caveat. |
| 109 | W4416589125 | Exclude | — | Literature-screening application is not evidence about retrieval methods for the approved corpus. |
| 110 | W4417068614 | Include | H | DAT directly evaluates dynamically weighted sparse/dense retrieval in RAG. |
| 111 | W4417092524 | Include | R | DynamicRAG adapts document ordering and quantity using answer-quality feedback. |
| 112 | W7114889968 | Include | Review | Systematic RAG review synthesizes empirical studies; retain selectively as a field synthesis. |
| 113 | W7127049495 | Include | C | Evaluates structure-aware chunking for complex/nested tables using RAG metrics. |
| 114 | W7138120984 | Include | R | LiR3AG studies reranking quality, latency, and token tradeoffs. |

## Decision and coverage review

The user reviewed the candidate-level screening, selected **yes, selectively** for surveys and systematic reviews/meta-analyses, and explicitly agreed with every Include/Exclude choice. The reviewed decisions are imported into version 1 of the manifest: 67 included and 47 excluded. The user also approved the three coverage statuses; manifest v1 was then approved in the isolated review database. Inclusion advances a candidate to source and rights review; it does not authorize full-text acquisition.

Approved coverage assessment, drafted by Codex from candidate metadata and approved by the user:

- **Hybrid versus dense retrieval — covered.** The included shortlist contains several direct dense/hybrid comparisons across different corpora and settings. Results are context-specific; the shortlist is not a claim about corpus-wide recall.
- **Reranking quality and latency — covered.** Multiple included studies examine reranking methods, retrieval quality, or quality/cost tradeoffs. Full-text review must compare latency under each paper's stated setup because the experiments use different tasks and hardware.
- **Chunking and citation support — gap.** Chunking and evidence-retrieval comparisons are well represented, but the candidate metadata gives limited direct evidence about downstream citation support. Treat this as a research-coverage gap to check during the reference-set review, not a claim that no relevant work exists.

## Source checks for records with missing abstracts

The discovery export omitted abstracts for several high-priority records. Primary-source checks used to support these recommendations include [ColBERTv2](https://arxiv.org/abs/2112.01488), [Re2G](https://arxiv.org/abs/2207.06300), [CBR-RAG](https://arxiv.org/abs/2404.04302), [Interspeech reranking-feedback paper](https://www.isca-archive.org/interspeech_2024/nguyen24c_interspeech.pdf), [hierarchical text segmentation/chunking](https://arxiv.org/abs/2507.09935), [OpenAPI chunking](https://arxiv.org/abs/2411.19804), and [MoC chunking](https://aclanthology.org/2025.acl-long.258/). These source checks support screening only; they do not replace the later full-text, rights, and sample-verification gates.
