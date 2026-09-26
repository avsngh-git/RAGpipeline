# ADR-0005: Phase 1 embedding pilot

- Status: Accepted for the Phase 1 pilot; final retrieval-quality choice remains open
- Date: 2026-09-24

## Context

Phase 1 needs a locally runnable embedding model for English prose and table
chunks, with reproducible vector dimensions and preprocessing. The laptop has
4 GiB of VRAM and 7.6 GiB of RAM. Model feasibility can be measured on the
user-approved ten-paper reference set, but retrieval quality cannot be inferred
from an embedding-throughput test.

## Decision

Use `intfloat/e5-small-v2`, pinned to Hugging Face revision
`e8b23a92af33fd81c865283d505f8f058a570cc8`, for the Phase 1 local indexing
pilot. Use the optional `sentence-transformers==6.1.0` dependency; keep it out
of the ordinary runtime and CI dependency set.

Use the model's required `passage: ` prefix for indexed chunks and `query: ` for
search queries. Keep the pinned 384-dimensional vectors, 512-token model limit,
mean pooling, and L2 normalization. The pilot chunking configuration limits
source text chunks to 480 tokens with 64-token overlap; long table rows are
split into cell chunks that repeat applicable row and column headers.

The model card identifies the model as English-only, MIT-licensed, 384
dimensional, and limited to 512 tokens. The Sentence Transformers package is
Apache-2.0 licensed. See the [embedding pilot report](../reference/phase-1-embedding-pilot.md)
for the measured local footprint, pinned model-file hash, and limitations.

## Alternatives considered

1. **Keep the model unspecified.** This avoids a pilot implementation but does
   not let Phase 1 measure the complete local extraction-to-index path.
2. **Select a larger embedding model.** Deferred because this pilot prioritizes
   feasibility on the measured laptop; no evidence currently justifies the
   additional memory and runtime.
3. **Treat this benchmark as proof of retrieval quality.** Rejected. The run
   measures load time, inference time, memory, and vector shape only.

## Consequences

The index configuration and preprocessing are recorded in
[`configs/phase1-e5-small-v2-index.example.json`](../../configs/phase1-e5-small-v2-index.example.json).
The pinned model is a reversible Phase 1 pilot choice, not the final production
embedding decision. Phase 2 must compare retrieval quality on fixed questions
and evidence before that decision is closed.

The model is English-only and truncates inputs beyond 512 tokens. The 480-token
chunk limit leaves room for the model's passage prefix. Model weights are
downloaded only when the optional embedding adapter is used.

## Sources

- [Official E5-small-v2 model card](https://huggingface.co/intfloat/e5-small-v2)
- [Sentence Transformers 6.1.0 on PyPI](https://pypi.org/project/sentence-transformers/6.1.0/)
