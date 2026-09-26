# Phase 2 cross-encoder candidates: source review and feasibility pilot

**Reviewed:** 2026-09-27
**Reviewer:** Assistant (Codex, under the user's Phase 2 delegation)
**Scope:** Primary-source audit and bounded local CPU/WSL-GPU feasibility pilot for P2-10.1: current model revisions, model-declared licenses, pair formatting, input limits, documented inference paths, and measured resource use. Pinned public weights were downloaded to /tmp; local raw metadata stays under ignored local-reference. This report measures feasibility only, not retrieval quality, and does not select a winner.

## Candidate summary

| Item | MS MARCO MiniLM-L6-v2 | BGE reranker base |
| --- | --- | --- |
| Canonical Hub ID | `cross-encoder/ms-marco-MiniLM-L6-v2`. The spelling with `L-6` redirects to this ID. | `BAAI/bge-reranker-base` |
| Hub revision observed on review date | `233902d25c440f23af6f7d6e94d2946bac0bee0a` ([pinned tree](https://huggingface.co/cross-encoder/ms-marco-MiniLM-L6-v2/tree/233902d25c440f23af6f7d6e94d2946bac0bee0a), [commit](https://huggingface.co/cross-encoder/ms-marco-MiniLM-L6-v2/commit/233902d25c440f23af6f7d6e94d2946bac0bee0a)) | `2cfc18c9415c912f9d8155881c133215df768a70` ([pinned tree](https://huggingface.co/BAAI/bge-reranker-base/tree/2cfc18c9415c912f9d8155881c133215df768a70), [commit](https://huggingface.co/BAAI/bge-reranker-base/commit/2cfc18c9415c912f9d8155881c133215df768a70)) |
| Model-declared license | Apache-2.0 in the model card metadata. The model repository's published file list does not show a separate `LICENSE` file. The Sentence Transformers software repository has its own Apache-2.0 license; that software license is not used here as a substitute for the model's license declaration. ([model card](https://huggingface.co/cross-encoder/ms-marco-MiniLM-L6-v2/blob/233902d25c440f23af6f7d6e94d2946bac0bee0a/README.md), [Sentence Transformers LICENSE](https://github.com/huggingface/sentence-transformers/blob/main/LICENSE)) | MIT in the model card metadata. The card also says the released models may be used commercially without charge and links the upstream FlagEmbedding MIT license. ([model card](https://huggingface.co/BAAI/bge-reranker-base/blob/2cfc18c9415c912f9d8155881c133215df768a70/README.md), [FlagEmbedding LICENSE](https://github.com/FlagOpen/FlagEmbedding/blob/master/LICENSE)) |
| Language and backbone | English; six-layer BERT sequence classifier, hidden size 384; Hub reports 22.7M parameters. ([model card](https://huggingface.co/cross-encoder/ms-marco-MiniLM-L6-v2/blob/233902d25c440f23af6f7d6e94d2946bac0bee0a/README.md), [config](https://huggingface.co/cross-encoder/ms-marco-MiniLM-L6-v2/blob/233902d25c440f23af6f7d6e94d2946bac0bee0a/config.json)) | English and Chinese; XLM-RoBERTa sequence classifier, 12 layers, hidden size 768. ([model card](https://huggingface.co/BAAI/bge-reranker-base/blob/2cfc18c9415c912f9d8155881c133215df768a70/README.md), [config](https://huggingface.co/BAAI/bge-reranker-base/blob/2cfc18c9415c912f9d8155881c133215df768a70/config.json)) |
| Pair input and documented cap | One `(query, passage)` pair per candidate; lower-casing BERT tokenizer; 512 tokens for the entire pair, as indicated by both tokenizer and model configs. ([model-card inference example](https://huggingface.co/cross-encoder/ms-marco-MiniLM-L6-v2/blob/233902d25c440f23af6f7d6e94d2946bac0bee0a/README.md), [tokenizer config](https://huggingface.co/cross-encoder/ms-marco-MiniLM-L6-v2/blob/233902d25c440f23af6f7d6e94d2946bac0bee0a/tokenizer_config.json), [model config](https://huggingface.co/cross-encoder/ms-marco-MiniLM-L6-v2/blob/233902d25c440f23af6f7d6e94d2946bac0bee0a/config.json)) | One `(query, document)` pair per candidate; XLM-RoBERTa tokenizer; upstream inference example sets `max_length=512` with truncation, so treat 512 as the total formatted pair budget. The model config has 514 position slots, but the published inference recipe uses 512. ([model-card inference example](https://huggingface.co/BAAI/bge-reranker-base/blob/2cfc18c9415c912f9d8155881c133215df768a70/README.md), [tokenizer config](https://huggingface.co/BAAI/bge-reranker-base/blob/2cfc18c9415c912f9d8155881c133215df768a70/tokenizer_config.json), [model config](https://huggingface.co/BAAI/bge-reranker-base/blob/2cfc18c9415c912f9d8155881c133215df768a70/config.json)) |
| Supported inference shown upstream | Sentence Transformers `CrossEncoder.predict` over a list of query/passage pairs, or Transformers `AutoModelForSequenceClassification`; the Hub tags PyTorch, ONNX and OpenVINO. ([model card](https://huggingface.co/cross-encoder/ms-marco-MiniLM-L6-v2/blob/233902d25c440f23af6f7d6e94d2946bac0bee0a/README.md), [CrossEncoder API](https://www.sbert.net/docs/package_reference/cross_encoder/model.html)) | FlagEmbedding `FlagReranker.compute_score` over one pair or a list of pairs, or Transformers `AutoModelForSequenceClassification`; upstream documents PyTorch and ONNX paths. ([FlagEmbedding reranker guide](https://github.com/FlagOpen/FlagEmbedding/blob/master/examples/inference/reranker/README.md), [model card](https://huggingface.co/BAAI/bge-reranker-base/blob/2cfc18c9415c912f9d8155881c133215df768a70/README.md)) |
| Source-backed resource facts | One `model.safetensors` file is listed as 90.9 MB. The card reports 1,800 documents/second on a V100 for its MS MARCO/TREC evaluation table. ([pinned files](https://huggingface.co/cross-encoder/ms-marco-MiniLM-L6-v2/tree/233902d25c440f23af6f7d6e94d2946bac0bee0a), [model-card performance table](https://huggingface.co/cross-encoder/ms-marco-MiniLM-L6-v2/blob/233902d25c440f23af6f7d6e94d2946bac0bee0a/README.md)) | One `model.safetensors` file is listed as 1.11 GB. FlagEmbedding documents optional FP16 inference as faster with a slight performance degradation, but provides no comparable laptop latency or peak-memory measurement for this base model in the reviewed sources. ([pinned files](https://huggingface.co/BAAI/bge-reranker-base/tree/2cfc18c9415c912f9d8155881c133215df768a70), [FlagEmbedding reranker guide](https://github.com/FlagOpen/FlagEmbedding/blob/master/examples/inference/reranker/README.md)) |

The file sizes above describe individual published weight artifacts, not resident memory. The Hub repository totals include multiple formats and exported files; those totals should not be mistaken for the disk or memory needed by a particular loader.

## Confirmed source facts

### Revision identity

The current MiniLM Hub page resolves to `cross-encoder/ms-marco-MiniLM-L6-v2`; opening the `L-6` spelling redirects to this canonical ID. The current `main` snapshot observed on 2026-09-27 is commit `233902d25c440f23af6f7d6e94d2946bac0bee0a`. The current BGE base snapshot observed the same day is `2cfc18c9415c912f9d8155881c133215df768a70`. Future configuration should pin these full SHAs instead of `main`; a later model run should recheck whether the project still intends these revisions.

### License and intended task

The MiniLM model card identifies Apache-2.0 and says this cross-encoder was trained on the MS MARCO Passage Ranking task. The card describes reranking passages for a query. Its published performance row reports NDCG@10 74.30 on TREC DL 2019, MRR@10 39.01 on MS MARCO dev, and 1,800 documents/second on a V100. These are the model publisher's historical task results, not an independent comparison on this project's candidate pools. The model's MiniLM backbone is described in the original [MiniLM paper](https://arxiv.org/abs/2002.10957), which presents self-attention distillation for compressing pretrained transformers; it does not itself evaluate this MS MARCO fine-tuned checkpoint.

The BGE card declares MIT for `BAAI/bge-reranker-base`, labels it English and Chinese, and describes it as a cross-encoder that consumes a question and document jointly to produce a relevance score. The card notes that cross-entropy training leaves the score unbounded and that higher scores indicate greater relevance. Its cited [C-Pack paper](https://arxiv.org/abs/2309.07597) presents BGE embedding models and resources; that paper does not specifically document this reranker checkpoint's inference resource use. For this checkpoint, the model card and [FlagEmbedding's reranker guide](https://github.com/FlagOpen/FlagEmbedding/blob/master/examples/inference/reranker/README.md) are the direct sources for its usage and score behavior.

### Input formatting and truncation

Both models are cross-encoders: each candidate must be scored jointly with the query. The official MiniLM example passes `(query, passage)` pairs to `CrossEncoder.predict`; its Transformers example passes separate query and passage batches to the BERT tokenizer with `truncation=True`. The tokenizer config says `do_lower_case: true`, and the model config gives 512 maximum positions and one output label. No query instruction or evidence prefix is prescribed by the MiniLM card.

The official BGE example passes `[query, passage]` pairs through `AutoTokenizer` with `truncation=True` and `max_length=512`. The tokenizer config sets `model_max_length` to 512. Its XLM-RoBERTa model config has `max_position_embeddings: 514`, but that architectural setting is not a reason to exceed the 512-token limit in the published scoring example. The reranker examples use the raw query and passage; the optional query/passage instruction parameters in the broader FlagEmbedding interface should remain unset unless the pilot explicitly tests and records them.

For both candidates, count query text, any added title/section/table context, pair separators, and other special tokens inside the 512-token budget. The models accept strings, not structured tables. They do not document table-aware parsing or guarantee that naive truncation preserves row/header associations.

### Inference and score interpretation

Sentence Transformers documents `CrossEncoder.predict` as batched pair prediction (default batch size 32), with selectable `torch`, `onnx`, or `openvino` backends, device selection, and a configurable sequence length. Its model constructor accepts a pinned Hub revision and defaults `trust_remote_code` to false. The MiniLM model card also shows ordinary Transformers sequence-classification inference under `eval()` and `torch.no_grad()`.

FlagEmbedding documents `FlagReranker` for BGE base and accepts one pair or a list of query/document pairs. Its Transformers example uses `AutoModelForSequenceClassification`; the default model score is a raw, unbounded scalar, and an optional sigmoid mapping is available. FP16 is an optional inference mode in FlagEmbedding. These wrapper-specific choices do not establish speed or quality for a chosen batch size on this laptop.

Raw scores from the two models should not be compared numerically or interpreted as calibrated probabilities. Compare candidate ordering and retrieval metrics; if sigmoid is evaluated for BGE, record it as score postprocessing rather than as evidence of probability calibration.

## Resource evidence and limits

- MiniLM's Hub performance table reports 1,800 documents/second on a V100. Its details are insufficient to treat that as an RTX 3050, CPU, or service-level estimate.
- The Hub lists a 90.9 MB MiniLM safetensors file and a 1.11 GB BGE safetensors file. These are download footprints, not resident memory. Alternate weights and exports make repository totals unsuitable as loaded-model RAM/VRAM estimates.
- The reviewed BGE instructions describe optional FP16 inference as faster with slight performance degradation, but provide no comparable laptop measurement.
- **Measured 2026-09-27:** both pinned candidates ran in the same WSL project environment with PyTorch 2.14.0+cu130, CUDA build 13.0, Sentence Transformers 6.1.0 and Transformers 5.17.0. From inside WSL, nvidia-smi reported the RTX 3050 Laptop GPU, the Windows host driver exposed as 617.14, and 4096 MiB total memory. Runs were sequential, FP32, batch size 4, one warm-up and five timed repetitions for each group of four pairs.
- A deterministic sample contained 12 unique development query/source-chunk pairs: four prose, four table-like and four longest-fitting. Each pair was the same for both models and devices (pair-set SHA-256: 185e703b43a411fe75f5740e94070312e8d2e6c930984145e08b28350327c6de). The query and original chunk were passed as a raw tokenizer pair, with no prefix or added title/context. Both tokenizers were audited without truncation; selected pair lengths were MiniLM/BGE 183–272/223–287 tokens for prose, 306–396/366–438 for table-like, and 342–496/417–512 for longest-fitting. Across the sample-construction space, 5,970 development query/source-chunk pairings were checked; 42 exceeding 512 in either tokenizer were excluded whole before inference. These are resource inputs, not retrieved candidates or a ranking evaluation.
- All twelve pairs in every run returned four finite scores with the expected alignment. No candidate failed to load or infer at batch size 4; the longest-fitting group included a 512-token BGE pair.

| Candidate / device | Model load | Peak process RSS | Peak GPU allocated / reserved | Prose median (range), 4 pairs | Table-like median (range), 4 pairs | Longest-fit median (range), 4 pairs |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| MiniLM / CPU | 0.198 s | 1.275 GiB | — | 0.1329 s (0.1275–0.1904) | 0.2824 s (0.2040–0.3084) | 0.3386 s (0.3040–0.3545) |
| MiniLM / WSL GPU | 0.294 s | 1.553 GiB | 128 / 170 MiB | 0.0182 s (0.0178–0.0195) | 0.0242 s (0.0233–0.0274) | 0.0306 s (0.0301–0.0308) |
| BGE / CPU | 2.293 s | 1.951 GiB | — | 1.1149 s (0.9787–1.1953) | 1.7996 s (1.6472–1.8207) | 2.0602 s (1.8981–2.3422) |
| BGE / WSL GPU | 2.188 s | 2.589 GiB | 1,137 / 1,256 MiB | 0.0793 s (0.0783–0.0819) | 0.1235 s (0.1230–0.1299) | 0.1444 s (0.1435–0.1452) |

GPU allocated/reserved reports the inference peak after model load; MiniLM used 87 MiB allocated after load, and BGE used 1,061 MiB. BGE began with 3.222 GiB free in WSL. Peak process RSS includes the Python runtime and tokenizer as well as the model. Model-load timing began after input selection, and local file/OS caches may have been warm. Timings include tokenization, transfer and inference; five repeats provide medians and ranges, not a credible p95 or service benchmark. Raw scores were checked for finite alignment but not retained or interpreted.

## Practical implications for the remaining P2-10 work

These are implementation inferences from the confirmed source behavior and approved roadmap, not model-selection judgments:

1. Use the same saved hybrid candidate lists for both rerankers, keep each model's full revision and tokenizer identity in configuration, and compare rank-based metrics rather than raw scores.
2. Make pair formatting explicit and version it. Any paper title, section name, table caption, header, unit or footnote added to the document side consumes the same 512-token pair budget and must not be silently clipped.
3. P2-10.2 freezes raw source-chunk pairs and an all-or-fail 512-token policy;
   over-budget results require explicit caller fallback rather than evidence loss.
4. FP32 batch size 4 is feasible on this laptop for the measured pair groups. Batch sizes above 4 and FP16 remain unmeasured; the library's default batch size 32 and upstream FP16 examples are not local feasibility evidence.

## Unknowns and limitations

- Comparative ranking quality on this project's fixed hybrid candidates, including scientific prose and table-cell questions, is unmeasured.
- Service-level latency over the full candidate limit, p95 latency, larger batches, FP16, and a full device-exhaustion boundary remain unmeasured. No BGE base throughput figure was found that can be compared to the MiniLM V100 result.
- The optimal batch size, dtype and final pair formatting for this project remain unresolved. The upstream docs leave batch-size tuning dependent on hardware, model size, precision and input length.
- Neither candidate's model card documents table-structure semantics. The project must provide and evaluate table-aware text formatting at the application boundary.
- The model cards identify licenses, but this source review is not a legal opinion or a review of every upstream training-data license. Keep the model-artifact license distinct from the license on the inference library and source training data.

## Agent operating checklist

- **Phase/task:** Phase 2, P2-10.1 source review and bounded resource pilot. This report supports the approved comparison of MiniLM-L6-v2 and BGE reranker base.
- **Decision state:** both candidates are feasible for batch-size-4 FP32 inference on the measured laptop. Exact reranker choice and settings remain OPEN until development retrieval evaluation.
- **Tests and telemetry:** the local ignored pilot script ran four offline model/device combinations; every group completed with finite aligned outputs. Raw IDs, timings and memory records remain local. No quality score was computed. P2-10.2 freezes table-aware source-chunk preservation and pair overflow behavior; quality remains unmeasured.
- **Scope and consequences:** no project dependency, application code, database, index, or accepted snapshot changed. Pinned model files are confined to /tmp. No ADR or source-of-truth amendment is proposed; model selection remains OPEN.
- **Review limits:** findings are assistant-reviewed, rely on upstream model/library sources and cited papers, and are not independently human-validated. The Hub revisions are those observed on 2026-09-27.
