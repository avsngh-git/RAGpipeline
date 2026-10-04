"""Search over published generations, with evidence content served by Qdrant (P35-09).

PostgreSQL authorizes evidence IDs against snapshot membership and permission
evidence but never re-reads text on this path (ADR-0022 items 1-2).
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from typing import Protocol, cast
from uuid import UUID

import asyncpg  # type: ignore[import-untyped]

from research_platform.ingestion.embeddings import (
    validate_supported_embedding_configuration,
)
from research_platform.ingestion.generation_index import (
    GenerationIndexConfiguration,
    GenerationQdrantCollection,
    generation_filter,
    passage_point_id,
    with_conditions,
)
from research_platform.ingestion.generation_registry import GenerationRecord
from research_platform.ingestion.indexing import (
    IndexInput,
    IndexMatch,
    IndexReconciliationRequired,
    ReadySnapshotIndex,
    SnapshotAccessDenied,
    SnapshotIndexMismatch,
    SnapshotIndexNotReady,
)
from research_platform.search.contracts import (
    DEFAULT_SEARCH_LIMITS,
    SearchFilters,
    SearchOperation,
)
from research_platform.search.dense_search import (
    DenseQueryEmbedder,
    DenseSearchResponse,
    HydratedDenseHit,
    ProfileDenseIndexMismatch,
    UnsupportedRetrievalProfile,
    _qdrant_payload_conditions,
    _validate_hydrated_filter_eligibility,
    _validate_normalized_query_vector,
)
from research_platform.search.profiles import RetrievalProfile

_AUTHORIZE_SQL = """
SELECT chunk.id AS evidence_id
FROM snapshot_items AS item
JOIN documents AS document
  ON document.id = item.document_id AND document.paper_id = item.paper_id
JOIN extractions AS extraction
  ON extraction.id = item.extraction_id
 AND extraction.document_id = item.document_id
JOIN document_artifacts AS artifact
  ON artifact.id = extraction.source_artifact_id
 AND artifact.document_id = extraction.document_id
JOIN document_permission_evidence AS permission
  ON permission.id = artifact.permission_evidence_id
 AND permission.document_id = artifact.document_id
JOIN snapshot_item_chunks AS selected
  ON selected.snapshot_id = item.snapshot_id
 AND selected.paper_id = item.paper_id
 AND selected.document_id = item.document_id
 AND selected.extraction_id = item.extraction_id
JOIN chunks AS chunk
  ON chunk.id = selected.chunk_id
 AND chunk.document_id = selected.document_id
 AND chunk.extraction_id = selected.extraction_id
WHERE item.snapshot_id = $1
  AND chunk.id = ANY($2::text[])
  AND extraction.status IN ('completed', 'partial')
  AND artifact.storage_permitted
  AND artifact.indexing_permitted
  AND permission.storage_permitted
  AND permission.indexing_permitted
"""


class GenerationLookup(Protocol):
    async def by_snapshot(
        self, configuration_id: str, snapshot_id: UUID
    ) -> GenerationRecord | None: ...


class PassageAuthorizer:
    """Confirm evidence IDs are selected, permitted members of a finalized snapshot."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def authorize(self, snapshot_id: UUID, evidence_ids: Sequence[str]) -> None:
        if not evidence_ids:
            return
        async with self._pool.acquire() as connection:
            status = await connection.fetchval(
                "SELECT status FROM snapshots WHERE id = $1", snapshot_id
            )
            if status is None:
                raise ValueError("snapshot does not exist")
            if status != "finalized":
                raise SnapshotAccessDenied(
                    "normal search requires a finalized snapshot"
                )
            rows = await connection.fetch(
                _AUTHORIZE_SQL, snapshot_id, list(dict.fromkeys(evidence_ids))
            )
        if {str(row["evidence_id"]) for row in rows} != set(evidence_ids):
            raise PermissionError(
                "results include evidence that is not selected and indexing-permitted"
            )


class QdrantContentReader:
    """Read evidence content from a generation's passage points, in request order."""

    def __init__(
        self,
        passages: GenerationQdrantCollection,
        authorizer: PassageAuthorizer,
        configuration: GenerationIndexConfiguration,
    ) -> None:
        self._passages = passages
        self._authorizer = authorizer
        self._configuration = configuration

    async def read(
        self, snapshot_id: UUID, generation: int, evidence_ids: Sequence[str]
    ) -> tuple[IndexInput, ...]:
        if len(set(evidence_ids)) != len(evidence_ids):
            raise SnapshotIndexMismatch("results contain duplicate evidence IDs")
        if not evidence_ids:
            return ()
        configuration_id = self._configuration.configuration_id
        matches = await self._passages.retrieve(
            [
                passage_point_id(evidence_id, configuration_id)
                for evidence_id in evidence_ids
            ]
        )
        by_evidence = {
            str(match.payload.get("evidence_id")): match for match in matches
        }
        missing = [e for e in evidence_ids if e not in by_evidence]
        if missing:
            raise IndexReconciliationRequired(
                "evidence is missing from the generation collection"
            )
        inputs = []
        for evidence_id in evidence_ids:
            payload = by_evidence[evidence_id].payload
            _check_content(payload, generation, configuration_id)
            inputs.append(
                IndexInput(
                    evidence_id=evidence_id,
                    text=cast(str, payload["text"]),
                    # Points are shared across generations, so the snapshot comes from
                    # the request, as in PostgreSQL hydration.
                    payload={**payload, "snapshot_id": str(snapshot_id)},
                )
            )
        await self._authorizer.authorize(snapshot_id, evidence_ids)
        return tuple(inputs)


class GenerationDenseSearch:
    """Dense branch over a published generation; matches ``DenseEvidenceBranch``."""

    def __init__(
        self,
        *,
        passages: GenerationQdrantCollection,
        reader: QdrantContentReader,
        registry: GenerationLookup,
        configuration: GenerationIndexConfiguration,
        query_embedder: DenseQueryEmbedder,
        exact: bool = True,
    ) -> None:
        # Exact search keeps results deterministic for pinned generations; HNSW graphs
        # differ between collections even for identical vectors.
        self._exact = exact
        self._passages = passages
        self._reader = reader
        self._registry = registry
        self._configuration = configuration
        self._query_embedder = query_embedder

    async def generation_for(self, snapshot_id: UUID) -> int:
        """The published generation built from a snapshot under this configuration."""
        record = await self._registry.by_snapshot(
            self._configuration.configuration_id, snapshot_id
        )
        if record is None or record.state != "published":
            raise SnapshotIndexNotReady("snapshot has no published generation")
        return record.generation

    async def read_evidence(
        self, snapshot_id: UUID, evidence_ids: Sequence[str]
    ) -> tuple[IndexInput, ...]:
        """Serve ranked evidence content for a snapshot's published generation."""
        generation = await self.generation_for(snapshot_id)
        return await self._reader.read(snapshot_id, generation, evidence_ids)

    async def search_query(
        self,
        profile: RetrievalProfile,
        query: str,
        *,
        limit: int,
        filters: SearchFilters = SearchFilters(),
    ) -> DenseSearchResponse:
        return await self._search(
            profile, query, limit=limit, filters=filters, hybrid_component=False
        )

    async def search_hybrid_component_query(
        self,
        profile: RetrievalProfile,
        query: str,
        *,
        limit: int,
        filters: SearchFilters = SearchFilters(),
        ready_index: ReadySnapshotIndex | None = None,
    ) -> DenseSearchResponse:
        return await self._search(
            profile, query, limit=limit, filters=filters, hybrid_component=True
        )

    async def evaluate_hybrid_component_query(
        self,
        profile: RetrievalProfile,
        query: str,
        *,
        limit: int,
        filters: SearchFilters = SearchFilters(),
    ) -> DenseSearchResponse:
        raise SnapshotAccessDenied(
            "generation search serves published generations only"
        )

    async def _search(
        self,
        profile: RetrievalProfile,
        query: str,
        *,
        limit: int,
        filters: SearchFilters,
        hybrid_component: bool,
    ) -> DenseSearchResponse:
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query text must be non-empty")
        if len(query) > DEFAULT_SEARCH_LIMITS.max_query_characters:
            raise ValueError("query text exceeds the configured character limit")
        index_configuration_id = _validate_profile(
            profile, self._configuration, limit, hybrid_component=hybrid_component
        )
        filters.validate_for(SearchOperation.EVIDENCE_SEARCH)
        snapshot_id = profile.snapshot.snapshot_id
        generation = await self.generation_for(snapshot_id)
        dense = self._configuration.dense_configuration()
        vector = await self._query_embedder.embed_query(query, configuration=dense)
        _validate_normalized_query_vector(vector, dense.vector_size)
        search_filter = with_conditions(
            generation_filter(generation),
            [
                condition
                for condition in _qdrant_payload_conditions(filters)
                if condition.get("key") != "filter_payload_revision"
            ],
        )
        candidate_count = await self._passages.count(search_filter)
        matches = await self._passages.query_dense(
            vector, filter_=search_filter, limit=limit, exact=self._exact
        )
        evidence_ids = [str(match.payload.get("evidence_id")) for match in matches]
        inputs = await self._reader.read(snapshot_id, generation, evidence_ids)
        _validate_hydrated_filter_eligibility(inputs, filters)
        hits = tuple(
            IndexMatch(
                evidence_id=item.evidence_id, score=match.score, payload=item.payload
            )
            for item, match in zip(inputs, matches, strict=True)
        )
        return DenseSearchResponse(
            snapshot_id=snapshot_id,
            profile_id=profile.profile_id,
            index_configuration_id=index_configuration_id,
            requested_limit=limit,
            hits=hits,
            candidate_count=candidate_count,
            truncated=candidate_count > limit,
            applied_filters=filters,
            hydrated_hits=tuple(
                HydratedDenseHit(rank=rank, score=hit.score, evidence=item)
                for rank, (hit, item) in enumerate(zip(hits, inputs, strict=True), 1)
            ),
        )


def _check_content(payload: object, generation: int, configuration_id: str) -> None:
    if not isinstance(payload, dict):
        raise SnapshotIndexMismatch("passage payload is malformed")
    text = payload.get("text")
    if not isinstance(text, str) or hashlib.sha256(
        text.encode("utf-8")
    ).hexdigest() != payload.get("text_sha256"):
        raise SnapshotIndexMismatch("passage text does not match its hash")
    added = payload.get("added_generation")
    retired = payload.get("retired_generation")
    if (
        payload.get("index_configuration_id") != configuration_id
        or not isinstance(added, int)
        or added > generation
        or (isinstance(retired, int) and retired <= generation)
    ):
        raise SnapshotIndexMismatch(
            "passage is not visible in the requested generation"
        )


def _validate_profile(
    profile: RetrievalProfile,
    configuration: GenerationIndexConfiguration,
    limit: int,
    *,
    hybrid_component: bool,
) -> str:
    """Check the dense stage matches the generation model; return the profile's index ID.

    Generation collections differ from the per-snapshot collection the profile names
    only in collection name and batch size, which do not change vectors.
    """
    if not isinstance(profile, RetrievalProfile):
        raise ValueError("profile must be a RetrievalProfile")
    if profile.reranker is not None:
        raise UnsupportedRetrievalProfile(
            "dense search cannot execute a profile requiring reranking"
        )
    if hybrid_component != (
        profile.lexical_index is not None or profile.fusion is not None
    ):
        raise UnsupportedRetrievalProfile(
            "profile stages do not match the requested dense search role"
        )
    identity = profile.dense_index
    if identity is None:
        raise UnsupportedRetrievalProfile(
            "dense search requires a dense index identity"
        )
    configured_limit = profile.candidate_limits.dense_top_k
    if (
        isinstance(limit, bool)
        or not isinstance(limit, int)
        or limit <= 0
        or limit > DEFAULT_SEARCH_LIMITS.max_candidate_limit
        or configured_limit is None
        or limit > configured_limit
    ):
        raise ValueError("limit is outside the profile's dense candidate bounds")
    dense = configuration.dense_configuration()
    if (
        identity.model != dense.embedding_model
        or identity.revision != dense.embedding_revision
        or identity.preprocessing_revision != dense.preprocessing_revision
        or identity.dimensions != dense.vector_size
        or identity.maximum_input_tokens != dense.maximum_input_tokens
    ):
        raise ProfileDenseIndexMismatch(
            "retrieval profile does not match the generation dense model"
        )
    try:
        validate_supported_embedding_configuration(dense)
    except ValueError as error:
        raise ProfileDenseIndexMismatch(str(error)) from None
    return identity.index_configuration_id
