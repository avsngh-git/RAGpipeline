"""Profile-bound dense search over one validated snapshot index."""

from __future__ import annotations

import math
from collections.abc import Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Protocol, cast
from uuid import UUID

from research_platform.ingestion.embeddings import (
    validate_supported_embedding_configuration,
)
from research_platform.ingestion.evidence import EvidenceKind
from research_platform.ingestion.identity import DocumentVersionKind
from research_platform.ingestion.indexing import (
    DENSE_FILTER_PAYLOAD_REVISION,
    IndexConfiguration,
    IndexInput,
    IndexMatch,
    QdrantIndex,
    ReadySnapshotIndex,
    SnapshotIndexMismatch,
)
from research_platform.ingestion.snapshot_selection import SnapshotSelection
from research_platform.search.contracts import (
    DEFAULT_SEARCH_LIMITS,
    SearchFilters,
    SearchOperation,
    matches_filters,
)
from research_platform.search.profiles import RetrievalProfile


class DenseQueryEmbedder(Protocol):
    """Pinned-model query adapter used by profile-bound dense search."""

    async def embed_query(
        self, text: str, *, configuration: IndexConfiguration
    ) -> Sequence[float]: ...


class SnapshotEvidenceHydrator(Protocol):
    """Resolve Qdrant identities to currently selected, permitted source inputs."""

    async def hydrate_snapshot_matches(
        self,
        snapshot_selection: SnapshotSelection,
        configuration: IndexConfiguration,
        matches: Sequence[IndexMatch],
        *,
        allow_draft: bool = False,
    ) -> tuple[IndexInput, ...]: ...


class SnapshotIndexGate(Protocol):
    """Readiness/permission seam held for the duration of one dense query."""

    def serving_index(
        self,
        snapshot_selection: SnapshotSelection,
        configuration: IndexConfiguration,
    ) -> AbstractAsyncContextManager[ReadySnapshotIndex]: ...

    def evaluation_index(
        self,
        snapshot_selection: SnapshotSelection,
        configuration: IndexConfiguration,
    ) -> AbstractAsyncContextManager[ReadySnapshotIndex]: ...


@dataclass(frozen=True)
class HydratedDenseHit:
    """A ranked vector match paired with its authoritative selected source row."""

    rank: int
    score: float
    evidence: IndexInput


@dataclass(frozen=True)
class DenseSearchResponse:
    """Dense matches and exact unfiltered counts, if available for this query."""

    snapshot_id: UUID
    profile_id: str
    index_configuration_id: str
    requested_limit: int
    hits: tuple[IndexMatch, ...]
    hydrated_hits: tuple[HydratedDenseHit, ...] = ()
    candidate_count: int | None = None
    truncated: bool | None = None


class UnsupportedRetrievalProfile(ValueError):
    """The selected profile requires a retrieval stage this service does not own."""


class ProfileDenseIndexMismatch(SnapshotIndexMismatch):
    """Dense model and vector-index fields disagree with the executable adapter."""


class SnapshotDenseSearch:
    """Execute dense-only searches or one branch of an explicit hybrid profile."""

    def __init__(
        self,
        gate: SnapshotIndexGate,
        index: QdrantIndex,
        *,
        query_embedder: DenseQueryEmbedder | None = None,
        evidence_hydrator: SnapshotEvidenceHydrator | None = None,
    ) -> None:
        self._gate = gate
        self._index = index
        self._query_embedder = query_embedder
        self._evidence_hydrator = evidence_hydrator

    async def search(
        self,
        profile: RetrievalProfile,
        vector: Sequence[float],
        *,
        limit: int,
        filters: SearchFilters = SearchFilters(),
    ) -> DenseSearchResponse:
        """Serve only a finalized snapshot through its exact ready profile."""
        return await self._search(
            profile,
            vector,
            limit=limit,
            filters=filters,
            evaluation=False,
            hydrate=False,
            hybrid_component=False,
        )

    async def search_query(
        self,
        profile: RetrievalProfile,
        query: str,
        *,
        limit: int,
        filters: SearchFilters = SearchFilters(),
    ) -> DenseSearchResponse:
        """Embed a pinned-model query, retrieve candidates and hydrate source rows."""
        return await self._search_query(
            profile,
            query,
            limit=limit,
            filters=filters,
            evaluation=False,
            hybrid_component=False,
        )

    async def evaluate_query(
        self,
        profile: RetrievalProfile,
        query: str,
        *,
        limit: int,
        filters: SearchFilters = SearchFilters(),
    ) -> DenseSearchResponse:
        """Run a named evaluation query, including explicit draft snapshots."""
        return await self._search_query(
            profile,
            query,
            limit=limit,
            filters=filters,
            evaluation=True,
            hybrid_component=False,
        )

    async def search_hybrid_component_query(
        self,
        profile: RetrievalProfile,
        query: str,
        *,
        limit: int,
        filters: SearchFilters = SearchFilters(),
    ) -> DenseSearchResponse:
        """Run the dense branch of a profile that also requires lexical fusion."""
        return await self._search_query(
            profile,
            query,
            limit=limit,
            filters=filters,
            evaluation=False,
            hybrid_component=True,
        )

    async def evaluate_hybrid_component_query(
        self,
        profile: RetrievalProfile,
        query: str,
        *,
        limit: int,
        filters: SearchFilters = SearchFilters(),
    ) -> DenseSearchResponse:
        """Run the dense branch for a named hybrid evaluation profile."""
        return await self._search_query(
            profile,
            query,
            limit=limit,
            filters=filters,
            evaluation=True,
            hybrid_component=True,
        )

    async def _search_query(
        self,
        profile: RetrievalProfile,
        query: str,
        *,
        limit: int,
        filters: SearchFilters,
        evaluation: bool,
        hybrid_component: bool,
    ) -> DenseSearchResponse:
        if self._query_embedder is None or self._evidence_hydrator is None:
            raise RuntimeError(
                "query search requires a pinned embedder and authoritative evidence hydrator"
            )
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query text must be non-empty")
        if len(query) > DEFAULT_SEARCH_LIMITS.max_query_characters:
            raise ValueError("query text exceeds the configured character limit")
        configuration = self._index.configuration
        _validate_search_request(
            profile, configuration, limit, hybrid_component=hybrid_component
        )
        filters.validate_for(SearchOperation.EVIDENCE_SEARCH)
        try:
            validate_supported_embedding_configuration(configuration)
        except ValueError as error:
            raise ProfileDenseIndexMismatch(str(error)) from None
        vector = await self._query_embedder.embed_query(
            query, configuration=configuration
        )
        _validate_normalized_query_vector(vector, configuration.vector_size)
        return await self._search(
            profile,
            vector,
            limit=limit,
            filters=filters,
            evaluation=evaluation,
            hydrate=True,
            hybrid_component=hybrid_component,
        )

    async def evaluate(
        self,
        profile: RetrievalProfile,
        vector: Sequence[float],
        *,
        limit: int,
        filters: SearchFilters = SearchFilters(),
    ) -> DenseSearchResponse:
        """Use the separate evaluation path, which may name a draft snapshot."""
        return await self._search(
            profile,
            vector,
            limit=limit,
            filters=filters,
            evaluation=True,
            hydrate=False,
            hybrid_component=False,
        )

    async def _search(
        self,
        profile: RetrievalProfile,
        vector: Sequence[float],
        *,
        limit: int,
        filters: SearchFilters,
        evaluation: bool,
        hydrate: bool,
        hybrid_component: bool,
    ) -> DenseSearchResponse:
        configuration = self._index.configuration
        _validate_search_request(
            profile, configuration, limit, hybrid_component=hybrid_component
        )
        filters.validate_for(SearchOperation.EVIDENCE_SEARCH)
        if _has_active_filters(filters) and self._evidence_hydrator is None:
            raise RuntimeError("filtered dense search requires authoritative hydration")

        lease_factory = (
            self._gate.evaluation_index if evaluation else self._gate.serving_index
        )
        async with lease_factory(profile.snapshot, configuration) as ready:
            if (
                ready.snapshot_selection != profile.snapshot
                or ready.configuration_id != configuration.configuration_id
                or (not evaluation and ready.snapshot_status != "finalized")
            ):
                raise SnapshotIndexMismatch(
                    "resolved index does not match the requested retrieval profile"
                )
            if _has_active_filters(filters) and (
                ready.filter_payload_revision != DENSE_FILTER_PAYLOAD_REVISION
            ):
                raise SnapshotIndexMismatch(
                    "dense index filter metadata is stale; rebuild the index before filtering"
                )
            hits = await self._index.query_snapshot(
                vector,
                profile.snapshot.snapshot_id,
                limit=limit,
                payload_conditions=_qdrant_payload_conditions(filters),
            )
            for hit in hits:
                if (
                    hit.payload.get("snapshot_id") != str(profile.snapshot.snapshot_id)
                    or hit.payload.get("index_configuration_id")
                    != configuration.configuration_id
                ):
                    raise SnapshotIndexMismatch(
                        "vector result payload does not match the resolved profile"
                    )
            hydrated_hits: tuple[HydratedDenseHit, ...] = ()
            candidate_count = (
                None if _has_active_filters(filters) else ready.expected_count
            )
            truncated = None if candidate_count is None else candidate_count > limit
            if hydrate or _has_active_filters(filters):
                assert self._evidence_hydrator is not None
                hydrated_inputs = (
                    await self._evidence_hydrator.hydrate_snapshot_matches(
                        profile.snapshot,
                        configuration,
                        hits,
                        allow_draft=evaluation,
                    )
                )
                if tuple(item.evidence_id for item in hydrated_inputs) != tuple(
                    hit.evidence_id for hit in hits
                ):
                    raise SnapshotIndexMismatch(
                        "authoritative evidence rows do not align with vector results"
                    )
                _validate_hydrated_filter_eligibility(hydrated_inputs, filters)
                hydrated_hits = tuple(
                    HydratedDenseHit(rank=rank, score=hit.score, evidence=evidence)
                    for rank, (hit, evidence) in enumerate(
                        zip(hits, hydrated_inputs, strict=True), start=1
                    )
                )
        return DenseSearchResponse(
            snapshot_id=profile.snapshot.snapshot_id,
            profile_id=profile.profile_id,
            index_configuration_id=configuration.configuration_id,
            requested_limit=limit,
            hits=hits,
            hydrated_hits=hydrated_hits,
            candidate_count=candidate_count,
            truncated=truncated,
        )


def _validate_normalized_query_vector(vector: Sequence[float], dimension: int) -> None:
    if len(vector) != dimension:
        raise ValueError(f"query vector must contain exactly {dimension} values")
    values: list[float] = []
    for value in vector:
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
        ):
            raise ValueError("query vector values must be finite numbers")
        values.append(float(value))
    norm = math.sqrt(math.fsum(value * value for value in values))
    if not math.isfinite(norm) or abs(norm - 1.0) > 1e-3:
        raise ValueError("query vector must be L2-normalized")


def _validate_search_request(
    profile: RetrievalProfile,
    configuration: IndexConfiguration,
    limit: int,
    *,
    hybrid_component: bool = False,
) -> None:
    if not isinstance(profile, RetrievalProfile):
        raise ValueError("profile must be a RetrievalProfile")
    if profile.reranker is not None:
        raise UnsupportedRetrievalProfile(
            "dense search cannot execute a profile requiring reranking"
        )
    if hybrid_component:
        if profile.lexical_index is None or profile.fusion is None:
            raise UnsupportedRetrievalProfile(
                "hybrid dense component requires lexical and fusion profile stages"
            )
    elif profile.lexical_index is not None or profile.fusion is not None:
        raise UnsupportedRetrievalProfile(
            "dense-only search cannot execute a profile requiring lexical or fusion stages"
        )
    dense_identity = profile.dense_index
    if dense_identity is None:
        raise UnsupportedRetrievalProfile(
            "dense search requires a dense index identity"
        )
    configured_limit = profile.candidate_limits.dense_top_k
    if (
        isinstance(limit, bool)
        or not isinstance(limit, int)
        or limit <= 0
        or limit > DEFAULT_SEARCH_LIMITS.max_candidate_limit
    ):
        raise ValueError("limit is outside the supported candidate bounds")
    if configured_limit is None or limit > configured_limit:
        raise ValueError("limit exceeds the profile's dense candidate limit")
    if (
        dense_identity.model != configuration.embedding_model
        or dense_identity.revision != configuration.embedding_revision
        or dense_identity.preprocessing_revision != configuration.preprocessing_revision
        or dense_identity.dimensions != configuration.vector_size
        or dense_identity.maximum_input_tokens != configuration.maximum_input_tokens
        or dense_identity.index_configuration_id != configuration.configuration_id
    ):
        raise ProfileDenseIndexMismatch(
            "retrieval profile does not match the configured dense index"
        )


def _has_active_filters(filters: SearchFilters) -> bool:
    return any(
        value is not None
        for value in (
            filters.year_from,
            filters.year_to,
            filters.paper_ids,
            filters.evidence_kinds,
            filters.document_version_kinds,
        )
    )


def _qdrant_payload_conditions(
    filters: SearchFilters,
) -> tuple[dict[str, object], ...]:
    if not _has_active_filters(filters):
        return ()
    conditions: list[dict[str, object]] = [
        {
            "key": "filter_payload_revision",
            "match": {"value": DENSE_FILTER_PAYLOAD_REVISION},
        }
    ]
    if filters.year_from is not None or filters.year_to is not None:
        year_range: dict[str, object] = {}
        if filters.year_from is not None:
            year_range["gte"] = filters.year_from
        if filters.year_to is not None:
            year_range["lte"] = filters.year_to
        conditions.append({"key": "publication_year", "range": year_range})
    for key, values in (
        ("paper_id", filters.paper_ids),
        ("evidence_kind", filters.evidence_kinds),
        ("document_version_kind", filters.document_version_kinds),
    ):
        if values is not None:
            conditions.append({"key": key, "match": {"any": list(values)}})
    return tuple(conditions)


def _validate_hydrated_filter_eligibility(
    evidence: Sequence[IndexInput], filters: SearchFilters
) -> None:
    if not _has_active_filters(filters):
        return
    valid_evidence_kinds = {
        "text",
        "table",
        "table_row_group",
        "caption",
        "figure",
        "equation",
    }
    valid_version_kinds = {"published", "preprint", "other", "unknown"}
    for item in evidence:
        payload = item.payload
        year_value = payload.get("publication_year")
        publication_year = (
            year_value
            if isinstance(year_value, int) and not isinstance(year_value, bool)
            else None
        )
        kind_value = payload.get("evidence_kind")
        evidence_kind = cast(
            EvidenceKind | None,
            kind_value if kind_value in valid_evidence_kinds else None,
        )
        version_value = payload.get("document_version_kind")
        version_kind = cast(
            DocumentVersionKind | None,
            version_value if version_value in valid_version_kinds else None,
        )
        paper_id_value = payload.get("paper_id")
        paper_id = paper_id_value if isinstance(paper_id_value, str) else None
        if not matches_filters(
            filters,
            operation=SearchOperation.EVIDENCE_SEARCH,
            paper_id=paper_id,
            publication_year=publication_year,
            evidence_kind=evidence_kind,
            document_version_kind=version_kind,
        ):
            raise SnapshotIndexMismatch(
                "authoritative evidence does not satisfy the requested dense filters"
            )
