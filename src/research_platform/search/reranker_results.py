"""Apply reranker scores without losing hybrid candidate provenance."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace

from research_platform.search.contracts import (
    ComponentScores,
    EvidenceHit,
    RankedComponent,
)
from research_platform.search.profiles import RetrievalProfile
from research_platform.search.reranker import RerankerScore, compute_query_sha256


class RerankerProvenanceError(ValueError):
    """Reranker output does not describe the exact supplied candidate pool."""


def apply_reranker_scores(
    profile: RetrievalProfile,
    query: str,
    candidates: Sequence[EvidenceHit],
    scored_candidates: Sequence[RerankerScore],
) -> tuple[EvidenceHit, ...]:
    """Apply reranked positions and scores while retaining prior ranks and scores.

    The scored records must cover the supplied candidate pool exactly. This boundary
    cannot add candidates, lose evidence, overwrite earlier component values or apply
    scores produced for a different reranker identity.
    """
    if not isinstance(profile, RetrievalProfile):
        raise ValueError("profile must be a RetrievalProfile")
    identity = profile.reranker
    if identity is None:
        raise RerankerProvenanceError("profile does not select a reranker")
    if (
        profile.lexical_index is None
        or profile.dense_index is None
        or profile.fusion is None
    ):
        raise RerankerProvenanceError(
            "reranker provenance requires a hybrid fusion profile"
        )
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must be non-empty")
    rerank_limit = profile.candidate_limits.rerank_top_k
    if rerank_limit is None:
        raise RerankerProvenanceError("profile has no rerank candidate limit")
    if isinstance(candidates, (str, bytes)) or not isinstance(candidates, Sequence):
        raise ValueError("candidates must be a sequence of EvidenceHit values")
    if isinstance(scored_candidates, (str, bytes)) or not isinstance(
        scored_candidates, Sequence
    ):
        raise ValueError("scored_candidates must be a sequence of RerankerScore values")
    candidate_tuple = tuple(candidates)
    score_tuple = tuple(scored_candidates)
    if len(candidate_tuple) > rerank_limit:
        raise RerankerProvenanceError("candidate pool exceeds its profile rerank limit")
    if len(candidate_tuple) != len(score_tuple):
        raise RerankerProvenanceError(
            "reranker output does not cover the candidate pool"
        )
    if any(not isinstance(hit, EvidenceHit) for hit in candidate_tuple):
        raise TypeError("candidates must contain EvidenceHit values")
    if any(not isinstance(score, RerankerScore) for score in score_tuple):
        raise TypeError("scored_candidates must contain RerankerScore values")

    by_chunk_id: dict[str, EvidenceHit] = {}
    original_ranks: set[int] = set()
    for hit in candidate_tuple:
        if hit.chunk_id in by_chunk_id:
            raise RerankerProvenanceError("candidate pool repeats a chunk ID")
        if hit.rank in original_ranks:
            raise RerankerProvenanceError("candidate pool repeats an original rank")
        if hit.component_scores.reranker is not None:
            raise RerankerProvenanceError("candidate was already reranked")
        if (
            hit.component_scores.fusion is None
            or hit.component_scores.fusion.rank != hit.rank
        ):
            raise RerankerProvenanceError(
                "candidate does not retain its original fused rank"
            )
        by_chunk_id[hit.chunk_id] = hit
        original_ranks.add(hit.rank)

    score_ids: set[str] = set()
    for expected_rank, score in enumerate(score_tuple, start=1):
        if score.reranker_identity != identity:
            raise RerankerProvenanceError(
                "reranker score identity differs from the selected profile"
            )
        if score.profile_id != profile.profile_id:
            raise RerankerProvenanceError(
                "reranker score profile differs from the selected profile"
            )
        if score.query_sha256 != compute_query_sha256(query):
            raise RerankerProvenanceError(
                "reranker score query identity differs from the supplied query"
            )
        if score.rank != expected_rank:
            raise RerankerProvenanceError("reranker result ranks must be sequential")
        candidate_hit = by_chunk_id.get(score.evidence_hit.chunk_id)
        if candidate_hit is None or score.evidence_hit != candidate_hit:
            raise RerankerProvenanceError(
                "reranker output contains evidence outside the supplied candidate pool"
            )
        if score.original_rank != candidate_hit.rank:
            raise RerankerProvenanceError(
                "reranker output does not retain the candidate's original rank"
            )
        if candidate_hit.chunk_id in score_ids:
            raise RerankerProvenanceError("reranker output repeats a chunk ID")
        score_ids.add(candidate_hit.chunk_id)

    if score_ids != set(by_chunk_id):
        raise RerankerProvenanceError(
            "reranker output does not cover the candidate pool"
        )
    expected_order = tuple(
        sorted(
            score_tuple,
            key=lambda score: (
                -score.score,
                score.original_rank,
                score.evidence_hit.chunk_id,
            ),
        )
    )
    if score_tuple != expected_order:
        raise RerankerProvenanceError(
            "reranker output is not in deterministic score order"
        )

    reranked: list[EvidenceHit] = []
    for score in score_tuple:
        prior_scores = score.evidence_hit.component_scores
        reranked.append(
            replace(
                score.evidence_hit,
                rank=score.rank,
                component_scores=ComponentScores(
                    lexical=prior_scores.lexical,
                    dense=prior_scores.dense,
                    fusion=prior_scores.fusion,
                    reranker=RankedComponent(rank=score.rank, score=score.score),
                ),
            )
        )
    return tuple(reranked)
