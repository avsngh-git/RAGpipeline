# Phase 2 cross-encoder adapter

Status: P2-10.3–10.5 implemented and assistant-reviewed, 2026-09-27.

`search/reranker.py` provides `CrossEncoderReranker`, a framework-independent
asynchronous boundary around an injected synchronous scorer and pair-token counter.
The P2-10.5 model loader and fallback wrapper are described below.

## Request contract

- The requested `RetrievalProfile.reranker` must equal the adapter’s complete
  `RerankerIdentity` (model, revision, preprocessing revision and pair token cap).
- The service scores the first `rerank_top_k` fused candidates. On success it
  appends the remaining candidates in unchanged hybrid order. The adapter’s configured
  maximum also bounds the scored prefix.
- The profile’s exact model and revision identify the tokenizer counter. Pair
  construction uses `query-source-chunk-v1` and fails the complete request if a pair
  exceeds the identity’s token cap.
- Scoring receives `(query, stored evidence text)` pairs in bounded batches. Pair
  counting and all batches run on a dedicated single-worker thread, outside the async
  event loop; requests sharing one adapter are serialized.

## Results and failure behavior

Each `RerankerScore` retains the exact `RerankerIdentity`, full retrieval profile ID,
SHA-256 of the exact query, original immutable `EvidenceHit`, original fused rank,
finite raw cross-encoder score, and new reranked position. Higher scores rank first. Equal scores preserve original fused rank, with chunk ID as a final stable
tie key. Scores are not calibrated probabilities, and earlier component values are
not rewritten by this adapter.

Every batch must return exactly one finite numeric score per input. Token-budget
violations, malformed scores, misaligned output, inference exceptions and timeout
produce errors without returning partial score records. Timeout includes time queued
behind another inference on the same adapter. Python cannot stop a synchronous model
call already running in its worker thread; after a timeout that call may finish in the
background, while subsequent work stays serialized behind it. P2-10.5 owns caller
fallback and safe failure reporting.

Focused fake-boundary tests cover identity, batching, event-loop isolation, alignment,
finite scores, stable ties, count limits, timeout, pair overflow and partial failure.
No model weights, real-model selection, search-service integration or quality
evaluation is included in P2-10.3.

## Applying results to evidence hits

`search/reranker_results.py` applies result records against the original candidate
sequence and profile. It requires a hybrid profile and verifies exact one-to-one
chunk coverage, unchanged evidence values, matching model identity, sequential output
ranks, and retained original fused ranks. It updates `EvidenceHit.rank`, preserves the
lexical, dense and fusion components verbatim, and records the cross-encoder's raw
score and reranked position in its own component. A candidate outside the input pool,
a missing/duplicate candidate, or an already-reranked hit is rejected.

## Pinned models and safe fallback

`search/reranker_models.py` supports only the two exact P2-10.1 revisions: MiniLM
(`cross-encoder/ms-marco-MiniLM-L6-v2`,
`233902d25c440f23af6f7d6e94d2946bac0bee0a`) and BGE
(`BAAI/bge-reranker-base`, `2cfc18c9415c912f9d8155881c133215df768a70`). It reads
from the local Hugging Face cache or an explicit cache directory with
`local_files_only=True`; it does not download weights or execute Hub-provided code.
The loader uses FP32, the 512-token cap, and a fast tokenizer. CUDA may be requested
explicitly or selected when available. It surfaces safe typed errors for missing
weights/runtime, unavailable CUDA and device exhaustion.

The official CrossEncoder API supports pinned revisions and offline loading. Its
published default can apply sigmoid when there is one output label, so inference
explicitly passes identity activation and disables softmax to keep raw ranking logits
([CrossEncoder API](https://www.sbert.net/docs/package_reference/cross_encoder/model.html),
[Sentence Transformers 6.1.0 source](https://github.com/huggingface/sentence-transformers/blob/v6.1.0/sentence_transformers/cross_encoder/model.py)).

`search/reranker_service.py` reranks only the configured leading candidates and
appends the untouched fused tail after a complete score result. It catches only
controlled inference and pair-budget errors. On failure it returns the original fused
`EvidenceHit` tuple unchanged with effective mode `hybrid`. Safe failure metadata
identifies the profile, snapshot, model, revision and error type without including
query text, passage text or exception messages. Integrity/provenance errors still fail
closed instead of being hidden as fallback.

Both pinned models passed a one-pair synthetic local-only WSL CUDA smoke through the
model loader and the full profile-bound scoring/provenance path. This confirms runtime
compatibility only; retrieval quality has not been evaluated and no model was selected.
