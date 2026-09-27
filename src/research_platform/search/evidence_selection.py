"""Bound ranked evidence results by the number retained for each paper."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from research_platform.search.contracts import (
    DEFAULT_SEARCH_LIMITS,
    EvidenceHit,
)
from research_platform.search.profiles import SelectionRules

EvidenceSelectionOmissionReason = Literal["per_paper_limit"]


@dataclass(frozen=True)
class EvidenceSelectionOmission:
    """One hit omitted by the per-paper cap, with its source lineage retained."""

    chunk_id: str
    paper_id: str
    original_rank: int
    source_evidence_ids: tuple[str, ...]
    reason: EvidenceSelectionOmissionReason = "per_paper_limit"

    def __post_init__(self) -> None:
        if not isinstance(self.chunk_id, str) or not self.chunk_id.strip():
            raise ValueError("chunk_id must be non-empty")
        if not isinstance(self.paper_id, str) or not self.paper_id.strip():
            raise ValueError("paper_id must be non-empty")
        if (
            isinstance(self.original_rank, bool)
            or not isinstance(self.original_rank, int)
            or self.original_rank < 1
        ):
            raise ValueError("original_rank must be a positive integer")
        if (
            not isinstance(self.source_evidence_ids, tuple)
            or not self.source_evidence_ids
        ):
            raise ValueError("source_evidence_ids must be a non-empty tuple")
        if any(
            not isinstance(item, str) or not item.strip()
            for item in self.source_evidence_ids
        ):
            raise ValueError("source_evidence_ids must contain non-empty IDs")
        if self.reason != "per_paper_limit":
            raise ValueError("unsupported evidence selection omission reason")


@dataclass(frozen=True)
class PerPaperEvidenceSelection:
    """Selected hits plus source-linked cap omissions for one candidate sequence."""

    hits: tuple[EvidenceHit, ...]
    omissions: tuple[EvidenceSelectionOmission, ...]
    candidate_count: int
    per_paper_limit: int

    def __post_init__(self) -> None:
        if not isinstance(self.hits, tuple) or any(
            not isinstance(hit, EvidenceHit) for hit in self.hits
        ):
            raise ValueError("hits must contain EvidenceHit values")
        if not isinstance(self.omissions, tuple) or any(
            not isinstance(item, EvidenceSelectionOmission) for item in self.omissions
        ):
            raise ValueError("omissions must contain EvidenceSelectionOmission values")
        if (
            isinstance(self.candidate_count, bool)
            or not isinstance(self.candidate_count, int)
            or self.candidate_count < 0
        ):
            raise ValueError("candidate_count must be non-negative")
        if self.candidate_count != len(self.hits) + len(self.omissions):
            raise ValueError(
                "candidate_count must account for selected and omitted hits"
            )
        if (
            isinstance(self.per_paper_limit, bool)
            or not isinstance(self.per_paper_limit, int)
            or not 1
            <= self.per_paper_limit
            <= DEFAULT_SEARCH_LIMITS.max_per_paper_evidence_limit
        ):
            raise ValueError("per_paper_limit is outside the configured bounds")
        all_ids = tuple(hit.chunk_id for hit in self.hits) + tuple(
            item.chunk_id for item in self.omissions
        )
        if len(set(all_ids)) != len(all_ids):
            raise ValueError("selected and omitted chunk IDs must be unique")
        ranks = tuple(hit.rank for hit in self.hits) + tuple(
            item.original_rank for item in self.omissions
        )
        if len(set(ranks)) != len(ranks):
            raise ValueError("selected and omitted ranks must be unique")
        counts: dict[str, int] = {}
        for hit in self.hits:
            counts[hit.paper_id] = counts.get(hit.paper_id, 0) + 1
        if any(count > self.per_paper_limit for count in counts.values()):
            raise ValueError("selected hits exceed the per-paper limit")

    @property
    def omitted_count(self) -> int:
        """Number of observed candidates omitted by this per-paper cap."""
        return len(self.omissions)

    @property
    def truncated(self) -> bool:
        """Whether this selector omitted any candidate from its input sequence."""
        return bool(self.omissions)


def select_evidence_per_paper(
    candidates: Sequence[EvidenceHit],
    *,
    selection_rules: SelectionRules = SelectionRules(),
) -> PerPaperEvidenceSelection:
    """Keep each paper's highest-ranked hits up to its profile-bound evidence cap.

    Original ranks, scores, source identities and candidate order are preserved.
    Omission counts refer to the supplied candidate sequence; any upstream-pool
    truncation must be reported separately by the caller.
    """
    if isinstance(candidates, (str, bytes)) or not isinstance(candidates, Sequence):
        raise ValueError("candidates must be a sequence of EvidenceHit values")
    if not isinstance(selection_rules, SelectionRules):
        raise ValueError("selection_rules must be SelectionRules")
    limit = selection_rules.evidence_per_paper_limit
    if limit > DEFAULT_SEARCH_LIMITS.max_per_paper_evidence_limit:
        raise ValueError("evidence per-paper limit exceeds the configured maximum")

    hits = tuple(candidates)
    if any(not isinstance(hit, EvidenceHit) for hit in hits):
        raise TypeError("candidates must contain EvidenceHit values")
    chunk_ids = tuple(hit.chunk_id for hit in hits)
    if len(set(chunk_ids)) != len(chunk_ids):
        raise ValueError("candidates must not repeat chunk IDs")
    ranks = tuple(hit.rank for hit in hits)
    if len(set(ranks)) != len(ranks):
        raise ValueError("candidate ranks must be unique")

    selected_counts: dict[str, int] = {}
    selected: list[EvidenceHit] = []
    omissions: list[EvidenceSelectionOmission] = []
    for hit in sorted(hits, key=lambda item: (item.rank, item.chunk_id)):
        paper_count = selected_counts.get(hit.paper_id, 0)
        if paper_count < limit:
            selected.append(hit)
            selected_counts[hit.paper_id] = paper_count + 1
        else:
            omissions.append(
                EvidenceSelectionOmission(
                    chunk_id=hit.chunk_id,
                    paper_id=hit.paper_id,
                    original_rank=hit.rank,
                    source_evidence_ids=hit.source_evidence_ids,
                )
            )

    return PerPaperEvidenceSelection(
        hits=tuple(selected),
        omissions=tuple(omissions),
        candidate_count=len(hits),
        per_paper_limit=limit,
    )
