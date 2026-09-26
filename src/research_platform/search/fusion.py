"""Deterministic reciprocal-rank fusion for profile-bound evidence results."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from research_platform.search.contracts import ComponentScores, RankedComponent
from research_platform.search.dense_search import HydratedDenseHit
from research_platform.search.lexical import LexicalHit
from research_platform.search.profiles import FusionSettings


@dataclass(frozen=True)
class FusedEvidenceCandidate:
    """One evidence ID with its fused rank and original component provenance."""

    evidence_id: str
    rank: int
    score: float
    component_scores: ComponentScores

    def __post_init__(self) -> None:
        if not isinstance(self.evidence_id, str) or not self.evidence_id.strip():
            raise ValueError("evidence_id must be non-empty text")
        if (
            isinstance(self.rank, bool)
            or not isinstance(self.rank, int)
            or self.rank < 1
        ):
            raise ValueError("rank must be a positive integer")
        if (
            isinstance(self.score, bool)
            or not isinstance(self.score, (int, float))
            or not math.isfinite(self.score)
            or self.score <= 0
        ):
            raise ValueError("fusion score must be finite and positive")
        if not isinstance(self.component_scores, ComponentScores):
            raise ValueError("component_scores must be ComponentScores")


def reciprocal_rank_fusion(
    lexical_hits: Sequence[LexicalHit],
    dense_hits: Sequence[HydratedDenseHit],
    *,
    settings: FusionSettings,
) -> tuple[FusedEvidenceCandidate, ...]:
    """Fuse two ranked evidence lists using their 1-based component ranks.

    Scores are RRF ranking values, not probabilities. The configured method and
    positive rank constant are serialized into the retrieval profile identity.
    """
    if not isinstance(settings, FusionSettings):
        raise ValueError("settings must be FusionSettings")

    contributions: dict[str, list[float]] = {}
    lexical_components: dict[str, RankedComponent] = {}
    dense_components: dict[str, RankedComponent] = {}

    for rank, lexical_hit in enumerate(lexical_hits, start=1):
        if not isinstance(lexical_hit, LexicalHit):
            raise TypeError("lexical_hits must contain LexicalHit values")
        evidence_id = lexical_hit.stable_id
        if not isinstance(evidence_id, str) or not evidence_id.strip():
            raise ValueError("lexical evidence IDs must be non-empty")
        if evidence_id in lexical_components:
            raise ValueError("lexical results must not repeat evidence IDs")
        lexical_components[evidence_id] = RankedComponent(
            rank=rank, score=lexical_hit.score
        )
        contributions.setdefault(evidence_id, []).append(
            1.0 / (settings.rank_constant + rank)
        )

    for expected_rank, dense_hit in enumerate(dense_hits, start=1):
        if not isinstance(dense_hit, HydratedDenseHit):
            raise TypeError("dense_hits must contain HydratedDenseHit values")
        if dense_hit.rank != expected_rank:
            raise ValueError("dense results must have sequential 1-based ranks")
        evidence_id = dense_hit.evidence.evidence_id
        if evidence_id in dense_components:
            raise ValueError("dense results must not repeat evidence IDs")
        dense_components[evidence_id] = RankedComponent(
            rank=dense_hit.rank, score=dense_hit.score
        )
        contributions.setdefault(evidence_id, []).append(
            1.0 / (settings.rank_constant + dense_hit.rank)
        )

    scored = [
        (
            evidence_id,
            math.fsum(terms),
            lexical_components.get(evidence_id),
            dense_components.get(evidence_id),
        )
        for evidence_id, terms in contributions.items()
    ]
    scored.sort(key=lambda candidate: (-candidate[1], candidate[0]))

    return tuple(
        FusedEvidenceCandidate(
            evidence_id=evidence_id,
            rank=rank,
            score=score,
            component_scores=ComponentScores(
                lexical=lexical,
                dense=dense,
                fusion=RankedComponent(rank=rank, score=score),
            ),
        )
        for rank, (evidence_id, score, lexical, dense) in enumerate(scored, start=1)
    )
