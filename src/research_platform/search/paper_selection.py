"""Bound paper-result selection and report candidate-pool truncation."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from research_platform.search.contracts import (
    DEFAULT_SEARCH_LIMITS,
    PaperHit,
)
from research_platform.search.profiles import RetrievalProfile


@dataclass(frozen=True)
class PaperResultSelection:
    """A bounded page and honest count of candidates omitted from that page."""

    hits: tuple[PaperHit, ...]
    candidate_count: int
    candidate_scan_limit: int
    truncated: bool
    omitted_count: int
    omitted_count_exact: bool
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.hits, tuple) or any(
            not isinstance(hit, PaperHit) for hit in self.hits
        ):
            raise ValueError("hits must contain PaperHit values")
        for name in ("candidate_count", "omitted_count"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if (
            isinstance(self.candidate_scan_limit, bool)
            or not isinstance(self.candidate_scan_limit, int)
            or self.candidate_scan_limit < 1
        ):
            raise ValueError("candidate_scan_limit must be a positive integer")
        if self.candidate_count > self.candidate_scan_limit:
            raise ValueError("candidate count exceeds its configured scan limit")
        if self.omitted_count != self.candidate_count - len(self.hits):
            raise ValueError("omitted_count must match observed unreturned candidates")
        if not isinstance(self.omitted_count_exact, bool):
            raise ValueError("omitted_count_exact must be a boolean")
        if not isinstance(self.truncated, bool) or self.truncated != (
            self.omitted_count > 0 or not self.omitted_count_exact
        ):
            raise ValueError("truncated must include omitted or unknown candidates")
        if not isinstance(self.warnings, tuple) or any(
            not isinstance(warning, str) or not warning.strip()
            for warning in self.warnings
        ):
            raise ValueError("warnings must contain non-empty strings")


def paper_candidate_scan_limit(profile: RetrievalProfile) -> int:
    """Derive the maximum metadata-plus-evidence union from profile stage caps."""
    if not isinstance(profile, RetrievalProfile):
        raise ValueError("profile must be a RetrievalProfile")

    limits = profile.candidate_limits
    metadata_limit = limits.lexical_top_k if profile.lexical_index is not None else 0
    if profile.reranker is not None:
        evidence_limit = limits.rerank_top_k
    elif profile.fusion is not None:
        evidence_limit = limits.fused_top_k
    elif profile.dense_index is not None:
        evidence_limit = limits.dense_top_k
    elif profile.lexical_index is not None:
        evidence_limit = limits.lexical_top_k
    else:
        evidence_limit = 0

    if metadata_limit is None:
        metadata_limit = 0
    if evidence_limit is None:
        evidence_limit = 0
    scan_limit = metadata_limit + evidence_limit
    if scan_limit < 1:
        raise ValueError("profile must configure a bounded paper candidate stage")
    return scan_limit


def select_paper_results(
    candidates: Sequence[PaperHit],
    *,
    limit: int,
    profile: RetrievalProfile,
    candidate_pools_truncated: bool,
) -> PaperResultSelection:
    """Return one result per paper and account for both page and pool omissions.

    `candidates` must already be ordered by the profile's paper ranking rule. The
    profile's branch candidate limits define a strict upper bound on the union. A
    truncated input pool makes the omitted count a lower bound, even when the
    observed candidate list fits on the requested page.
    """
    if (
        isinstance(limit, bool)
        or not isinstance(limit, int)
        or not 1 <= limit <= DEFAULT_SEARCH_LIMITS.max_result_limit
    ):
        raise ValueError("limit is outside the configured paper result bounds")
    if not isinstance(candidate_pools_truncated, bool):
        raise ValueError("candidate_pools_truncated must be a boolean")
    scan_limit = paper_candidate_scan_limit(profile)
    if len(candidates) > scan_limit:
        raise ValueError("paper candidate union exceeds the profile-derived scan cap")

    paper_ids: set[str] = set()
    for expected_rank, hit in enumerate(candidates, start=1):
        if not isinstance(hit, PaperHit):
            raise TypeError("candidates must contain PaperHit values")
        if hit.paper_id in paper_ids:
            raise ValueError("paper candidates must contain one record per paper")
        if hit.rank != expected_rank:
            raise ValueError("paper candidates must have sequential fused ranks")
        paper_ids.add(hit.paper_id)

    selected = tuple(candidates[:limit])
    omitted_count = len(candidates) - len(selected)
    omitted_count_exact = not candidate_pools_truncated
    truncated = omitted_count > 0 or candidate_pools_truncated
    warnings: list[str] = []
    if omitted_count > 0:
        warnings.append("paper result limit omitted lower-ranked candidates")
    if candidate_pools_truncated:
        warnings.append(
            "candidate pools were truncated; omitted_count covers only observed candidates"
        )
    return PaperResultSelection(
        hits=selected,
        candidate_count=len(candidates),
        candidate_scan_limit=scan_limit,
        truncated=truncated,
        omitted_count=omitted_count,
        omitted_count_exact=omitted_count_exact,
        warnings=tuple(warnings),
    )
