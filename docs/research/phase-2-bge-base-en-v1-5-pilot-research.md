# BGE-base-en-v1.5 source review and feasibility pilot for P2-07.2

**Reviewed:** 2026-09-26  
**Reviewer:** Assistant (Codex, under the user's Phase 2 delegation)  
**Scope:** Primary-source review of license, immutable repository revision, tokenizer, query prefix, input limit and Sentence Transformers loading configuration; bounded CPU/GPU feasibility measurements; and a full accepted-chunk tokenizer compatibility audit. This report does not evaluate retrieval quality.

## Verified source facts

| Item | Finding |
| --- | --- |
| Model / license | The BAAI repository identifies `BAAI/bge-base-en-v1.5` as an English sentence embedding model and declares the model license as MIT. This is the model repository's license metadata, separate from the installed inference library's license. [Model repository](https://huggingface.co/BAAI/bge-base-en-v1.5) |
| Immutable revision | On the review date, the model's current `main` resolved to **`a5beb1e3e68b9ab74eb54cfd186867f64f240e1a`**. The Hugging Face repository view displays short SHA `a5beb1e`; the current `config.json` resolution URL identifies the corresponding full cache revision. Pin the full SHA rather than `main`. [Revision-pinned repository](https://huggingface.co/BAAI/bge-base-en-v1.5/tree/a5beb1e3e68b9ab74eb54cfd186867f64f240e1a), [revision-pinned model card](https://huggingface.co/BAAI/bge-base-en-v1.5/blob/a5beb1e3e68b9ab74eb54cfd186867f64f240e1a/README.md), [current config resolution](https://huggingface.co/BAAI/bge-base-en-v1.5/resolve/main/config.json) |
| Embedding shape / backbone | The model card lists 768 dimensions and a 512-token sequence length. The repository config identifies a 12-layer BERT encoder with hidden size 768 and `max_position_embeddings: 512`. [Model card](https://huggingface.co/BAAI/bge-base-en-v1.5/blob/a5beb1e3e68b9ab74eb54cfd186867f64f240e1a/README.md), [model config](https://huggingface.co/BAAI/bge-base-en-v1.5/blob/a5beb1e3e68b9ab74eb54cfd186867f64f240e1a/config.json) |
| Tokenizer identity | The repository includes its `tokenizer.json` and `vocab.txt`; `tokenizer_config.json` declares `BertTokenizer`, `do_lower_case: true`, `model_max_length: 512`, and the standard BERT special tokens. Model config declares vocabulary size 30,522. Use these tokenizer assets from the exact same pinned model revision. [Tokenizer config](https://huggingface.co/BAAI/bge-base-en-v1.5/blob/a5beb1e3e68b9ab74eb54cfd186867f64f240e1a/tokenizer_config.json), [pinned repository files](https://huggingface.co/BAAI/bge-base-en-v1.5/tree/a5beb1e3e68b9ab74eb54cfd186867f64f240e1a) |
| Query instruction | The model list specifies the exact English retrieval prefix **`Represent this sentence for searching relevant passages: `** (including the trailing space). The model card says to prepend this instruction to search queries when retrieving passages and never to add it to passages. For v1.5, the card says instruction-free use has only a slight retrieval degradation overall, while recommending the prefix for short-query-to-long-document retrieval. [Model card: model list and usage guidance](https://huggingface.co/BAAI/bge-base-en-v1.5/blob/a5beb1e3e68b9ab74eb54cfd186867f64f240e1a/README.md) |
| Sentence Transformers artifact | `modules.json` specifies a built-in `Transformer` → `Pooling` → `Normalize` pipeline. The pooling config selects CLS-token pooling only (768 dimensions; mean/max pooling off). `sentence_bert_config.json` sets `max_seq_length: 512` and lowercasing. The Sentence Transformers metadata records model-export versions 2.2.2 / Transformers 4.28.1 / PyTorch 1.13.0+cu117; these are historical export metadata, not a runtime requirement. [Modules](https://huggingface.co/BAAI/bge-base-en-v1.5/blob/a5beb1e3e68b9ab74eb54cfd186867f64f240e1a/modules.json), [pooling config](https://huggingface.co/BAAI/bge-base-en-v1.5/blob/a5beb1e3e68b9ab74eb54cfd186867f64f240e1a/1_Pooling/config.json), [Sentence Transformers config](https://huggingface.co/BAAI/bge-base-en-v1.5/blob/a5beb1e3e68b9ab74eb54cfd186867f64f240e1a/sentence_bert_config.json), [export metadata](https://huggingface.co/BAAI/bge-base-en-v1.5/blob/a5beb1e3e68b9ab74eb54cfd186867f64f240e1a/config_sentence_transformers.json) |
| Loader controls | The model card documents loading with `SentenceTransformer("BAAI/bge-base-en-v1.5")`. Sentence Transformers supports a `revision` constructor argument accepting a Hub commit ID; `trust_remote_code` defaults to false. Its `encode` API defaults to batch size 32 and `normalize_embeddings=False`, while allowing explicit device and normalization settings. [Model card](https://huggingface.co/BAAI/bge-base-en-v1.5/blob/a5beb1e3e68b9ab74eb54cfd186867f64f240e1a/README.md), [SentenceTransformer loading and encode API](https://sbert.net/docs/package_reference/sentence_transformer/model.html) |

## Implications for the pilot

- Load with `SentenceTransformer("BAAI/bge-base-en-v1.5", revision="a5beb1e3e68b9ab74eb54cfd186867f64f240e1a", trust_remote_code=False, device=...)`. Specify `cpu` or `cuda` per run so device choice is recorded and timings are comparable. Keep model and tokenizer from that one revision.
- Encode passages without a BGE instruction. For the instruction-following arm, prefix only the raw query with the exact English string above. Since BGE v1.5 permits instruction-free input, record prefix use in embedding configuration and compare prefix/no-prefix on the same development queries before freezing it.
- The hard model input budget is 512 tokenizer tokens for the *entire formatted input*, including special tokens and any query prefix. Count with the pinned tokenizer; do not rely on hidden truncation or cut text/table units. The project’s protocol requires comparing BGE and E5 on the same source chunk IDs and checking both tokenizers; if a chunk does not fit both, define and disclose a common compatible set or variant. [P2-07 protocol](../plans/phase-2-retrieval-evaluation.md#p2-07--implement-dense-search-and-embedding-feasibility)
- The artifact includes CLS pooling and a Normalize module. Request `normalize_embeddings=True` explicitly during the pilot to make the cosine/unit-vector contract visible, then verify output dimensions and norms. It is consistent with BAAI's Sentence Transformers example, which normalizes embeddings for cosine similarity. [Model card](https://huggingface.co/BAAI/bge-base-en-v1.5/blob/a5beb1e3e68b9ab74eb54cfd186867f64f240e1a/README.md)
- The default `encode` batch size is 32, documented by Sentence Transformers; it is not evidence that 32 fits the laptop. Start with small declared batches and measure cold load, CPU/GPU latency and peak RAM/VRAM as P2-07.2 requires. Do not full-index until those measurements and the same-set token audit pass.
- Separate BGE vectors/index from E5. The 768-dimensional BGE vectors are incompatible with the existing 384-dimensional E5 index; model identity, revision, tokenizer/preprocessing, dimension, normalization and query prefix belong in the profile identity.

## Measured local feasibility

The accepted snapshot export was read locally from the permission-gated, read-only
Phase 1 review database artifact. The pilot never printed or copied source passage
text into a tracked file. The ignored local run directory is
`local-reference/phase2-runs/bge-base-en-v1.5-pilot-2026-09-26/`; it retains the
sample IDs and metadata-only JSON needed to replay the run.

The BGE sample contains twelve distinct chunks: four prose chunks selected nearest
800 characters without table separators, four pipe-table-like chunks nearest 800
characters, and four additional chunks with the highest BGE token counts in the
accepted selection. Selection ties use chunk ID. The first two groups represent
ordinary passage shapes; the last group exercises the longest accepted inputs.
Their BGE input lengths were respectively 156–194, 208–286, and 482–483 tokens.
All passage inputs omit a BGE prefix. The synthetic query used BAAI's exact query
prefix and was 21 BGE tokens including special tokens. The sample ID-set digest is
`sha256:5ad8c41439ba0da9d14c1e7698873ed8cc03631ff1d517caf85dc5f3c3583f25`.

Each device used FP32 inference, batch size 4, four PyTorch CPU threads, one
unmeasured warm-up pass, and five measured warm batches per input group. The numbers
below are medians and observed ranges for a batch of four passages, not p95 service
estimates. Model initialization was timed in a fresh process after the tokenizer and
samples had loaded; model files were locally cached and the OS file cache may have
been warm.

| Measurement | CPU | RTX 3050 Laptop GPU |
| --- | ---: | ---: |
| Runtime | PyTorch `2.14.0+cu130`; CUDA unavailable in that earlier driver state | PyTorch `2.14.0+cu130`; CUDA available after the Windows driver update propagated into WSL |
| Model initialization | 0.28 s | 2.31 s |
| Prose batch latency | 0.836 s (0.746–0.869) | 0.060 s (0.059–0.063) |
| Pipe-table-like batch latency | 1.282 s (1.197–1.338) | 0.077 s (0.075–0.077) |
| Near-limit batch latency | 2.344 s (2.154–2.538) | 0.141 s (0.140–0.142) |
| Process peak RSS | 1.34 GiB | 1.33 GiB |
| Peak GPU memory | unavailable | 490 MiB allocated / 574 MiB reserved |

The laptop has an Intel Core i5-11400H (6 cores / 12 threads), 7.6 GiB host RAM,
and an RTX 3050 Laptop GPU with 4 GiB VRAM. WSL exposes the Windows host's NVIDIA
driver to Linux processes; `nvidia-smi` run inside WSL reported driver 576.80
before the Windows driver update, when the installed `cu130` build could not
initialize CUDA. After the Windows host update, `nvidia-smi` inside WSL reported
617.14 and the same PyTorch `2.14.0+cu130` build detected the GPU. Final GPU
figures above were rerun in this normal project WSL environment. An isolated CUDA 12.6 wheel was used for an earlier
exploratory run and then removed; no project environment or dependency file changed.

BGE returned `(4, 768)` passage vectors and `(1, 768)` for the query. With explicit
normalization, observed vector norms ranged from 0.99999994 to 1.00000012. The
near-limit batch completed on both devices without truncation or out-of-memory;
the GPU process began with 3.46 GB free and ended with about 2.84 GB free. These
measurements support local feasibility for BGE-base-en-v1.5 on this laptop at batch
size 4. They do not estimate full-index build time or establish a quality advantage.

### P2-07.3 input compatibility audit

A metadata-only tokenizer pass examined all 44,277 unique chunks in accepted
snapshot `4b11fab3-d4a5-4e7a-a58e-8654accf2c6c`, using the pinned fast tokenizers and
model-specific passage formatting. Counts include special tokens; E5 includes
`passage: ` and BGE has no passage prefix.

| Model / revision | Minimum | Median | p95 | p99 | Maximum | Over 512 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| E5-small-v2 `e8b23a92af33fd81c865283d505f8f058a570cc8` | 5 | 15 | 482 | 482 | 485 | 0 |
| BGE-base-en-v1.5 `a5beb1e3e68b9ab74eb54cfd186867f64f240e1a` | 3 | 13 | 480 | 480 | 483 | 0 |

All 44,277 IDs fit both model input budgets, so the common compatible set is the
entire accepted selection. Its sorted-ID digest is
`sha256:823bd7cd64ed89f555add9ec4967777118b8c1845b4b949e260f88987c9016f8`.
No chunk was silently truncated or removed for this compatibility audit. Raw IDs and aggregate token statistics remain in the ignored local
`token-audit.json`; per-sample token counts are in the local pilot metrics.

## Unresolved / not measured

1. Retrieval quality and the relative effect of BGE's query prefix remain open for
development-set evaluation. This pilot is not a model-selection decision.
2. The complete embedding/index build over 44,277 chunks, storage footprint and
   rebuild behavior have not been measured. The pilot uses three small batches per
   repeat group, not a full index workload.
3. The upstream model repository declares MIT. The inference library license has
   not received a separate audit.

## Agent operating checklist

- This serves Phase 2 P2-07.2 and P2-07.3. BGE feasibility is supported for
  batch size 4 on the measured laptop; model choice remains OPEN pending retrieval
  evaluation.
- No application retrieval code or project dependency was added by the pilot. Hardware inference and all-chunk tokenizer auditing were run directly; there is no code-test result to report for this research artifact.
- Measurements retain model commit, runtime versions, tokenizer, prefixes, normalization, device, batch size, sample identity, timing repetitions and memory peaks. CI must not download weights.
- The upstream model repository declares MIT. No permanent technology/scope change is proposed, so no ADR or source-of-truth update is needed. An isolated CUDA 12.6 wheel used for an earlier exploratory run was removed; final GPU measurements used the default `cu130` runtime after the Windows driver update propagated into WSL.

Sources reviewed on 2026-09-26. The BGE repository and Sentence Transformers documentation are first-party sources for the model artifact and loader API. The revision SHA is the current `main` resolution captured on that date; it is an immutable content revision even if `main` advances later.
