# Phase 1 embedding feasibility pilot

**Run date:** 2026-09-24<br>
**Status:** Reversible local indexing model selected for the Phase 1 pilot<br>
**Model:** `intfloat/e5-small-v2` at revision `e8b23a92af33fd81c865283d505f8f058a570cc8`

## Purpose and limits

This run checked whether the pinned English E5 model can embed a small set of
permitted, parser-produced chunks on the local laptop. It did not evaluate search
ranking, retrieval recall, citation support, or answer quality. The model choice
therefore remains subject to the fixed-question retrieval evaluation in Phase 2.

The [model card](https://huggingface.co/intfloat/e5-small-v2) specifies English
input, 384-dimensional embeddings, a 512-token maximum, and the `query: ` and
`passage: ` prefixes for retrieval. It documents mean pooling followed by
normalization. The model is MIT-licensed. The optional
[`sentence-transformers==6.1.0`](https://pypi.org/project/sentence-transformers/6.1.0/)
runtime is Apache-2.0 licensed.

## Measured workload

- 19 approved parser-produced page Markdown inputs from the ten reviewed PDFs.
- 56 text chunks, each limited to 480 source tokens with 64-token overlap.
- One batch of 16 at a time; each output has 384 float32 values.
- CUDA inference on the local RTX 3050 Laptop GPU; model files came from the
  pinned local Hugging Face revision.

| Measurement | Result |
| --- | ---: |
| First run, including model download and load | 25.164 s |
| First-run inference for 56 chunks | 0.98 s |
| Cached tokenizer and model initialization | 7.449 s |
| Cached inference for 56 chunks | 0.96 s |
| Cached-run peak process RSS | 1,390,309,376 bytes |
| CUDA allocated after load | 292,539,904 bytes |
| CUDA reserved after load | 367,001,600 bytes |
| Output vectors | 56 × 384 float32 (86,016 bytes) |

The downloaded `model.safetensors` file had SHA-256
`45bfa60070649aae2244fbc9d508537779b93b6f353c17b0f95ceccb1c5116c1`.
The selected index configuration ID is
`sha256:af4ae74756b20946caee031eefeb26aecad5963a451741ef833c66398f30dbe7`.
The reproducible sample settings are in
[`phase1-e5-small-v2-index.example.json`](../../configs/phase1-e5-small-v2-index.example.json)
and [`phase1-e5-small-v2-chunking.example.json`](../../configs/phase1-e5-small-v2-chunking.example.json).

## Decision and follow-up

The measured load, memory use, and batch inference fit the local pilot profile,
so E5-small-v2 is selected for the ten-paper extraction/indexing exercise.
Configuration, revision, dimension, distance metric, and prefixes are explicit
in the index adapter. The model weights and Sentence Transformers remain an
optional dependency; the default application and CI do not download them.

This is hardware feasibility evidence only. Phase 2 must compare ranking and
evidence retrieval against a fixed query set before treating this model as the
project's final embedding choice. No alternative model was benchmarked here.
