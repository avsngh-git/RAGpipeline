"""Profile-bound dense search over one validated snapshot index."""

from __future__ import annotations

import math
from collections.abc import Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from research_platform.ingestion.embeddings import (
    validate_supported_embedding_configuration,
)
from research_platform.ingestion.indexing import (
    IndexConfiguration,
    IndexInput,
    IndexMatch,
    QdrantIndex,
    ReadySnapshotIndex,
    SnapshotIndexMismatch,
)
from research_platform.ingestion.snapshot_selection import SnapshotSelection
from research_platform.search.contracts import DEFAULT_SEARCH_LIMITS
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
    snapshot_id: UUID
    profile_id: str
    index_configuration_id: str
    requested_limit: int
    hits: tuple[IndexMatch, ...]
    hydrated_hits: tuple[HydratedDenseHit, ...] = ()


class UnsupportedRetrievalProfile(ValueError):
    """The selected profile requires a retrieval stage this service does not own."""


class ProfileDenseIndexMismatch(SnapshotIndexMismatch):
    """Dense model and vector-index fields disagree with the executable adapter."""


class SnapshotDenseSearch:
    """Execute dense-only profiles after resolving and leasing their exact index."""

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
        self, profile: RetrievalProfile, vector: Sequence[float], *, limit: int
    ) -> DenseSearchResponse:
        """Serve only a finalized snapshot through its exact ready profile."""
        return await self._search(
            profile, vector, limit=limit, evaluation=False, hydrate=False
        )

    async def search_query(
        self, profile: RetrievalProfile, query: str, *, limit: int
    ) -> DenseSearchResponse:
        """Embed a pinned-model query, retrieve candidates and hydrate source rows."""
        return await self._search_query(profile, query, limit=limit, evaluation=False)

    async def evaluate_query(
        self, profile: RetrievalProfile, query: str, *, limit: int
    ) -> DenseSearchResponse:
        """Run a named evaluation query, including explicit draft snapshots."""
        return await self._search_query(profile, query, limit=limit, evaluation=True)

    async def _search_query(
        self,
        profile: RetrievalProfile,
        query: str,
        *,
        limit: int,
        evaluation: bool,
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
        _validate_search_request(profile, configuration, limit)
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
            evaluation=evaluation,
            hydrate=True,
        )

    async def evaluate(
        self, profile: RetrievalProfile, vector: Sequence[float], *, limit: int
    ) -> DenseSearchResponse:
        """Use the separate evaluation path, which may name a draft snapshot."""
        return await self._search(
            profile, vector, limit=limit, evaluation=True, hydrate=False
        )

    async def _search(
        self,
        profile: RetrievalProfile,
        vector: Sequence[float],
        *,
        limit: int,
        evaluation: bool,
        hydrate: bool,
    ) -> DenseSearchResponse:
        configuration = self._index.configuration
        _validate_search_request(profile, configuration, limit)

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
            hits = await self._index.query_snapshot(
                vector, profile.snapshot.snapshot_id, limit=limit
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
            if hydrate:
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
) -> None:
    if not isinstance(profile, RetrievalProfile):
        raise ValueError("profile must be a RetrievalProfile")
    if (
        profile.lexical_index is not None
        or profile.fusion is not None
        or profile.reranker is not None
    ):
        raise UnsupportedRetrievalProfile(
            "dense search cannot execute a profile requiring lexical, fusion, or reranking stages"
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
