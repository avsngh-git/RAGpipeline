"""Build one generation's passages from a finalized snapshot (P35-06, ADR-0023).

Points carry the evidence text and locator so search can serve content from Qdrant.
Generation N > 1 only adds new evidence and retires removed evidence; existing points
are never rewritten. Verification and publication happen separately (P35-08).
"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Protocol, cast
from uuid import UUID

import asyncpg  # type: ignore[import-untyped]
import httpx

from research_platform.ingestion.generation_index import (
    GenerationIndexConfiguration,
    GenerationPoint,
    GenerationQdrantCollection,
    SparseVector,
    generation_filter,
    passage_point_id,
)
from research_platform.ingestion.generation_registry import GenerationRecord
from research_platform.ingestion.indexing import (
    IndexConfiguration,
    VectorEmbedder,
    _evidence_locator_payload,
    _qdrant_point_id,
)

_RETIRE_BATCH = 1000

_PASSAGE_INPUT_SQL = """
SELECT chunk.id AS evidence_id, chunk.text, paper.id AS paper_id,
       document.id AS document_id, document.version,
       extraction.id AS extraction_id, extraction.source_artifact_id,
       source_file.sha256 AS source_artifact_sha256,
       document.version_kind AS document_version_kind,
       chunk.kind AS evidence_kind,
       paper.publication_year, paper.title,
       section.id AS section_id, section.title AS section_title,
       section.ordinal AS section_ordinal,
       item.chunking_configuration_id,
       chunk.start_offset, chunk.end_offset,
       chunk.source_location AS evidence_source_location,
       chunk.metadata AS evidence_metadata
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
JOIN artifacts AS source_file ON source_file.id = artifact.artifact_id
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
LEFT JOIN sections AS section
  ON section.id = chunk.section_id
 AND section.extraction_id = chunk.extraction_id
WHERE item.snapshot_id = $1
  AND extraction.status IN ('completed', 'partial')
  AND artifact.storage_permitted
  AND artifact.indexing_permitted
  AND permission.storage_permitted
  AND permission.indexing_permitted
ORDER BY chunk.id
"""


@dataclass(frozen=True)
class PassageInput:
    """Selected, permitted evidence text with every payload field except generation tags."""

    evidence_id: str
    text: str
    payload: Mapping[str, object]

    @property
    def text_sha256(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class GenerationBuildReport:
    collection_id: UUID
    configuration_id: str
    generation: int
    snapshot_id: UUID
    added_count: int
    retired_count: int
    reused_vector_count: int
    embedded_count: int
    manifest_sha256: str


class DenseVectorSource(Protocol):
    async def vectors_for(
        self, evidence_ids: Sequence[str]
    ) -> Mapping[str, Sequence[float]]: ...


class SparsePassageEncoder(Protocol):
    async def encode_passages(
        self, texts: Sequence[str]
    ) -> tuple[tuple[SparseVector, tuple[str, ...]], ...]: ...


class GenerationRegistryStore(Protocol):
    def build_lock(
        self, configuration_id: str
    ) -> AbstractAsyncContextManager[None]: ...

    async def register_configuration(
        self, configuration_id: str, configuration: Mapping[str, object]
    ) -> None: ...

    async def register_generation(
        self,
        *,
        collection_id: UUID,
        configuration_id: str,
        snapshot_id: UUID,
        manifest_sha256: str,
    ) -> GenerationRecord: ...

    async def mark_failed(
        self,
        collection_id: UUID,
        configuration_id: str,
        generation: int,
        *,
        reason: str,
    ) -> None: ...


class PassageInputSource(Protocol):
    async def load_passage_inputs(
        self, snapshot_id: UUID
    ) -> tuple[PassageInput, ...]: ...


class GenerationInputRepository:
    """Read a snapshot's selected, permitted evidence with its source locators."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def load_passage_inputs(self, snapshot_id: UUID) -> tuple[PassageInput, ...]:
        async with self._pool.acquire() as connection:
            async with connection.transaction(
                isolation="repeatable_read", readonly=True
            ):
                expected_papers = await connection.fetchval(
                    "SELECT count(*) FROM snapshot_items WHERE snapshot_id = $1",
                    snapshot_id,
                )
                rows = await connection.fetch(_PASSAGE_INPUT_SQL, snapshot_id)
        if expected_papers == 0:
            raise ValueError("cannot build a generation from an empty snapshot")
        if len({row["paper_id"] for row in rows}) != expected_papers:
            raise PermissionError(
                "every snapshot paper must have indexing-permitted evidence"
            )
        return tuple(_passage_input(row) for row in rows)


class QdrantDenseVectorSource:
    """Read stored vectors from a per-snapshot collection with the same dense model."""

    def __init__(
        self,
        http: httpx.AsyncClient,
        *,
        stored: IndexConfiguration,
        expected: IndexConfiguration,
        snapshot_id: UUID,
    ) -> None:
        if (
            stored.embedding_model,
            stored.embedding_revision,
            stored.preprocessing_revision,
            stored.vector_size,
            stored.distance,
            stored.maximum_input_tokens,
        ) != (
            expected.embedding_model,
            expected.embedding_revision,
            expected.preprocessing_revision,
            expected.vector_size,
            expected.distance,
            expected.maximum_input_tokens,
        ):
            raise ValueError("stored vectors use a different dense configuration")
        self._http = http
        self._collection = stored.collection_name
        self._size = stored.vector_size
        self._snapshot_id = str(snapshot_id)

    async def vectors_for(
        self, evidence_ids: Sequence[str]
    ) -> Mapping[str, Sequence[float]]:
        """Return vectors found for ``evidence_ids``; missing ones are omitted."""
        by_point = {
            str(_qdrant_point_id(self._snapshot_id, evidence_id)): evidence_id
            for evidence_id in evidence_ids
        }
        if not by_point:
            return {}
        response = await self._http.post(
            f"/collections/{self._collection}/points",
            json={"ids": list(by_point), "with_payload": False, "with_vector": True},
        )
        response.raise_for_status()
        body = response.json()
        points = body.get("result") if isinstance(body, dict) else None
        if not isinstance(points, list):
            raise RuntimeError("Qdrant returned an invalid retrieve response")
        vectors: dict[str, Sequence[float]] = {}
        for point in points:
            vector = point.get("vector") if isinstance(point, dict) else None
            evidence_id = by_point.get(str(point.get("id")))
            if (
                evidence_id is None
                or not isinstance(vector, list)
                or len(vector) != self._size
            ):
                raise RuntimeError("stored vector does not match its requested point")
            vectors[evidence_id] = [float(value) for value in vector]
        return vectors


def passage_manifest_sha256(inputs: Sequence[PassageInput]) -> str:
    """Order-independent digest of evidence identities and their text hashes."""
    lines = sorted(f"{item.evidence_id}:{item.text_sha256}" for item in inputs)
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def passage_payload(
    item: PassageInput, configuration: GenerationIndexConfiguration, generation: int
) -> dict[str, object]:
    """The full point payload: source fields, content, hashes and generation tag."""
    return {
        **item.payload,
        "evidence_id": item.evidence_id,
        "text": item.text,
        "text_sha256": item.text_sha256,
        "index_configuration_id": configuration.configuration_id,
        "payload_revision": configuration.payload_revision,
        "added_generation": generation,
    }


async def build_generation_passages(
    *,
    registry: GenerationRegistryStore,
    inputs: PassageInputSource,
    passages: GenerationQdrantCollection,
    embedder: VectorEmbedder,
    configuration: GenerationIndexConfiguration,
    collection_id: UUID,
    snapshot_id: UUID,
    vector_source: DenseVectorSource | None = None,
    sparse_encoder: SparsePassageEncoder | None = None,
) -> GenerationBuildReport:
    """Register and fill the next generation; it stays ``building`` until verified."""
    if (configuration.lexical is None) != (sparse_encoder is None):
        raise ValueError(
            "a sparse encoder is required exactly when lexical settings are configured"
        )
    configuration_id = configuration.configuration_id
    await registry.register_configuration(configuration_id, configuration.to_dict())
    async with registry.build_lock(configuration_id):
        loaded = await inputs.load_passage_inputs(snapshot_id)
        record = await registry.register_generation(
            collection_id=collection_id,
            configuration_id=configuration_id,
            snapshot_id=snapshot_id,
            manifest_sha256=passage_manifest_sha256(loaded),
        )
        try:
            return await _fill(
                record,
                loaded,
                passages=passages,
                embedder=embedder,
                configuration=configuration,
                vector_source=vector_source,
                sparse_encoder=sparse_encoder,
            )
        except (Exception, asyncio.CancelledError) as error:
            await registry.mark_failed(
                collection_id,
                configuration_id,
                record.generation,
                reason=type(error).__name__,
            )
            raise


async def _fill(
    record: GenerationRecord,
    loaded: tuple[PassageInput, ...],
    *,
    passages: GenerationQdrantCollection,
    embedder: VectorEmbedder,
    configuration: GenerationIndexConfiguration,
    vector_source: DenseVectorSource | None,
    sparse_encoder: SparsePassageEncoder | None,
) -> GenerationBuildReport:
    generation = record.generation
    await passages.ensure_collection()
    await passages.ensure_payload_indexes()
    by_id = {item.evidence_id: item for item in loaded}
    if len(by_id) != len(loaded):
        raise ValueError("snapshot contains duplicate evidence identities")
    if generation == 1:
        parent_ids: set[str] = set()
    else:
        visible = await passages.scroll_payloads(
            filter_=generation_filter(generation - 1), fields=["evidence_id"]
        )
        parent_ids = {cast(str, payload["evidence_id"]) for payload in visible}
    new_ids = sorted(set(by_id) - parent_ids)
    retired_ids = sorted(parent_ids - set(by_id))

    reused = 0
    embedded = 0
    batch_size = configuration.batch_size
    for start in range(0, len(new_ids), batch_size):
        batch = [
            by_id[evidence_id] for evidence_id in new_ids[start : start + batch_size]
        ]
        vectors = await _vectors(batch, vector_source, embedder, configuration)
        reused += sum(1 for item in batch if vectors[item.evidence_id][1])
        embedded += sum(1 for item in batch if not vectors[item.evidence_id][1])
        sparse = (
            await sparse_encoder.encode_passages([item.text for item in batch])
            if sparse_encoder is not None
            else None
        )
        points = []
        for index, item in enumerate(batch):
            payload = passage_payload(item, configuration, generation)
            vector = None
            if sparse is not None:
                vector, terms = sparse[index]
                payload["lexical_terms"] = list(terms)
            points.append(
                GenerationPoint(
                    point_id=passage_point_id(
                        item.evidence_id, configuration.configuration_id
                    ),
                    dense=vectors[item.evidence_id][0],
                    sparse=vector,
                    payload=payload,
                )
            )
        await passages.upsert(points)
    for start in range(0, len(retired_ids), _RETIRE_BATCH):
        await passages.set_payload(
            [
                passage_point_id(evidence_id, configuration.configuration_id)
                for evidence_id in retired_ids[start : start + _RETIRE_BATCH]
            ],
            {"retired_generation": generation},
        )
    return GenerationBuildReport(
        collection_id=record.collection_id,
        configuration_id=record.configuration_id,
        generation=generation,
        snapshot_id=record.snapshot_id,
        added_count=len(new_ids),
        retired_count=len(retired_ids),
        reused_vector_count=reused,
        embedded_count=embedded,
        manifest_sha256=record.manifest_sha256,
    )


async def _vectors(
    batch: Sequence[PassageInput],
    vector_source: DenseVectorSource | None,
    embedder: VectorEmbedder,
    configuration: GenerationIndexConfiguration,
) -> dict[str, tuple[Sequence[float], bool]]:
    """Map evidence IDs to (vector, reused) using stored vectors where available."""
    found: Mapping[str, Sequence[float]] = {}
    if vector_source is not None:
        found = await vector_source.vectors_for([item.evidence_id for item in batch])
    result = {key: (vector, True) for key, vector in found.items()}
    missing = [item for item in batch if item.evidence_id not in result]
    if missing:
        embedded = await embedder.embed(
            [item.text for item in missing],
            configuration=configuration.dense_configuration(),
        )
        if len(embedded) != len(missing):
            raise ValueError("embedding adapter returned a different item count")
        for item, vector in zip(missing, embedded, strict=True):
            result[item.evidence_id] = (vector, False)
    return result


def _passage_input(row: Mapping[str, object]) -> PassageInput:
    section_id = row["section_id"]
    text = row["text"]
    if not isinstance(text, str):
        raise ValueError("stored evidence text is malformed")
    payload: dict[str, object] = {
        "paper_id": row["paper_id"],
        "document_id": str(row["document_id"]),
        "document_version": row["version"],
        "document_version_kind": row["document_version_kind"],
        "extraction_id": str(row["extraction_id"]),
        "source_artifact_id": str(row["source_artifact_id"]),
        "source_artifact_sha256": row["source_artifact_sha256"],
        "publication_year": row["publication_year"],
        "evidence_kind": row["evidence_kind"],
        "paper_title": row["title"],
        "section_id": None if section_id is None else str(section_id),
        "section_title": row["section_title"],
        "chunking_configuration_id": row["chunking_configuration_id"],
        **_evidence_locator_payload(row),
    }
    return PassageInput(
        evidence_id=cast(str, row["evidence_id"]), text=text, payload=payload
    )
