"""Rebuildable, configuration-checked Qdrant indexing for evidence chunks."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol, cast
from urllib.parse import quote
from uuid import UUID, uuid5

import asyncpg  # type: ignore[import-untyped]
import httpx

IndexDistance = Literal["Cosine", "Dot", "Euclid", "Manhattan"]
IndexState = Literal[
    "pending", "building", "ready", "reconciliation_required", "failed"
]
_DISTANCE_VALUES = {"Cosine", "Dot", "Euclid", "Manhattan"}
_COLLECTION_NAME = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


@dataclass(frozen=True)
class IndexConfiguration:
    """All choices that change vector meaning, shape, batching or index identity."""

    collection_name: str
    embedding_model: str
    embedding_revision: str
    preprocessing_revision: str
    vector_size: int
    distance: IndexDistance
    batch_size: int
    maximum_input_tokens: int

    def __post_init__(self) -> None:
        for field_name in (
            "collection_name",
            "embedding_model",
            "embedding_revision",
            "preprocessing_revision",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must be a non-empty string")
        if not _COLLECTION_NAME.fullmatch(self.collection_name):
            raise ValueError("collection_name contains unsupported characters")
        for field_name in ("vector_size", "batch_size", "maximum_input_tokens"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{field_name} must be a positive integer")
        if self.distance not in _DISTANCE_VALUES:
            raise ValueError("unsupported Qdrant distance metric")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "collection_name": self.collection_name,
            "embedding_model": self.embedding_model,
            "embedding_revision": self.embedding_revision,
            "preprocessing_revision": self.preprocessing_revision,
            "vector_size": self.vector_size,
            "distance": self.distance,
            "batch_size": self.batch_size,
            "maximum_input_tokens": self.maximum_input_tokens,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> IndexConfiguration:
        expected = {
            "schema_version",
            "collection_name",
            "embedding_model",
            "embedding_revision",
            "preprocessing_revision",
            "vector_size",
            "distance",
            "batch_size",
            "maximum_input_tokens",
        }
        if set(data) != expected or data.get("schema_version") != 1:
            raise ValueError("unsupported index configuration fields or version")
        if isinstance(data["schema_version"], bool):
            raise ValueError("unsupported index configuration fields or version")
        for name in (
            "collection_name",
            "embedding_model",
            "embedding_revision",
            "preprocessing_revision",
            "distance",
        ):
            if not isinstance(data[name], str):
                raise ValueError(f"{name} must be a string")
        for name in ("vector_size", "batch_size", "maximum_input_tokens"):
            if isinstance(data[name], bool) or not isinstance(data[name], int):
                raise ValueError(f"{name} must be an integer")
        return cls(
            collection_name=cast(str, data["collection_name"]),
            embedding_model=cast(str, data["embedding_model"]),
            embedding_revision=cast(str, data["embedding_revision"]),
            preprocessing_revision=cast(str, data["preprocessing_revision"]),
            vector_size=cast(int, data["vector_size"]),
            distance=cast(IndexDistance, data["distance"]),
            batch_size=cast(int, data["batch_size"]),
            maximum_input_tokens=cast(int, data["maximum_input_tokens"]),
        )

    @property
    def configuration_id(self) -> str:
        canonical = json.dumps(
            self.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class IndexInput:
    evidence_id: str
    text: str
    payload: Mapping[str, object]

    def __post_init__(self) -> None:
        if not isinstance(self.evidence_id, str) or not self.evidence_id.strip():
            raise ValueError("evidence_id must be a non-empty string")
        if not isinstance(self.text, str) or not self.text.strip():
            raise ValueError("index input text must be non-empty")
        for key in ("paper_id", "document_id", "extraction_id", "snapshot_id"):
            if not self.payload.get(key):
                raise ValueError(f"index payload must include {key}")


@dataclass(frozen=True)
class IndexPoint:
    evidence_id: str
    vector: Sequence[float]
    payload: Mapping[str, object]


@dataclass(frozen=True)
class IndexMatch:
    evidence_id: str
    score: float
    payload: Mapping[str, object]


@dataclass(frozen=True)
class IndexBuildReport:
    snapshot_id: UUID
    configuration_id: str
    expected_count: int
    indexed_count: int
    batch_count: int


class IndexConfigurationMismatch(RuntimeError):
    """A collection already exists with a different vector configuration."""


class IndexReconciliationRequired(RuntimeError):
    """PostgreSQL and Qdrant do not currently agree on snapshot membership."""


class VectorEmbedder(Protocol):
    """Adapter seam for the model selected by the 10-paper comparison."""

    async def embed(
        self,
        texts: Sequence[str],
        *,
        configuration: IndexConfiguration,
    ) -> Sequence[Sequence[float]]: ...


class IndexStateStore(Protocol):
    async def load_snapshot_inputs(
        self, snapshot_id: UUID, configuration: IndexConfiguration
    ) -> tuple[IndexInput, ...]: ...

    async def set_index_state(
        self,
        snapshot_id: UUID,
        configuration: IndexConfiguration,
        *,
        status: IndexState,
        expected_count: int,
        indexed_count: int,
        details: Mapping[str, object],
    ) -> None: ...


class QdrantIndex:
    """Small REST adapter for idempotent upsert, snapshot query and reconciliation."""

    def __init__(self, configuration: IndexConfiguration, http: httpx.AsyncClient):
        self.configuration = configuration
        self._http = http
        self._collection_url = "/collections/" + quote(
            configuration.collection_name, safe=""
        )

    async def collection_exists(self) -> bool:
        """Check collection presence without creating or otherwise changing it."""
        response = await self._http.get(self._collection_url)
        if response.status_code == 404:
            return False
        response.raise_for_status()
        return True

    async def ensure_collection(self) -> None:
        response = await self._http.get(self._collection_url)
        if response.status_code == 404:
            created = await self._http.put(
                self._collection_url,
                json={
                    "vectors": {
                        "size": self.configuration.vector_size,
                        "distance": self.configuration.distance,
                    }
                },
            )
            if created.status_code not in {200, 409}:
                created.raise_for_status()
            response = await self._http.get(self._collection_url)
        response.raise_for_status()
        body = response.json()
        result = body.get("result") if isinstance(body, dict) else None
        collection_config = result.get("config") if isinstance(result, dict) else None
        params = (
            collection_config.get("params")
            if isinstance(collection_config, dict)
            else None
        )
        vectors = params.get("vectors") if isinstance(params, dict) else None
        if not isinstance(vectors, dict):
            raise IndexConfigurationMismatch(
                "Qdrant collection does not use one unnamed dense vector"
            )
        if (
            vectors.get("size") != self.configuration.vector_size
            or vectors.get("distance") != self.configuration.distance
        ):
            raise IndexConfigurationMismatch(
                "Qdrant collection dimensions or distance differ from configuration"
            )

    async def upsert(self, points: Sequence[IndexPoint]) -> int:
        if len(points) > self.configuration.batch_size:
            raise ValueError("Qdrant upsert exceeds the configured batch size")
        if not points:
            return 0
        point_ids: set[UUID] = set()
        serialized: list[dict[str, object]] = []
        for point in points:
            vector = _validate_vector(point.vector, self.configuration.vector_size)
            snapshot_id = point.payload.get("snapshot_id")
            config_id = point.payload.get("index_configuration_id")
            if config_id != self.configuration.configuration_id:
                raise IndexConfigurationMismatch(
                    "point payload uses a different index configuration"
                )
            if not isinstance(snapshot_id, str) or not snapshot_id:
                raise ValueError("point payload must include snapshot_id")
            qdrant_id = _qdrant_point_id(snapshot_id, point.evidence_id)
            if qdrant_id in point_ids:
                raise ValueError("an upsert batch cannot repeat point identities")
            point_ids.add(qdrant_id)
            payload = dict(point.payload)
            payload["evidence_id"] = point.evidence_id
            serialized.append(
                {"id": str(qdrant_id), "vector": vector, "payload": payload}
            )
        response = await self._http.put(
            f"{self._collection_url}/points",
            params={"wait": "true"},
            json={"points": serialized},
        )
        response.raise_for_status()
        return len(serialized)

    async def query_snapshot(
        self,
        vector: Sequence[float],
        snapshot_id: UUID,
        *,
        limit: int,
    ) -> tuple[IndexMatch, ...]:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise ValueError("query limit must be a positive integer")
        checked_vector = _validate_vector(vector, self.configuration.vector_size)
        response = await self._http.post(
            f"{self._collection_url}/points/query",
            json={
                "query": checked_vector,
                "limit": limit,
                "filter": _snapshot_filter(snapshot_id),
                "with_payload": True,
                "with_vector": False,
            },
        )
        response.raise_for_status()
        body = response.json()
        result = body.get("result") if isinstance(body, dict) else None
        raw_points = result.get("points") if isinstance(result, dict) else None
        if not isinstance(raw_points, list):
            raise RuntimeError("Qdrant returned an invalid query response")
        matches: list[IndexMatch] = []
        for item in raw_points:
            if not isinstance(item, dict):
                raise RuntimeError("Qdrant returned a malformed point")
            payload = item.get("payload")
            score = item.get("score")
            if (
                not isinstance(payload, dict)
                or not isinstance(payload.get("evidence_id"), str)
                or isinstance(score, bool)
                or not isinstance(score, (int, float))
                or not math.isfinite(score)
            ):
                raise RuntimeError("Qdrant returned a point without evidence identity")
            matches.append(
                IndexMatch(
                    evidence_id=payload["evidence_id"],
                    score=float(score),
                    payload=payload,
                )
            )
        return tuple(matches)

    async def count_snapshot(self, snapshot_id: UUID) -> int:
        response = await self._http.post(
            f"{self._collection_url}/points/count",
            json={"filter": _snapshot_filter(snapshot_id), "exact": True},
        )
        response.raise_for_status()
        body = response.json()
        result = body.get("result") if isinstance(body, dict) else None
        count = result.get("count") if isinstance(result, dict) else None
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise RuntimeError("Qdrant returned an invalid exact count")
        return count

    async def delete_snapshot(self, snapshot_id: UUID) -> None:
        response = await self._http.post(
            f"{self._collection_url}/points/delete",
            params={"wait": "true"},
            json={"filter": _snapshot_filter(snapshot_id)},
        )
        response.raise_for_status()

    async def scroll_snapshot_ids(
        self, snapshot_id: UUID, *, page_size: int = 100
    ) -> tuple[str, ...]:
        if (
            isinstance(page_size, bool)
            or not isinstance(page_size, int)
            or page_size <= 0
        ):
            raise ValueError("page_size must be a positive integer")
        identities: list[str] = []
        offset: str | int | None = None
        while True:
            payload: dict[str, object] = {
                "filter": _snapshot_filter(snapshot_id),
                "limit": page_size,
                "with_payload": ["evidence_id"],
                "with_vector": False,
            }
            if offset is not None:
                payload["offset"] = offset
            response = await self._http.post(
                f"{self._collection_url}/points/scroll", json=payload
            )
            response.raise_for_status()
            body = response.json()
            result = body.get("result") if isinstance(body, dict) else None
            points = result.get("points") if isinstance(result, dict) else None
            next_offset = (
                result.get("next_page_offset") if isinstance(result, dict) else None
            )
            if not isinstance(points, list):
                raise RuntimeError("Qdrant returned an invalid scroll response")
            for point in points:
                if not isinstance(point, dict) or not isinstance(
                    point.get("payload"), dict
                ):
                    raise RuntimeError("Qdrant returned a malformed point")
                evidence_id = point["payload"].get("evidence_id")
                if not isinstance(evidence_id, str):
                    raise RuntimeError("Qdrant point has no evidence_id payload")
                identities.append(evidence_id)
            if next_offset is None or not points:
                break
            if not isinstance(next_offset, (str, int)) or isinstance(next_offset, bool):
                raise RuntimeError("Qdrant returned an invalid scroll offset")
            offset = next_offset
        return tuple(identities)


def _qdrant_point_id(snapshot_id: str, evidence_id: str) -> UUID:
    return uuid5(
        UUID("2cbcf690-1c7a-4f6c-9254-a25cf78fb014"), f"{snapshot_id}:{evidence_id}"
    )


def _snapshot_filter(snapshot_id: UUID) -> dict[str, object]:
    return {"must": [{"key": "snapshot_id", "match": {"value": str(snapshot_id)}}]}


def _validate_vector(vector: Sequence[float], dimension: int) -> list[float]:
    if len(vector) != dimension:
        raise ValueError(f"vector must contain exactly {dimension} values")
    values: list[float] = []
    for value in vector:
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
        ):
            raise ValueError("vector values must be finite numbers")
        values.append(float(value))
    return values


class IndexRepository:
    """Persist index identity, resolve authorized snapshot text and mark sync state."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def load_snapshot_inputs(
        self, snapshot_id: UUID, configuration: IndexConfiguration
    ) -> tuple[IndexInput, ...]:
        async with self._pool.acquire() as connection:
            expected_papers = await connection.fetchval(
                "SELECT count(*) FROM snapshot_items WHERE snapshot_id = $1",
                snapshot_id,
            )
            rows = await connection.fetch(
                """
                SELECT chunk.id AS evidence_id, chunk.text, paper.id AS paper_id,
                       document.id AS document_id, extraction.id AS extraction_id,
                       extraction.source_artifact_id, document.version,
                       paper.publication_year, paper.title,
                       section.id AS section_id, section.title AS section_title
                FROM snapshot_items AS item
                JOIN papers AS paper ON paper.id = item.paper_id
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
                JOIN chunks AS chunk
                  ON chunk.document_id = item.document_id
                 AND chunk.extraction_id = item.extraction_id
                LEFT JOIN sections AS section
                  ON section.id = chunk.section_id
                 AND section.extraction_id = chunk.extraction_id
                WHERE item.snapshot_id = $1
                  AND (item.chunking_configuration_id IS NULL
                       OR chunk.metadata ->> 'chunking_configuration_id' =
                          item.chunking_configuration_id)
                  AND extraction.status IN ('completed', 'partial')
                  AND artifact.storage_permitted
                  AND artifact.indexing_permitted
                  AND permission.storage_permitted
                  AND permission.indexing_permitted
                ORDER BY paper.id, chunk.id
                """,
                snapshot_id,
            )
        if expected_papers == 0:
            raise ValueError("cannot build an index for an empty snapshot")
        paper_ids = {str(row["paper_id"]) for row in rows}
        if len(paper_ids) != expected_papers:
            raise PermissionError(
                "every snapshot paper must have indexed-permitted extraction evidence"
            )
        configuration_id = configuration.configuration_id
        return tuple(
            IndexInput(
                evidence_id=row["evidence_id"],
                text=row["text"],
                payload={
                    "snapshot_id": str(snapshot_id),
                    "index_configuration_id": configuration_id,
                    "paper_id": row["paper_id"],
                    "document_id": str(row["document_id"]),
                    "document_version": row["version"],
                    "extraction_id": str(row["extraction_id"]),
                    "source_artifact_id": str(row["source_artifact_id"]),
                    "publication_year": row["publication_year"],
                    "paper_title": row["title"],
                    "section_id": str(row["section_id"])
                    if row["section_id"] is not None
                    else None,
                    "section_title": row["section_title"],
                },
            )
            for row in rows
        )

    async def set_index_state(
        self,
        snapshot_id: UUID,
        configuration: IndexConfiguration,
        *,
        status: IndexState,
        expected_count: int,
        indexed_count: int,
        details: Mapping[str, object],
    ) -> None:
        if expected_count < 0 or indexed_count < 0:
            raise ValueError("index counts must not be negative")
        configuration_json = json.dumps(configuration.to_dict(), sort_keys=True)
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                collection_owner = await connection.fetchval(
                    """
                    SELECT configuration_id FROM index_configurations
                    WHERE configuration ->> 'collection_name' = $1
                    FOR SHARE
                    """,
                    configuration.collection_name,
                )
                if (
                    collection_owner is not None
                    and collection_owner != configuration.configuration_id
                ):
                    raise IndexConfigurationMismatch(
                        "Qdrant collection name is already assigned to another configuration"
                    )
                await connection.fetchval(
                    """
                    INSERT INTO index_configurations (configuration_id, configuration)
                    VALUES ($1, $2::jsonb)
                    ON CONFLICT (configuration_id) DO NOTHING
                    RETURNING configuration_id
                    """,
                    configuration.configuration_id,
                    configuration_json,
                )
                existing_config = await connection.fetchval(
                    "SELECT configuration::text FROM index_configurations WHERE configuration_id = $1",
                    configuration.configuration_id,
                )
                if existing_config is None:
                    raise RuntimeError("index configuration was not persisted")
                if json.loads(existing_config) != configuration.to_dict():
                    raise ValueError(
                        "index configuration ID conflicts with stored data"
                    )
                await connection.execute(
                    """
                    INSERT INTO snapshot_index_states
                        (snapshot_id, configuration_id, collection_name, status,
                         expected_count, indexed_count, reconciled_at, details)
                    VALUES ($1, $2, $3, $4, $5, $6,
                            CASE WHEN $4 = 'ready' THEN now() ELSE NULL END,
                            $7::jsonb)
                    ON CONFLICT (snapshot_id, configuration_id)
                    DO UPDATE SET collection_name = EXCLUDED.collection_name,
                                  status = EXCLUDED.status,
                                  expected_count = EXCLUDED.expected_count,
                                  indexed_count = EXCLUDED.indexed_count,
                                  reconciled_at = EXCLUDED.reconciled_at,
                                  details = EXCLUDED.details
                    """,
                    snapshot_id,
                    configuration.configuration_id,
                    configuration.collection_name,
                    status,
                    expected_count,
                    indexed_count,
                    json.dumps(dict(details), sort_keys=True),
                )


async def rebuild_snapshot_index(
    store: IndexStateStore,
    index: QdrantIndex,
    embedder: VectorEmbedder,
    snapshot_id: UUID,
) -> IndexBuildReport:
    """Replace one snapshot's points and reconcile exact membership in Qdrant."""
    configuration = index.configuration
    inputs = await store.load_snapshot_inputs(snapshot_id, configuration)
    evidence_ids = [item.evidence_id for item in inputs]
    if len(set(evidence_ids)) != len(evidence_ids):
        raise ValueError("snapshot contains duplicate evidence identities")
    if not inputs:
        raise ValueError("cannot build an index for an empty snapshot")
    expected_count = len(inputs)
    await store.set_index_state(
        snapshot_id,
        configuration,
        status="building",
        expected_count=expected_count,
        indexed_count=0,
        details={"operation": "snapshot_rebuild"},
    )
    indexed_count = 0
    batch_count = 0
    try:
        await index.ensure_collection()
        await index.delete_snapshot(snapshot_id)
        for start in range(0, expected_count, configuration.batch_size):
            batch = inputs[start : start + configuration.batch_size]
            vectors = await embedder.embed(
                [item.text for item in batch], configuration=configuration
            )
            if len(vectors) != len(batch):
                raise ValueError("embedding adapter returned a different item count")
            points = tuple(
                IndexPoint(
                    evidence_id=item.evidence_id,
                    vector=vector,
                    payload=item.payload,
                )
                for item, vector in zip(batch, vectors, strict=True)
            )
            indexed_count += await index.upsert(points)
            batch_count += 1
        observed_count = await index.count_snapshot(snapshot_id)
        observed_ids = await index.scroll_snapshot_ids(snapshot_id)
        expected_ids_sha256 = _evidence_ids_fingerprint(evidence_ids)
        observed_ids_sha256 = _evidence_ids_fingerprint(observed_ids)
        if (
            observed_count != expected_count
            or len(observed_ids) != expected_count
            or set(observed_ids) != set(evidence_ids)
        ):
            raise IndexReconciliationRequired(
                "Qdrant evidence identities differ from the PostgreSQL snapshot"
            )
        await store.set_index_state(
            snapshot_id,
            configuration,
            status="ready",
            expected_count=expected_count,
            indexed_count=observed_count,
            details={
                "operation": "snapshot_rebuild",
                "batch_count": batch_count,
                "evidence_ids_sha256": expected_ids_sha256,
                "qdrant_evidence_ids_sha256": observed_ids_sha256,
            },
        )
        return IndexBuildReport(
            snapshot_id=snapshot_id,
            configuration_id=configuration.configuration_id,
            expected_count=expected_count,
            indexed_count=observed_count,
            batch_count=batch_count,
        )
    except Exception as error:
        await store.set_index_state(
            snapshot_id,
            configuration,
            status="reconciliation_required",
            expected_count=expected_count,
            indexed_count=indexed_count,
            details={
                "operation": "snapshot_rebuild",
                "failure_category": type(error).__name__,
            },
        )
        raise


def _evidence_ids_fingerprint(evidence_ids: Sequence[str]) -> str:
    canonical = "\n".join(sorted(evidence_ids))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
