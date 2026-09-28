"""Run reranking with explicit, source-preserving hybrid fallback."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from research_platform.search.contracts import EvidenceHit, RetrievalMode
from research_platform.search.profiles import RerankerIdentity, RetrievalProfile
from research_platform.search.reranker import (
    CrossEncoderReranker,
    RerankerAdapterError,
)
from research_platform.search.reranker_pairs import RerankerPairBudgetExceeded
from research_platform.search.reranker_results import apply_reranker_scores


@dataclass(frozen=True)
class RerankerFailureDetails:
    """Safe failure identity with no query, evidence text or exception message."""

    profile_id: str
    snapshot_id: UUID
    reranker: RerankerIdentity
    error_type: str
    fallback_mode: Literal["hybrid"] = "hybrid"

    def __post_init__(self) -> None:
        if not isinstance(self.profile_id, str) or not self.profile_id.strip():
            raise ValueError("profile_id must be non-empty")
        if not isinstance(self.snapshot_id, UUID):
            raise ValueError("snapshot_id must be a UUID")
        if not isinstance(self.reranker, RerankerIdentity):
            raise ValueError("reranker must be a RerankerIdentity")
        if not isinstance(self.error_type, str) or not self.error_type.strip():
            raise ValueError("error_type must be non-empty")
        if self.fallback_mode != "hybrid":
            raise ValueError("reranker fallback must return hybrid mode")

    def to_dict(self) -> dict[str, object]:
        return {
            "stage": "reranker",
            "profile_id": self.profile_id,
            "snapshot_id": str(self.snapshot_id),
            "reranker_model": self.reranker.model,
            "reranker_revision": self.reranker.revision,
            "reranker_preprocessing_revision": self.reranker.preprocessing_revision,
            "error_type": self.error_type,
            "requested_mode": RetrievalMode.RERANKED.value,
            "effective_mode": self.fallback_mode,
            "message": "reranking failed; unchanged hybrid order was returned",
        }


@dataclass(frozen=True)
class RerankerStageOutcome:
    """Effective ranked evidence plus optional safe reranker failure metadata."""

    hits: tuple[EvidenceHit, ...]
    effective_mode: Literal["reranked", "hybrid"]
    failure: RerankerFailureDetails | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.hits, tuple) or any(
            not isinstance(hit, EvidenceHit) for hit in self.hits
        ):
            raise ValueError("hits must be a tuple of EvidenceHit values")
        if self.effective_mode not in {"reranked", "hybrid"}:
            raise ValueError("effective_mode must be reranked or hybrid")
        if (self.effective_mode == "hybrid") != (self.failure is not None):
            raise ValueError("hybrid fallback must carry its failure details")


async def rerank_with_fallback(
    profile: RetrievalProfile,
    query: str,
    candidates: Sequence[EvidenceHit],
    reranker: CrossEncoderReranker,
) -> RerankerStageOutcome:
    """Rerank the configured fused prefix and preserve its untouched hybrid tail.

    Any failure while scoring the selected prefix returns the complete original
    fused sequence, so the caller never receives a partial reranker result.
    """
    if not isinstance(profile, RetrievalProfile):
        raise ValueError("profile must be a RetrievalProfile")
    if profile.reranker is None:
        raise ValueError("profile must select a reranker")
    if not isinstance(reranker, CrossEncoderReranker):
        raise ValueError("reranker must be a CrossEncoderReranker")
    if isinstance(candidates, (str, bytes)) or not isinstance(candidates, Sequence):
        raise ValueError("candidates must be a sequence of EvidenceHit values")
    candidate_tuple = tuple(candidates)
    if any(not isinstance(hit, EvidenceHit) for hit in candidate_tuple):
        raise TypeError("candidates must contain EvidenceHit values")
    rerank_limit = profile.candidate_limits.rerank_top_k
    if rerank_limit is None:
        raise ValueError("profile must configure a rerank candidate limit")
    rerank_candidates = candidate_tuple[:rerank_limit]
    hybrid_tail = candidate_tuple[len(rerank_candidates) :]

    try:
        scores = await reranker.rerank(profile, query, rerank_candidates)
        reranked_prefix = apply_reranker_scores(
            profile, query, rerank_candidates, scores
        )
    except (RerankerAdapterError, RerankerPairBudgetExceeded) as error:
        failure = RerankerFailureDetails(
            profile_id=profile.profile_id,
            snapshot_id=profile.snapshot.snapshot_id,
            reranker=profile.reranker,
            error_type=type(error).__name__,
        )
        return RerankerStageOutcome(
            hits=candidate_tuple, effective_mode="hybrid", failure=failure
        )
    return RerankerStageOutcome(
        hits=(*reranked_prefix, *hybrid_tail), effective_mode="reranked"
    )
