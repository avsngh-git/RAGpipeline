"""Combine metadata and evidence paper rankings with reciprocal-rank fusion."""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import TypeVar

from research_platform.search.contracts import (
    ComponentScores,
    PaperHit,
    PaperMetadataHit,
    RankedComponent,
)
from research_platform.search.profiles import FusionSettings

_ValueT = TypeVar("_ValueT")


def fuse_paper_candidates(
    metadata_hits: Sequence[PaperMetadataHit],
    evidence_hits: Sequence[PaperHit],
    *,
    settings: FusionSettings,
) -> tuple[PaperHit, ...]:
    """Fuse two paper rankings without adding their incomparable raw scores.

    Each branch contributes ``1 / (rank_constant + rank)`` once per paper. The
    metadata and evidence ranks remain on each result, and the evidence branch's
    supporting passages retain their own component scores. Stable paper IDs break
    equal fused-score ties.
    """
    if not isinstance(settings, FusionSettings):
        raise ValueError("settings must be FusionSettings")

    metadata_by_paper: dict[str, PaperMetadataHit] = {}
    for hit in metadata_hits:
        if not isinstance(hit, PaperMetadataHit):
            raise TypeError("metadata_hits must contain PaperMetadataHit values")
        if hit.paper_id in metadata_by_paper:
            raise ValueError("metadata ranking must not repeat paper IDs")
        metadata_by_paper[hit.paper_id] = hit

    evidence_by_paper: dict[str, PaperHit] = {}
    for evidence_candidate in evidence_hits:
        if not isinstance(evidence_candidate, PaperHit):
            raise TypeError("evidence_hits must contain PaperHit values")
        if evidence_candidate.paper_id in evidence_by_paper:
            raise ValueError("evidence ranking must not repeat paper IDs")
        if evidence_candidate.metadata_rank is not None:
            raise ValueError("evidence candidates must not already be fused")
        if (
            evidence_candidate.evidence_rank is not None
            and evidence_candidate.evidence_rank != evidence_candidate.rank
        ):
            raise ValueError("evidence candidate rank is inconsistent")
        if not evidence_candidate.supporting_evidence:
            raise ValueError("evidence candidates must retain supporting evidence")
        evidence_by_paper[evidence_candidate.paper_id] = evidence_candidate

    _validate_unique_ranks(tuple(metadata_by_paper.values()), "metadata")
    _validate_unique_ranks(tuple(evidence_by_paper.values()), "evidence")

    contributions: dict[str, list[float]] = {}
    for paper_id, hit in metadata_by_paper.items():
        contributions.setdefault(paper_id, []).append(
            1.0 / (settings.rank_constant + hit.rank)
        )
    for paper_id, evidence_candidate in evidence_by_paper.items():
        contributions.setdefault(paper_id, []).append(
            1.0 / (settings.rank_constant + evidence_candidate.rank)
        )

    scored = [(paper_id, math.fsum(terms)) for paper_id, terms in contributions.items()]
    scored.sort(key=lambda candidate: (-candidate[1], candidate[0]))

    fused_hits: list[PaperHit] = []
    for rank, (paper_id, score) in enumerate(scored, start=1):
        metadata_hit = metadata_by_paper.get(paper_id)
        evidence_hit = evidence_by_paper.get(paper_id)
        evidence_components = (
            evidence_hit.component_scores
            if evidence_hit is not None
            else ComponentScores()
        )
        lexical_component = (
            metadata_hit.component_scores.lexical
            if metadata_hit is not None
            else evidence_components.lexical
        )
        fused_hits.append(
            PaperHit(
                paper_id=paper_id,
                title=_first_value(
                    metadata_hit.title if metadata_hit is not None else None,
                    evidence_hit.title if evidence_hit is not None else None,
                ),
                publication_year=_first_value(
                    metadata_hit.publication_year if metadata_hit is not None else None,
                    evidence_hit.publication_year if evidence_hit is not None else None,
                ),
                rank=rank,
                component_scores=ComponentScores(
                    lexical=lexical_component,
                    dense=evidence_components.dense,
                    fusion=RankedComponent(rank=rank, score=score),
                    reranker=evidence_components.reranker,
                ),
                supporting_evidence=(
                    evidence_hit.supporting_evidence if evidence_hit is not None else ()
                ),
                metadata_rank=(metadata_hit.rank if metadata_hit is not None else None),
                evidence_rank=(evidence_hit.rank if evidence_hit is not None else None),
            )
        )
    return tuple(fused_hits)


def _validate_unique_ranks(
    hits: Sequence[PaperMetadataHit | PaperHit], branch: str
) -> None:
    ranks = tuple(hit.rank for hit in hits)
    if len(set(ranks)) != len(ranks):
        raise ValueError(f"{branch} ranking must not repeat ranks")


def _first_value(first: _ValueT | None, second: _ValueT | None) -> _ValueT | None:
    return first if first is not None else second
