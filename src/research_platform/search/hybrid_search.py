"""Profile-bound orchestration of lexical and dense evidence candidates."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from research_platform.search.contracts import (
    DEFAULT_SEARCH_LIMITS,
    SearchFilters,
    SearchOperation,
)
from research_platform.search.dense_search import DenseSearchResponse
from research_platform.search.fusion import (
    FusedEvidenceCandidate,
    reciprocal_rank_fusion,
)
from research_platform.search.lexical import LexicalIndexManifest, LexicalSearchResult
from research_platform.search.profiles import RetrievalProfile


class HybridProfileMismatch(RuntimeError):
    """A branch or artifact does not match the requested hybrid profile."""


class UnsupportedHybridProfile(ValueError):
    """The requested profile contains stages this candidate service cannot run."""


@dataclass(frozen=True)
class CandidatePoolStats:
    """Configured bound and observed size of one ranked candidate pool."""

    limit: int
    available_count: int
    returned_count: int
    truncated: bool
    count_exact: bool = True

    def __post_init__(self) -> None:
        for name in ("limit", "available_count", "returned_count"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if self.limit == 0:
            raise ValueError("limit must be positive")
        if self.returned_count > self.limit:
            raise ValueError("returned candidates exceed the configured limit")
        if self.available_count < self.returned_count:
            raise ValueError("available_count cannot be smaller than returned_count")
        if self.count_exact and self.truncated != (self.available_count > self.limit):
            raise ValueError("truncated must match the exact available count and limit")
        if (
            not self.count_exact
            and self.available_count > self.limit
            and not self.truncated
        ):
            raise ValueError("a lower-bound count above the limit must be truncated")


@dataclass(frozen=True)
class HybridEvidenceSearchResponse:
    """Bounded fused candidates with exact per-stage pool statistics."""

    snapshot_id: UUID
    profile_id: str
    applied_filters: SearchFilters
    lexical_pool: CandidatePoolStats
    dense_pool: CandidatePoolStats
    fused_pool: CandidatePoolStats
    hits: tuple[FusedEvidenceCandidate, ...]

    @property
    def truncated(self) -> bool:
        """Whether any candidate stage omitted results at its configured bound."""
        return any(
            pool.truncated
            for pool in (self.lexical_pool, self.dense_pool, self.fused_pool)
        )


class LexicalEvidenceBranch(Protocol):
    @property
    def profile(self) -> RetrievalProfile: ...

    @property
    def manifest(self) -> LexicalIndexManifest: ...

    def search_with_stats(
        self,
        query: str,
        *,
        limit: int,
        filters: SearchFilters = SearchFilters(),
    ) -> LexicalSearchResult: ...


class DenseEvidenceBranch(Protocol):
    async def search_hybrid_component_query(
        self,
        profile: RetrievalProfile,
        query: str,
        *,
        limit: int,
        filters: SearchFilters = SearchFilters(),
    ) -> DenseSearchResponse: ...

    async def evaluate_hybrid_component_query(
        self,
        profile: RetrievalProfile,
        query: str,
        *,
        limit: int,
        filters: SearchFilters = SearchFilters(),
    ) -> DenseSearchResponse: ...


class HybridEvidenceSearch:
    """Run both bounded branches against one exact profile and fuse their hits."""

    def __init__(
        self,
        lexical: LexicalEvidenceBranch,
        dense: DenseEvidenceBranch,
    ) -> None:
        self._lexical = lexical
        self._dense = dense

    async def search_query(
        self,
        profile: RetrievalProfile,
        query: str,
        *,
        filters: SearchFilters = SearchFilters(),
    ) -> HybridEvidenceSearchResponse:
        """Serve a finalized snapshot through both branches and the fused cap."""
        return await self._search_query(
            profile, query, filters=filters, evaluation=False
        )

    async def evaluate_query(
        self,
        profile: RetrievalProfile,
        query: str,
        *,
        filters: SearchFilters = SearchFilters(),
    ) -> HybridEvidenceSearchResponse:
        """Evaluate one named snapshot, including a permitted draft snapshot."""
        return await self._search_query(
            profile, query, filters=filters, evaluation=True
        )

    async def _search_query(
        self,
        profile: RetrievalProfile,
        query: str,
        *,
        filters: SearchFilters,
        evaluation: bool,
    ) -> HybridEvidenceSearchResponse:
        if not isinstance(profile, RetrievalProfile):
            raise ValueError("profile must be a RetrievalProfile")
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query text must be non-empty")
        if len(query) > DEFAULT_SEARCH_LIMITS.max_query_characters:
            raise ValueError("query text exceeds the configured character limit")
        if not isinstance(filters, SearchFilters):
            raise ValueError("filters must be SearchFilters")
        filters.validate_for(SearchOperation.EVIDENCE_SEARCH)

        if (
            profile.lexical_index is None
            or profile.dense_index is None
            or profile.fusion is None
        ):
            raise UnsupportedHybridProfile(
                "hybrid search requires lexical, dense, and fusion profile stages"
            )
        if profile.reranker is not None:
            raise UnsupportedHybridProfile(
                "hybrid candidate search does not execute reranker profiles"
            )
        if profile != self._lexical.profile:
            raise HybridProfileMismatch(
                "lexical index profile differs from the requested retrieval profile"
            )
        manifest = self._lexical.manifest
        if (
            manifest.role != "evidence"
            or manifest.profile_id != profile.profile_id
            or manifest.snapshot != profile.snapshot
        ):
            raise HybridProfileMismatch(
                "lexical artifact does not match the requested evidence profile"
            )
        if not evaluation and manifest.snapshot_status != "finalized":
            raise PermissionError("serving search requires a finalized lexical index")

        lexical_limit = profile.candidate_limits.lexical_top_k
        dense_limit = profile.candidate_limits.dense_top_k
        fused_limit = profile.candidate_limits.fused_top_k
        if lexical_limit is None or dense_limit is None or fused_limit is None:
            raise UnsupportedHybridProfile(
                "hybrid profiles must configure all three candidate limits"
            )
        if manifest.candidate_limit != lexical_limit:
            raise HybridProfileMismatch(
                "lexical artifact candidate limit differs from the profile"
            )
        lexical_result = self._lexical.search_with_stats(
            query, limit=lexical_limit, filters=filters
        )
        if lexical_result.applied_filters != filters:
            raise HybridProfileMismatch(
                "lexical branch did not apply requested filters"
            )
        if lexical_result.limit != lexical_limit:
            raise HybridProfileMismatch(
                "lexical results do not report the requested candidate limit"
            )
        if len(lexical_result.hits) != min(
            lexical_result.available_count, lexical_limit
        ):
            raise HybridProfileMismatch(
                "lexical returned count differs from its exact pool stats"
            )
        dense_method = (
            self._dense.evaluate_hybrid_component_query
            if evaluation
            else self._dense.search_hybrid_component_query
        )
        dense_result = await dense_method(
            profile, query, limit=dense_limit, filters=filters
        )
        _validate_dense_branch_response(
            dense_result,
            profile=profile,
            limit=dense_limit,
            filters=filters,
        )
        fused = reciprocal_rank_fusion(
            lexical_result.hits,
            dense_result.hydrated_hits,
            settings=profile.fusion,
        )
        returned = fused[:fused_limit]
        return HybridEvidenceSearchResponse(
            snapshot_id=profile.snapshot.snapshot_id,
            profile_id=profile.profile_id,
            applied_filters=filters,
            lexical_pool=CandidatePoolStats(
                limit=lexical_limit,
                available_count=lexical_result.available_count,
                returned_count=len(lexical_result.hits),
                truncated=lexical_result.truncated,
            ),
            dense_pool=CandidatePoolStats(
                limit=dense_limit,
                available_count=dense_result.candidate_count,
                returned_count=len(dense_result.hydrated_hits),
                truncated=dense_result.truncated,
            ),
            fused_pool=CandidatePoolStats(
                limit=fused_limit,
                available_count=len(fused),
                returned_count=len(returned),
                truncated=len(fused) > fused_limit,
                count_exact=not (lexical_result.truncated or dense_result.truncated),
            ),
            hits=returned,
        )


def _validate_dense_branch_response(
    response: DenseSearchResponse,
    *,
    profile: RetrievalProfile,
    limit: int,
    filters: SearchFilters,
) -> None:
    dense_identity = profile.dense_index
    if (
        dense_identity is None
        or response.snapshot_id != profile.snapshot.snapshot_id
        or response.profile_id != profile.profile_id
        or response.index_configuration_id != dense_identity.index_configuration_id
        or response.requested_limit != limit
        or response.applied_filters != filters
    ):
        raise HybridProfileMismatch(
            "dense results differ from the requested profile or candidate limit"
        )
    if len(response.hits) != len(response.hydrated_hits):
        raise HybridProfileMismatch("dense results were not fully source-hydrated")
    if tuple(hit.evidence_id for hit in response.hits) != tuple(
        hit.evidence.evidence_id for hit in response.hydrated_hits
    ):
        raise HybridProfileMismatch("dense matches and hydrated evidence do not align")
    if len(response.hits) != min(response.candidate_count, limit):
        raise HybridProfileMismatch(
            "dense returned count differs from its exact pool stats"
        )
    if response.truncated != (response.candidate_count > limit):
        raise HybridProfileMismatch("dense truncation metadata is inconsistent")
