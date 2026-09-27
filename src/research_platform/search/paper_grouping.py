"""Group ranked evidence into paper results without length-based score gains."""

from __future__ import annotations

from collections.abc import Sequence

from research_platform.search.contracts import (
    DEFAULT_SEARCH_LIMITS,
    EvidenceHit,
    PaperHit,
)
from research_platform.search.profiles import SelectionRules


def group_evidence_by_paper(
    evidence_hits: Sequence[EvidenceHit],
    *,
    selection_rules: SelectionRules = SelectionRules(),
) -> tuple[PaperHit, ...]:
    """Build paper candidates from ranked evidence, using only each best hit's score.

    Each input hit is expected to have passed the requested evidence filters. Paper
    order follows the strongest hit's rank, with public paper ID as the stable tie
    break. Supporting passages retain their evidence ranks and component scores.
    Scores from multiple chunks are never summed or averaged.
    """
    if not isinstance(selection_rules, SelectionRules):
        raise ValueError("selection_rules must be SelectionRules")
    if (
        selection_rules.paper_support_limit
        > DEFAULT_SEARCH_LIMITS.max_per_paper_evidence_limit
    ):
        raise ValueError("paper support limit exceeds the configured maximum")

    hits = tuple(evidence_hits)
    if any(not isinstance(hit, EvidenceHit) for hit in hits):
        raise TypeError("evidence_hits must contain EvidenceHit values")
    chunk_ids = tuple(hit.chunk_id for hit in hits)
    if len(set(chunk_ids)) != len(chunk_ids):
        raise ValueError("evidence hits must not repeat chunk IDs")

    ordered_hits = sorted(hits, key=lambda hit: (hit.rank, hit.chunk_id))
    grouped: dict[str, list[EvidenceHit]] = {}
    for hit in ordered_hits:
        grouped.setdefault(hit.paper_id, []).append(hit)

    ordered_papers = sorted(
        grouped.items(),
        key=lambda item: (item[1][0].rank, item[0], item[1][0].chunk_id),
    )
    return tuple(
        PaperHit(
            paper_id=paper_id,
            title=None,
            publication_year=None,
            rank=rank,
            component_scores=paper_hits[0].component_scores,
            supporting_evidence=tuple(
                paper_hits[: selection_rules.paper_support_limit]
            ),
            evidence_rank=rank,
        )
        for rank, (paper_id, paper_hits) in enumerate(ordered_papers, start=1)
    )
