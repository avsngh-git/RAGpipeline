# Phase 1 discovery expansion: screening proposal

**Status: proposed for user approval. The v1 manifest remains approved and unchanged.**
No full texts were downloaded during these searches. Inclusion advances a paper to
source/rights review; it does not grant permission to store, extract, or index a
PDF.

## Search and deduplication

Two metadata-only OpenAlex runs were completed in the isolated review database:

| Run | Focus | Requests/pages | Cost | Draft shortlist |
|---|---|---:|---:|---|
| `969d32c5-0023-41ed-9e92-54c83772bf15` | Citation support and chunking | 20 | $0.02 | [v2 manifest](phase1-discovery-expansion-v2.json), 83 candidates |
| `19891419-f8bf-4d7e-9108-ffb5a5602eb2` | Sparse/dense retrieval and reranking latency | 20 | $0.02 | [v3 manifest](phase1-discovery-expansion-v3.json), 81 candidates |

Both queries per run reached the configured page ceiling. The exports therefore
remain bounded shortlists, not estimates of literature recall. Starting from
the 79 new OpenAlex records across both exports, I removed five records repeated
between the runs and four alternate records for publications already in v1,
using DOI and normalized title matches. That leaves 70 distinct new papers for
this screening proposal. The approved v1 still has 67 included papers and 47
excluded papers.

## Recommended additions

I recommend including these 33 papers. Together with the 67 v1 inclusions, they
form a 100-paper screened corpus if approved. The topic tags are **H** retrieval
methods, **R** ranking/reranking or efficiency, and **C** chunking, evidence, or
citation support.

| OpenAlex ID | Paper | Topics | Reason to include |
|---|---|---|---|
| W4385889719 | [Large Language Models for Information Retrieval: A Survey](https://openalex.org/W4385889719) | H, R | Synthesizes query rewriting, retrievers, rerankers, and readers; retain selectively for its direct IR-method coverage. |
| W4389520670 | [Enabling Large Language Models to Generate Text with Citations](https://openalex.org/W4389520670) | C | ALCE benchmarks retrieval-grounded answers and evaluates citation quality against human judgments. |
| W4399480372 | [RefAI: a GPT-powered retrieval-augmented generative tool for biomedical literature recommendation and summarization](https://openalex.org/W4399480372) | H, C | Evaluates literature search/ranking and source integration with expert judgments, close to the platform’s scientific-literature use case. |
| W4404781523 | [BERGEN: A Benchmarking Library for Retrieval-Augmented Generation](https://openalex.org/W4404781523) | H, R | Provides a reproducible comparison of retrievers, rerankers, datasets, and RAG metrics. |
| W4404784153 | [Model Internals-based Answer Attribution for Trustworthy Retrieval-Augmented Generation](https://openalex.org/W4404784153) | C | Tests whether answer attribution reflects retrieved evidence and compares citation quality. |
| W4406596702 | [Clinical entity augmented retrieval for clinical information extraction](https://openalex.org/W4406596702) | H, R | Directly compares entity retrieval with embedding retrieval and reports quality, latency, and token use. |
| W4411549467 | [FlashRAG: A Modular Toolkit for Efficient Retrieval-Augmented Generation Research](https://openalex.org/W4411549467) | H, R | Reproducible toolkit for comparing 16 RAG methods across datasets and standard metrics. |
| W4412673546 | [Correctness is not Faithfulness in Retrieval Augmented Generation Attributions](https://openalex.org/W4412673546) | C | Directly evaluates whether citations faithfully reflect evidence used by the generator. |
| W4412886806 | [MAIN-RAG: Multi-Agent Filtering Retrieval-Augmented Generation](https://aclanthology.org/2025.acl-long.131/) | H, R | ACL 2025 study filters noisy retrieved passages and measures answer-quality changes across four benchmarks. |
| W4409282347 | [Customized Retrieval Augmented Generation and Benchmarking for EDA Tool Documentation QA](https://openalex.org/W4409282347) | H, R | Provides a domain-specific QA benchmark and evaluates embedding and reranking methods against baselines. |
| W7127589252 | [Synthesizing scientific literature with retrieval-augmented language models](https://www.nature.com/articles/s41586-025-10072-4) | H, C | Published OpenScholar study evaluates scientific search, multi-paper synthesis, retrievers, and citation accuracy. |
| W3015883388 | [Dense Passage Retrieval for Open-Domain Question Answering](https://openalex.org/W3015883388) | H | Foundational dense retriever and a useful dense-only baseline for the hybrid comparison. |
| W3156836409 | [Zero-shot Neural Passage Retrieval via Domain-targeted Synthetic Question Generation](https://openalex.org/W3156836409) | H | Reports gains from combining term-based and neural retrieval, directly informing hybrid versus dense retrieval. |
| W3170739233 | [SPARTA: Efficient Open-Domain Question Answering via Sparse Transformer Matching Retrieval](https://openalex.org/W3170739233) | H, R | Compares efficient learned sparse retrieval with dense alternatives and reports effectiveness/efficiency tradeoffs. |
| W3172119680 | [COIL: Revisit Exact Lexical Match in Information Retrieval with Contextualized Inverted List](https://openalex.org/W3172119680) | H, R | Tests contextual lexical matching against lexical and neural retrievers, including latency. |
| W3203288040 | [Adversarial Retriever-Ranker for dense text retrieval](https://openalex.org/W3203288040) | H, R | Jointly trains a dense retriever and cross-encoder ranker and reports benchmark retrieval gains. |
| W3206455169 | [RocketQAv2: A Joint Training Method for Dense Passage Retrieval and Passage Re-ranking](https://openalex.org/W3206455169) | H, R | Directly evaluates joint dense retrieval and passage reranking. |
| W4281259526 | [ERNIE-Search: Bridging Cross-Encoder with Dual-Encoder via Self On-the-fly Distillation for Dense Passage Retrieval](https://openalex.org/W4281259526) | H, R | Studies cross-encoder knowledge transfer into dual-encoder retrieval on QA benchmarks. |
| W4297162632 | [Promptagator: Few-shot Dense Retrieval From 8 Examples](https://openalex.org/W4297162632) | H, R | Evaluates few-shot dense retrieval and subsequent reranking across retrieval datasets. |
| W4384656680 | [Lexically-Accelerated Dense Retrieval](https://openalex.org/W4384656680) | H, R | Measures a lexical-seeded dense retrieval approach on a recall/latency frontier. |
| W4389269373 | [Towards Effective and Efficient Sparse Neural Information Retrieval](https://openalex.org/W4389269373) | H, R | Evaluates learned sparse retrieval methods and latency improvements against keyword retrieval. |
| W4389524402 | [A Thorough Examination on Zero-shot Dense Retrieval](https://openalex.org/W4389524402) | H | An empirical analysis of when dense retrievers transfer and how they compare with sparse baselines. |
| W4396821195 | [Efficient Inverted Indexes for Approximate Retrieval over Learned Sparse Representations](https://openalex.org/W4396821195) | H, R | Quantifies latency and recall tradeoffs for learned sparse retrieval at scale. |
| W4402671832 | [ListT5: Listwise Reranking with Fusion-in-Decoder Improves Zero-shot Retrieval](https://openalex.org/W4402671832) | R | Compares listwise reranking effectiveness and inference efficiency on BEIR. |
| W4402854593 | [Retrieval-augmented generation for natural language processing: a survey](https://link.springer.com/article/10.1007/s10462-026-11605-7) | H, R | A recent RAG-focused synthesis of retrieval fusion, efficiency, and evaluation; retain selectively as technical context. |
| W4403006857 | [LegalBench-RAG: A Benchmark for Retrieval-Augmented Generation in the Legal Domain](https://openalex.org/W4403006857) | H, C | Human-annotated benchmark for retrieving precise evidence spans that support citations. |
| W4404781233 | [Open-RAG: Enhanced Retrieval Augmented Reasoning with Open-Source Large Language Models](https://openalex.org/W4404781233) | H, R | Evaluates adaptive retrieval and its effectiveness/speed tradeoff in RAG. |
| W4404782892 | [PromptReps: Prompting Large Language Models to Generate Dense and Sparse Representations for Zero-Shot Document Retrieval](https://openalex.org/W4404782892) | H | Directly evaluates a hybrid dense/sparse retrieval representation against zero-shot baselines. |
| W4404783040 | [Dense X Retrieval: What Retrieval Granularity Should We Use?](https://openalex.org/W4404783040) | H, C | Directly compares retrieval units and measures retrieval and downstream QA effects. |
| W4410634422 | [Dual retrieving and ranking medical large language model with retrieval augmented generation](https://openalex.org/W4410634422) | H, R | Compares hybrid search plus ColBERTv2 ranking with single-search RAG and reports accuracy/latency. |
| W4411113095 | [CodeRAG-Bench: Can Retrieval Augment Code Generation?](https://aclanthology.org/2025.findings-naacl.176/) | H | NAACL Findings benchmark compares ten retrievers and measures both retrieval and downstream RAG outcomes. |
| W4412888476 | [Document Segmentation Matters for Retrieval-Augmented Generation](https://aclanthology.org/2025.findings-acl.422/) | C | ACL Findings 2025 directly tests a chunking method and measures retrieval Hits@k and end-to-end QA. |
| W4414925442 | [MEGA-RAG: a retrieval-augmented generation framework with multi-evidence guided answer refinement for mitigating hallucinations of LLMs in public health](https://openalex.org/W4414925442) | H, R | Compares dense-plus-BM25 retrieval with reranking against baselines and reports answer-quality metrics. |

## Proposed exclusions

These 37 candidates either fall outside the three questions, duplicate a
preferred version, or are application/overview papers without a direct method
comparison. Exclusion is specific to this Phase 1 corpus, not a judgment that a
paper has no value.

| OpenAlex ID | Paper | Reason |
|---|---|---|
| W3003257820 | SciPy 1.0: fundamental algorithms for scientific computing in Python | General scientific-computing software; no retrieval/RAG study. |
| W3161760270 | Augmented Reality in Education: An Overview of Twenty-Five Years of Research | Unrelated application area. |
| W4224308101 | PaLM: Scaling Language Modeling with Pathways | General model scaling study; no retrieval-method evaluation. |
| W4327946446 | ChatGPT Utility in Healthcare Education, Research, and Practice: Systematic Review on the Promising Perspectives and Valid Concerns | Broad healthcare/ChatGPT review, not focused on RAG retrieval methods. |
| W4365134837 | Citation tracking for systematic literature searching: A scoping review | Reviews bibliographic search techniques, not citation support in RAG answers. |
| W4386510404 | Fabrication and errors in the bibliographic citations generated by ChatGPT | Studies generated citation errors without a retrieval-grounded system or retrieval comparison. |
| W4389519598 | FActScore: Fine-grained Atomic Evaluation of Factual Precision in Long Form Text Generation | General factuality evaluation; no direct retrieval, reranking, chunking, or citation-support comparison. |
| W4392565345 | Empowering personalized pharmacogenomics with generative AI solutions | Domain assistant evaluation without a retrieval-method comparison. |
| W4393621491 | Retrieval-Augmented Generation Approach: Document Question Answering using Large Language Model | Application-level QA comparison with unclear retrieval-method detail and non-diagnostic generation metrics. |
| W4398218462 | GastroBot: a Chinese gastrointestinal disease chatbot based on the retrieval-augmented generation | Chinese-language application outside the initial English-language scope. |
| W4400955423 | Enhancement of the Performance of Large Language Models in Diabetes Education through Retrieval-Augmented Generation: Comparative Study | Diabetes assistant compares base models with/without RAG, not retrieval choices. |
| W4402916777 | Wiki-LLaVA: Hierarchical Retrieval-Augmented Generation for Multimodal LLMs | Multimodal/image-text RAG, outside the text-focused corpus. |
| W4403493226 | Evaluating Retrieval-Augmented Generation Models for Financial Report Question and Answering | Financial application; does not isolate the targeted retrieval, reranking, chunking, or citation choices. |
| W4403646833 | Systematic Analysis of Retrieval-Augmented Generation-Based LLMs for Medical Chatbot Applications | Compares fine-tuning and RAG for a medical chatbot rather than retrieval methods. |
| W4408734515 | RAGVA: Engineering retrieval augmented generation-based virtual assistants in practice | Experience report and focus group, without a controlled target-method comparison. |
| W4412888702 | HopRAG: Multi-Hop Reasoning for Logic-Aware Retrieval-Augmented Generation | Graph-structured multi-hop retrieval is outside the core sparse/dense, reranking, chunking, and citation comparisons. |
| W4410251088 | Streamlining systematic reviews with large language models using prompt engineering and retrieval augmented generation | Applies RAG to literature screening; the task is not the retrieval/citation behavior under study. |
| W4411120544 | GRAG: Graph Retrieval-Augmented Generation | Graph-substructure retrieval is outside the approved sparse/dense, reranking, chunking, and citation comparisons. |
| W4411969741 | Retrieval-augmented generation elevates local LLM quality in radiology contrast media consultation | Application compares RAG with model baselines, not retrieval strategies. |
| W4412377217 | Parametric Retrieval Augmented Generation | Moves external knowledge into model parameters rather than evaluating document-retriever choices. |
| W4415233873 | A survey on retrieval-augmentation generation (RAG) models for healthcare applications | Domain-focused secondary review; less directly useful than the selected general RAG and retrieval-method sources. |
| W2995022099 | Advances and Open Problems in Federated Learning | Unrelated topic. |
| W3006487741 | Retrieval Topic Recurrent Memory Network for Remote Sensing Image Captioning | Image-captioning retrieval, outside text RAG. |
| W3140854437 | Review of deep learning: concepts, CNN architectures, challenges, applications, future directions | Broad deep-learning review with no focused retrieval/RAG evidence. |
| W3188983256 | Unsupervised Corpus Aware Language Model Pre-training for Dense Passage Retrieval | Dense-retriever training study, less direct to RAG pipeline choices than the selected foundational and comparative retrieval papers. |
| W4220818323 | On cross-lingual retrieval with multilingual text encoders | Primarily cross-lingual retrieval evaluation, outside the initial English retrieval scope. |
| W4221142221 | BERTopic: Neural topic modeling with a class-based TF-IDF procedure | Topic-modeling paper; “topic” is a search-term match, not retrieval-augmented generation. |
| W4229065825 | Retrieval-Enhanced Machine Learning | Broad conceptual retrieval-enhanced ML framework, not a direct RAG method comparison. |
| W4320465836 | A Neural Corpus Indexer for Document Retrieval | Generative document indexing rather than the approved RAG retrieval/reranking choices. |
| W4362515116 | A Survey of Large Language Models | Broad LLM survey, not retrieval-focused. |
| W4372272503 | Lift Yourself Up: Retrieval-augmented Text Generation with Self Memory | Self-generated memory for text generation rather than external document retrieval for QA. |
| W4382239620 | ConTextual Masked Auto-Encoder for Dense Passage Retrieval | Dense model pretraining study; overlaps the baseline retrieval question less directly than selected method comparisons. |
| W4385573402 | XRICL: Cross-lingual Retrieval-Augmented In-Context Learning for Cross-lingual Text-to-SQL Semantic Parsing | Cross-lingual Text-to-SQL task outside the initial English text-RAG scope. |
| W4392124699 | Merging Mixture of Experts and Retrieval Augmented Generation for Enhanced Information Retrieval and Reasoning | Early preprint centers model integration and general reasoning metrics, without a focused retrieval-method comparison. |
| W4404792869 | R2AG: Incorporating Retrieval Information into Retrieval Augmented Generation | Focuses on how the generator consumes retriever signals, not which retrieval, reranking, chunking, or citation methods work best. |
| W4411606774 | Medical LLMs: Fine-Tuning vs. Retrieval-Augmented Generation | Compares fine-tuning with RAG in healthcare, not alternative retrieval choices. |
| W4412875490 | Retrieval And Structuring Augmented Generation with Large Language Models | Broad secondary survey; overlaps the more directly RAG-focused selected survey and the primary studies. |

## Coverage recommendation

| Question | Proposed status | Basis and limit |
|---|---|---|
| When does hybrid retrieval outperform dense-only retrieval? | Covered | The combined shortlist now includes sparse/dense/hybrid comparisons across QA, open-domain retrieval, and RAG settings. Report each corpus and retrieval setup separately. |
| How much does cross-encoder reranking improve retrieval quality, and at what latency cost? | Covered | The combined shortlist includes cross-encoder, joint retriever-ranker, and listwise-reranker comparisons. Latency remains hardware- and candidate-count-specific. |
| How do chunking choices affect evidence retrieval and citation support? | Gap | Chunking and citation-support studies are both represented, but the current shortlist does not directly isolate how chunking choices change citation support. Preserve this as an open research gap. |

## Metadata source preflight (not permission)

The discovery-time OpenAlex primary-location fields report a PDF URL for 29 of
the 33 proposed papers. License metadata reports `cc-by` for 20 and
`cc-by-nc-nd` for 3; 10 records have no license reported. Four records have no
primary-location PDF URL: W4399480372, W4412673546, W4396821195, and
W4402854593. These are discovery metadata only: an OpenAlex license label or
PDF URL does not itself establish permission for the exact publisher/repository
copy, local storage, extraction, or indexing. Verify current source terms for
each selected version immediately before acquisition. The prior approval covers
only the original ten PDFs.

The read-only, source-level follow-up is recorded in the
[rights preflight](phase1-discovery-expansion-rights-preflight.md). It identifies
CC BY source terms for 23 candidates and 10 records that still need a separate
rights check: two ACM journal versions with unconfirmed item-level terms,
one accepted ACM version with a personal/classroom-use notice, one author-hosted
CC BY-NC-ND preprint statement, two CC BY-NC-SA alternate versions, three
publisher CC BY-NC-ND versions, and RefAI's repository copy. This is preliminary
source review, not permission or approval to acquire any PDF.

## Approval and next gate

This is a recommendation only. The v2/v3 manifests remain draft with undecided
candidate records; v1 remains untouched. Approval of these 33 additions would
create a 100-paper metadata-screened manifest. The separate source/rights review
must still approve the exact full-text version and storage/indexing permissions
for every paper before any further acquisition. No more PDFs were downloaded in
preparing this proposal.
