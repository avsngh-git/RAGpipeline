"""Profile and pool invariants for the hybrid evidence candidate service."""

import asyncio
from dataclasses import replace
from types import SimpleNamespace
from uuid import UUID

import pytest

from research_platform.ingestion.indexing import IndexInput, IndexMatch
from research_platform.ingestion.snapshot_selection import SnapshotSelection
from research_platform.search.contracts import SearchFilters
from research_platform.search.dense_search import (
    DenseSearchResponse,
    HydratedDenseHit,
)
from research_platform.search.hybrid_search import (
    HybridEvidenceSearch,
    HybridProfileMismatch,
)
from research_platform.search.lexical import (
    SCIENTIFIC_BM25_IDENTITY,
    LexicalHit,
    LexicalSearchResult,
)
from research_platform.search.profiles import (
    CandidateLimits,
    DenseIndexIdentity,
    FusionSettings,
    RetrievalProfile,
)

SNAPSHOT_ID = UUID("f1336240-dda0-45fb-a5b1-ff399bd93436")
SNAPSHOT_CONFIG_ID = "sha256:" + "a" * 64
CHUNK_SELECTION_ID = "sha256:" + "b" * 64
DENSE_CONFIG_ID = "sha256:" + "c" * 64


def _profile() -> RetrievalProfile:
    return RetrievalProfile(
        snapshot=SnapshotSelection(
            snapshot_id=SNAPSHOT_ID,
            snapshot_configuration_id=SNAPSHOT_CONFIG_ID,
            chunk_selection_id=CHUNK_SELECTION_ID,
        ),
        lexical_index=SCIENTIFIC_BM25_IDENTITY,
        dense_index=DenseIndexIdentity(
            model="test-model",
            revision="revision-a",
            preprocessing_revision="passage-query-v1",
            dimensions=2,
            maximum_input_tokens=64,
            index_configuration_id=DENSE_CONFIG_ID,
        ),
        fusion=FusionSettings(rank_constant=60),
        candidate_limits=CandidateLimits(
            lexical_top_k=2,
            dense_top_k=3,
            fused_top_k=2,
            rerank_top_k=None,
        ),
    )


def _lexical_hit(evidence_id: str, score: float, row: int) -> LexicalHit:
    return LexicalHit(evidence_id, "W123", row, score)


def _dense_hit(evidence_id: str, rank: int, score: float) -> HydratedDenseHit:
    evidence = IndexInput(
        evidence_id=evidence_id,
        text="evidence text",
        payload={
            "paper_id": "W123",
            "document_id": "document",
            "extraction_id": "extraction",
            "snapshot_id": str(SNAPSHOT_ID),
        },
    )
    return HydratedDenseHit(rank=rank, score=score, evidence=evidence)


class _LexicalBranch:
    def __init__(self, profile: RetrievalProfile, result: LexicalSearchResult) -> None:
        self.profile = profile
        self.manifest = SimpleNamespace(
            role="evidence",
            snapshot_status="finalized",
            profile_id=profile.profile_id,
            snapshot=profile.snapshot,
            candidate_limit=profile.candidate_limits.lexical_top_k,
        )
        self.result = result
        self.calls: list[tuple[str, int]] = []

    def search_with_stats(self, query: str, *, limit: int) -> LexicalSearchResult:
        self.calls.append((query, limit))
        return self.result


class _DenseBranch:
    def __init__(
        self, hits: tuple[HydratedDenseHit, ...], available_count: int
    ) -> None:
        self.hits = hits
        self.available_count = available_count
        self.calls: list[tuple[RetrievalProfile, str, int, SearchFilters, bool]] = []

    def _response(
        self,
        profile: RetrievalProfile,
        query: str,
        limit: int,
        filters: SearchFilters,
        evaluation: bool,
    ) -> DenseSearchResponse:
        self.calls.append((profile, query, limit, filters, evaluation))
        matches = tuple(
            IndexMatch(hit.evidence.evidence_id, hit.score, {}) for hit in self.hits
        )
        return DenseSearchResponse(
            snapshot_id=profile.snapshot.snapshot_id,
            profile_id=profile.profile_id,
            index_configuration_id=profile.dense_index.index_configuration_id,
            requested_limit=limit,
            hits=matches,
            hydrated_hits=self.hits,
            candidate_count=self.available_count,
            truncated=self.available_count > limit,
        )

    async def search_hybrid_component_query(
        self,
        profile: RetrievalProfile,
        query: str,
        *,
        limit: int,
        filters: SearchFilters = SearchFilters(),
    ) -> DenseSearchResponse:
        return self._response(profile, query, limit, filters, False)

    async def evaluate_hybrid_component_query(
        self,
        profile: RetrievalProfile,
        query: str,
        *,
        limit: int,
        filters: SearchFilters = SearchFilters(),
    ) -> DenseSearchResponse:
        return self._response(profile, query, limit, filters, True)


def _service(
    profile: RetrievalProfile,
) -> tuple[HybridEvidenceSearch, _LexicalBranch, _DenseBranch]:
    lexical_result = LexicalSearchResult(
        hits=(_lexical_hit("a", 9.0, 0), _lexical_hit("b", 8.0, 1)),
        available_count=5,
        limit=2,
        truncated=True,
    )
    lexical = _LexicalBranch(profile, lexical_result)
    dense = _DenseBranch(
        (_dense_hit("b", 1, 0.9), _dense_hit("c", 2, 0.8), _dense_hit("d", 3, 0.7)),
        available_count=5,
    )
    return HybridEvidenceSearch(lexical, dense), lexical, dense


def test_hybrid_search_caps_each_branch_and_fused_union_with_exact_stats() -> None:
    profile = _profile()
    service, lexical, dense = _service(profile)

    result = asyncio.run(service.search_query(profile, "query"))

    assert lexical.calls == [("query", 2)]
    assert dense.calls == [(profile, "query", 3, SearchFilters(), False)]
    assert [hit.evidence_id for hit in result.hits] == ["b", "a"]
    assert result.snapshot_id == SNAPSHOT_ID
    assert result.profile_id == profile.profile_id
    assert result.applied_filters == SearchFilters()
    assert result.lexical_pool.limit == 2
    assert result.lexical_pool.available_count == 5
    assert result.lexical_pool.returned_count == 2
    assert result.lexical_pool.truncated
    assert result.dense_pool.limit == 3
    assert result.dense_pool.available_count == 5
    assert result.dense_pool.returned_count == 3
    assert result.dense_pool.truncated
    assert result.fused_pool.limit == 2
    assert result.fused_pool.available_count == 4
    assert result.fused_pool.returned_count == 2
    assert result.fused_pool.truncated
    assert result.fused_pool.count_exact is False
    assert result.truncated


def test_hybrid_search_rejects_profile_mismatch_before_dense_call() -> None:
    profile = _profile()
    service, _lexical, dense = _service(profile)
    different_profile = replace(
        profile, fusion=replace(profile.fusion, rank_constant=30)
    )

    with pytest.raises(HybridProfileMismatch, match="lexical index profile"):
        asyncio.run(service.search_query(different_profile, "query"))

    assert not dense.calls


def test_hybrid_search_rejects_filters_until_both_branches_apply_them() -> None:
    profile = _profile()
    service, lexical, dense = _service(profile)

    with pytest.raises(ValueError, match="filters are not available yet"):
        asyncio.run(
            service.search_query(
                profile, "query", filters=SearchFilters(year_from=2020)
            )
        )

    assert not lexical.calls
    assert not dense.calls


def test_hybrid_evaluation_uses_the_explicit_evaluation_branch() -> None:
    profile = _profile()
    service, _lexical, dense = _service(profile)

    asyncio.run(service.evaluate_query(profile, "query"))

    assert dense.calls[0] == (profile, "query", 3, SearchFilters(), True)
