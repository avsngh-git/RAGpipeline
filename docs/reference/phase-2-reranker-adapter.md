# Phase 2 cross-encoder adapter

Status: P2-10.3 implemented and assistant-reviewed, 2026-09-27.

`search/reranker.py` provides `CrossEncoderReranker`, a framework-independent
asynchronous boundary around an injected synchronous scorer and pair-token counter.
Model loading and application-level fallback are separate follow-up substeps.

## Request contract

- The requested `RetrievalProfile.reranker` must equal the adapter’s complete
  `RerankerIdentity` (model, revision, preprocessing revision and pair token cap).
- The supplied query and candidate sequence are scored as provided. The profile’s
  `rerank_top_k` and the adapter’s configured maximum both bound candidate count.
- The profile’s exact model and revision identify the tokenizer counter. Pair
  construction uses `query-source-chunk-v1` and fails the complete request if a pair
  exceeds the identity’s token cap.
- Scoring receives `(query, stored evidence text)` pairs in bounded batches. Pair
  counting and all batches run on a dedicated single-worker thread, outside the async
  event loop; requests sharing one adapter are serialized.

## Results and failure behavior

Each `RerankerScore` retains the original immutable `EvidenceHit`, its original fused
rank, a finite raw cross-encoder score, and its new reranked position. Higher scores
rank first. Equal scores preserve original fused rank, with chunk ID as a final stable
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
