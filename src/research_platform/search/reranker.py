"""Profile-bound asynchronous adapter for batched cross-encoder scoring."""

from __future__ import annotations

import asyncio
import math
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Protocol

from research_platform.search.contracts import EvidenceHit
from research_platform.search.profiles import RerankerIdentity, RetrievalProfile
from research_platform.search.reranker_pairs import (
    RERANKER_PAIR_FORMAT_ID,
    PairTokenCounter,
    RerankerPairBudgetExceeded,
    build_reranker_pairs,
)


class CrossEncoderScorer(Protocol):
    """Synchronous model boundary; implementations return one raw score per pair."""

    def score_pairs(self, pairs: Sequence[tuple[str, str]]) -> Sequence[float]:
        """Score one batch without interpreting scores as probabilities."""


class RerankerAdapterError(RuntimeError):
    """Safe failure raised by the cross-encoder adapter."""


class RerankerProfileMismatch(ValueError):
    """The adapter identity does not match the requested retrieval profile."""


class RerankerCandidateLimitExceeded(ValueError):
    """The candidate pool exceeds its profile or adapter bound."""


class RerankerInferenceTimeout(RerankerAdapterError):
    """Scoring did not complete within the configured request budget."""


class RerankerInferenceFailure(RerankerAdapterError):
    """The model boundary failed before returning a complete candidate pool."""


class RerankerOutputAlignmentError(RerankerAdapterError):
    """The scorer did not return exactly one score for each input pair."""


class RerankerInvalidScoreError(RerankerAdapterError):
    """The scorer returned a value that cannot be used as a finite raw score."""


@dataclass(frozen=True)
class RerankerScore:
    """One source-preserving candidate with its raw score and reranked position."""

    evidence_hit: EvidenceHit
    score: float
    rank: int
    original_rank: int
    pair_format_id: str = RERANKER_PAIR_FORMAT_ID

    def __post_init__(self) -> None:
        if not isinstance(self.evidence_hit, EvidenceHit):
            raise ValueError("evidence_hit must be an EvidenceHit")
        if (
            isinstance(self.score, bool)
            or not isinstance(self.score, (int, float))
            or not math.isfinite(self.score)
        ):
            raise ValueError("score must be a finite raw ranking score")
        for name in ("rank", "original_rank"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        if self.pair_format_id != RERANKER_PAIR_FORMAT_ID:
            raise ValueError("unsupported reranker pair format")


class CrossEncoderReranker:
    """Score one bounded pool against the exact reranker identity in a profile.

    Token counting, pair construction and model inference run on one dedicated
    worker thread. Batches are processed serially so a model instance is never
    invoked concurrently by requests sharing this adapter.
    """

    def __init__(
        self,
        identity: RerankerIdentity,
        *,
        token_counter: PairTokenCounter,
        scorer: CrossEncoderScorer,
        batch_size: int = 4,
        maximum_candidates: int = 200,
        timeout_seconds: float = 15.0,
    ) -> None:
        if not isinstance(identity, RerankerIdentity):
            raise ValueError("identity must be a RerankerIdentity")
        if not callable(getattr(token_counter, "count_pair", None)):
            raise ValueError("token_counter must implement count_pair")
        if not callable(getattr(scorer, "score_pairs", None)):
            raise ValueError("scorer must implement score_pairs")
        for name, value in (
            ("batch_size", batch_size),
            ("maximum_candidates", maximum_candidates),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value <= 0
                or value > 200
            ):
                raise ValueError(f"{name} must be between 1 and 200")
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(timeout_seconds)
            or timeout_seconds <= 0
        ):
            raise ValueError("timeout_seconds must be finite and positive")

        self.identity = identity
        self._token_counter = token_counter
        self._scorer = scorer
        self.batch_size = batch_size
        self.maximum_candidates = maximum_candidates
        self.timeout_seconds = float(timeout_seconds)
        self._executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="cross-encoder"
        )
        self._closed = False

    async def rerank(
        self,
        profile: RetrievalProfile,
        query: str,
        candidates: Sequence[EvidenceHit],
    ) -> tuple[RerankerScore, ...]:
        """Return all candidates ordered by descending raw score.

        Equal scores retain original fused rank. Any timeout, over-budget pair,
        malformed score or failed batch returns no partial result.
        """
        rerank_limit = self._validate_request(profile, query, candidates)
        candidate_tuple = tuple(candidates)
        if len(candidate_tuple) > rerank_limit:
            raise RerankerCandidateLimitExceeded(
                "candidate pool exceeds the profile rerank limit"
            )
        if len(candidate_tuple) > self.maximum_candidates:
            raise RerankerCandidateLimitExceeded(
                "candidate pool exceeds the adapter maximum"
            )
        if not candidate_tuple:
            return ()
        if self._closed:
            raise RerankerInferenceFailure("reranker adapter is closed")

        loop = asyncio.get_running_loop()
        future = loop.run_in_executor(
            self._executor,
            self._score_candidates,
            query,
            candidate_tuple,
        )
        try:
            return await asyncio.wait_for(
                asyncio.shield(future), timeout=self.timeout_seconds
            )
        except TimeoutError:
            raise RerankerInferenceTimeout(
                "cross-encoder scoring exceeded its configured timeout"
            ) from None
        except (RerankerAdapterError, RerankerPairBudgetExceeded):
            raise
        except Exception:
            raise RerankerInferenceFailure(
                "cross-encoder scoring failed without a complete result"
            ) from None

    def close(self) -> None:
        """Stop accepting work and cancel queued batches; active inference may finish."""
        if not self._closed:
            self._closed = True
            self._executor.shutdown(wait=False, cancel_futures=True)

    def _validate_request(
        self,
        profile: RetrievalProfile,
        query: str,
        candidates: Sequence[EvidenceHit],
    ) -> int:
        if not isinstance(profile, RetrievalProfile):
            raise ValueError("profile must be a RetrievalProfile")
        if profile.reranker != self.identity:
            raise RerankerProfileMismatch(
                "retrieval profile does not select this reranker identity"
            )
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query must be non-empty")
        if isinstance(candidates, (str, bytes)) or not isinstance(candidates, Sequence):
            raise ValueError("candidates must be a sequence of EvidenceHit values")
        if any(not isinstance(hit, EvidenceHit) for hit in candidates):
            raise TypeError("candidates must contain EvidenceHit values")
        rerank_limit = profile.candidate_limits.rerank_top_k
        if rerank_limit is None:
            raise RerankerProfileMismatch(
                "retrieval profile does not configure a rerank candidate limit"
            )
        if rerank_limit > self.maximum_candidates:
            raise RerankerCandidateLimitExceeded(
                "profile rerank limit exceeds the adapter maximum"
            )
        return rerank_limit

    def _score_candidates(
        self, query: str, candidates: tuple[EvidenceHit, ...]
    ) -> tuple[RerankerScore, ...]:
        tokenizer_id = f"{self.identity.model}@{self.identity.revision}"
        try:
            pairs = build_reranker_pairs(
                query,
                candidates,
                token_counters={tokenizer_id: self._token_counter},
                maximum_pair_tokens=self.identity.maximum_input_tokens,
            )
        except (RerankerPairBudgetExceeded, RerankerAdapterError):
            raise
        except Exception:
            raise RerankerInferenceFailure(
                "cross-encoder pair preparation failed"
            ) from None
        scored: list[tuple[EvidenceHit, float, int]] = []
        pair_inputs = tuple((pair.query, pair.evidence_hit.text) for pair in pairs)
        for start in range(0, len(pair_inputs), self.batch_size):
            batch = pair_inputs[start : start + self.batch_size]
            try:
                batch_scores = self._scorer.score_pairs(batch)
            except Exception:
                raise RerankerInferenceFailure(
                    "cross-encoder batch inference failed"
                ) from None
            if isinstance(batch_scores, (str, bytes)) or not isinstance(
                batch_scores, Sequence
            ):
                raise RerankerOutputAlignmentError(
                    "cross-encoder output is not a score sequence"
                )
            if len(batch_scores) != len(batch):
                raise RerankerOutputAlignmentError(
                    "cross-encoder output count does not match its input batch"
                )
            for offset, raw_score in enumerate(batch_scores):
                if (
                    isinstance(raw_score, bool)
                    or not isinstance(raw_score, (int, float))
                    or not math.isfinite(raw_score)
                ):
                    raise RerankerInvalidScoreError(
                        "cross-encoder returned a non-finite or non-numeric score"
                    )
                pair = pairs[start + offset]
                scored.append(
                    (pair.evidence_hit, float(raw_score), pair.evidence_hit.rank)
                )

        scored.sort(key=lambda item: (-item[1], item[2], item[0].chunk_id))
        return tuple(
            RerankerScore(
                evidence_hit=evidence_hit,
                score=score,
                rank=rank,
                original_rank=original_rank,
            )
            for rank, (evidence_hit, score, original_rank) in enumerate(scored, start=1)
        )
