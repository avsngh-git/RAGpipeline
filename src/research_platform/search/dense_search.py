"""Profile-bound dense search over one validated snapshot index."""

from __future__ import annotations

from collections.abc import Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from research_platform.ingestion.indexing import (
    IndexConfiguration,
    IndexMatch,
    QdrantIndex,
    ReadySnapshotIndex,
    SnapshotIndexMismatch,
)
from research_platform.ingestion.snapshot_selection import SnapshotSelection
from research_platform.search.contracts import DEFAULT_SEARCH_LIMITS
from research_platform.search.profiles import RetrievalProfile


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
class DenseSearchResponse:
    snapshot_id: UUID
    profile_id: str
    index_configuration_id: str
    requested_limit: int
    hits: tuple[IndexMatch, ...]


class UnsupportedRetrievalProfile(ValueError):
    """The selected profile requires a retrieval stage this service does not own."""


class ProfileDenseIndexMismatch(SnapshotIndexMismatch):
    """Dense model and vector-index fields disagree with the executable adapter."""


class SnapshotDenseSearch:
    """Execute dense-only profiles after resolving and leasing their exact index."""

    def __init__(self, gate: SnapshotIndexGate, index: QdrantIndex) -> None:
        self._gate = gate
        self._index = index

    async def search(
        self, profile: RetrievalProfile, vector: Sequence[float], *, limit: int
    ) -> DenseSearchResponse:
        """Serve only a finalized snapshot through its exact ready profile."""
        return await self._search(profile, vector, limit=limit, evaluation=False)

    async def evaluate(
        self, profile: RetrievalProfile, vector: Sequence[float], *, limit: int
    ) -> DenseSearchResponse:
        """Use the separate evaluation path, which may name a draft snapshot."""
        return await self._search(profile, vector, limit=limit, evaluation=True)

    async def _search(
        self,
        profile: RetrievalProfile,
        vector: Sequence[float],
        *,
        limit: int,
        evaluation: bool,
    ) -> DenseSearchResponse:
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

        configuration = self._index.configuration
        if (
            dense_identity.model != configuration.embedding_model
            or dense_identity.revision != configuration.embedding_revision
            or dense_identity.preprocessing_revision
            != configuration.preprocessing_revision
            or dense_identity.dimensions != configuration.vector_size
            or dense_identity.maximum_input_tokens != configuration.maximum_input_tokens
            or dense_identity.index_configuration_id != configuration.configuration_id
        ):
            raise ProfileDenseIndexMismatch(
                "retrieval profile does not match the configured dense index"
            )

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
        return DenseSearchResponse(
            snapshot_id=profile.snapshot.snapshot_id,
            profile_id=profile.profile_id,
            index_configuration_id=configuration.configuration_id,
            requested_limit=limit,
            hits=hits,
        )
