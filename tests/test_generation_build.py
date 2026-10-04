"""Unit tests for building generation passages (P35-06)."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from typing import Any, cast
from uuid import UUID, uuid4

import pytest

from research_platform.ingestion.generation_build import (
    PassageInput,
    QdrantDenseVectorSource,
    build_generation_passages,
    passage_manifest_sha256,
)
from research_platform.ingestion.generation_index import (
    GenerationIndexConfiguration,
    GenerationPoint,
    GenerationQdrantCollection,
    SparseLexicalSettings,
    passage_point_id,
)
from research_platform.ingestion.generation_registry import GenerationRecord
from research_platform.ingestion.indexing import IndexConfiguration

CONFIGURATION = GenerationIndexConfiguration(
    passages_collection="test-passages",
    papers_collection="test-papers",
    embedding_model="model",
    embedding_revision="revision",
    preprocessing_revision="preprocessing",
    vector_size=2,
    distance="Cosine",
    batch_size=2,
    maximum_input_tokens=512,
)


def _input(evidence_id: str, text: str | None = None) -> PassageInput:
    return PassageInput(
        evidence_id=evidence_id,
        text=text or f"text of {evidence_id}",
        payload={"paper_id": "W1", "evidence_kind": "text", "source_spans": []},
    )


class _Registry:
    def __init__(self) -> None:
        self.generations: list[GenerationRecord] = []
        self.failed: list[tuple[int, str]] = []
        self.configurations: dict[str, Mapping[str, object]] = {}
        self.locked = False

    @asynccontextmanager
    async def build_lock(self, configuration_id: str) -> AsyncIterator[None]:
        self.locked = True
        try:
            yield
        finally:
            self.locked = False

    async def register_configuration(
        self, configuration_id: str, configuration: Mapping[str, object]
    ) -> None:
        self.configurations[configuration_id] = configuration

    async def register_generation(
        self,
        *,
        collection_id: UUID,
        configuration_id: str,
        snapshot_id: UUID,
        manifest_sha256: str,
    ) -> GenerationRecord:
        generation = len(self.generations) + 1
        record = GenerationRecord(
            collection_id=collection_id,
            configuration_id=configuration_id,
            generation=generation,
            snapshot_id=snapshot_id,
            parent_generation=None if generation == 1 else generation - 1,
            manifest_sha256=manifest_sha256,
            state="building",
            point_count=0,
            details={},
        )
        self.generations.append(record)
        return record

    async def mark_failed(
        self,
        collection_id: UUID,
        configuration_id: str,
        generation: int,
        *,
        reason: str,
    ) -> None:
        self.failed.append((generation, reason))


class _Inputs:
    def __init__(self, *snapshots: tuple[PassageInput, ...]) -> None:
        self.snapshots = list(snapshots)

    async def load_passage_inputs(self, snapshot_id: UUID) -> tuple[PassageInput, ...]:
        return self.snapshots.pop(0)


class _Collection:
    def __init__(self, *, fail_upsert: bool = False) -> None:
        self.points: dict[UUID, GenerationPoint] = {}
        self.retired: dict[UUID, int] = {}
        self.fail_upsert = fail_upsert

    async def ensure_collection(self) -> None:
        return None

    async def ensure_payload_indexes(self) -> None:
        return None

    async def upsert(self, points: Sequence[GenerationPoint]) -> int:
        if self.fail_upsert:
            raise RuntimeError("qdrant down")
        assert len(points) <= CONFIGURATION.batch_size
        for point in points:
            self.points[point.point_id] = point
        return len(points)

    async def set_payload(
        self, point_ids: Sequence[UUID], payload: Mapping[str, object]
    ) -> None:
        for point_id in point_ids:
            self.retired[point_id] = cast(int, payload["retired_generation"])

    async def scroll_payloads(
        self, *, filter_: Mapping[str, object], fields: Sequence[str]
    ) -> tuple[Mapping[str, object], ...]:
        generation = cast(Any, filter_)["must"][0]["range"]["lte"]
        return tuple(
            {"evidence_id": point.payload["evidence_id"]}
            for point_id, point in self.points.items()
            if cast(int, point.payload["added_generation"]) <= generation
            and self.retired.get(point_id, generation + 1) > generation
        )


class _Embedder:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    async def embed(
        self, texts: Sequence[str], *, configuration: IndexConfiguration
    ) -> Sequence[Sequence[float]]:
        assert configuration == CONFIGURATION.dense_configuration()
        self.calls.append(list(texts))
        return [(1.0, 0.0) for _ in texts]


class _VectorSource:
    def __init__(self, known: Mapping[str, Sequence[float]]) -> None:
        self.known = known

    async def vectors_for(
        self, evidence_ids: Sequence[str]
    ) -> Mapping[str, Sequence[float]]:
        return {i: self.known[i] for i in evidence_ids if i in self.known}


def _build(
    registry: _Registry,
    inputs: _Inputs,
    collection: _Collection,
    embedder: _Embedder,
    **kwargs: Any,
):
    return asyncio.run(
        build_generation_passages(
            registry=registry,
            inputs=inputs,
            passages=cast(GenerationQdrantCollection, collection),
            embedder=embedder,
            configuration=CONFIGURATION,
            collection_id=uuid4(),
            snapshot_id=uuid4(),
            **kwargs,
        )
    )


def test_generation_one_adds_every_input_with_content_payload() -> None:
    registry, collection, embedder = _Registry(), _Collection(), _Embedder()
    report = _build(
        registry,
        _Inputs((_input("e1"), _input("e2"), _input("e3"))),
        collection,
        embedder,
    )

    assert (report.generation, report.added_count, report.retired_count) == (1, 3, 0)
    assert report.embedded_count == 3
    assert CONFIGURATION.configuration_id in registry.configurations
    point = collection.points[passage_point_id("e2", CONFIGURATION.configuration_id)]
    assert point.payload["text"] == "text of e2"
    assert point.payload["added_generation"] == 1
    assert point.payload["payload_revision"] == CONFIGURATION.payload_revision
    assert point.payload["index_configuration_id"] == CONFIGURATION.configuration_id
    assert point.payload["paper_id"] == "W1"
    assert point.sparse is None
    assert [len(call) for call in embedder.calls] == [2, 1]


def test_text_sha256_matches_text() -> None:
    item = _input("e1", "Évidence ±0.5%")
    assert item.text_sha256 == hashlib.sha256("Évidence ±0.5%".encode()).hexdigest()


def test_later_generation_adds_new_and_retires_removed() -> None:
    registry, collection, embedder = _Registry(), _Collection(), _Embedder()
    inputs = _Inputs((_input("e1"), _input("e2")), (_input("e2"), _input("e3")))
    _build(registry, inputs, collection, embedder)
    report = _build(registry, inputs, collection, embedder)

    assert (report.generation, report.added_count, report.retired_count) == (2, 1, 1)
    e1 = passage_point_id("e1", CONFIGURATION.configuration_id)
    e3 = passage_point_id("e3", CONFIGURATION.configuration_id)
    assert collection.retired == {e1: 2}
    assert collection.points[e3].payload["added_generation"] == 2
    e2 = passage_point_id("e2", CONFIGURATION.configuration_id)
    assert collection.points[e2].payload["added_generation"] == 1


def test_reused_vectors_skip_embedding_and_missing_ones_are_embedded() -> None:
    registry, collection, embedder = _Registry(), _Collection(), _Embedder()
    source = _VectorSource({"e1": (0.0, 1.0), "e3": (0.6, 0.8)})
    report = _build(
        registry,
        _Inputs((_input("e1"), _input("e2"), _input("e3"))),
        collection,
        embedder,
        vector_source=source,
    )

    assert (report.reused_vector_count, report.embedded_count) == (2, 1)
    assert embedder.calls == [["text of e2"]]
    e1 = passage_point_id("e1", CONFIGURATION.configuration_id)
    assert tuple(collection.points[e1].dense) == (0.0, 1.0)


def test_vector_source_rejects_different_dense_configuration() -> None:
    other = IndexConfiguration(
        collection_name="other",
        embedding_model="model",
        embedding_revision="other-revision",
        preprocessing_revision="preprocessing",
        vector_size=2,
        distance="Cosine",
        batch_size=2,
        maximum_input_tokens=512,
    )
    with pytest.raises(ValueError, match="different dense configuration"):
        QdrantDenseVectorSource(
            cast(Any, None),
            stored=other,
            expected=CONFIGURATION.dense_configuration(),
            snapshot_id=uuid4(),
        )


def test_failure_marks_generation_failed() -> None:
    registry = _Registry()
    with pytest.raises(RuntimeError, match="qdrant down"):
        _build(
            registry,
            _Inputs((_input("e1"),)),
            _Collection(fail_upsert=True),
            _Embedder(),
        )
    assert registry.failed == [(1, "RuntimeError")]
    assert not registry.locked


def test_manifest_digest_is_order_independent() -> None:
    first = passage_manifest_sha256([_input("e1"), _input("e2")])
    assert first == passage_manifest_sha256([_input("e2"), _input("e1")])
    assert first != passage_manifest_sha256([_input("e1"), _input("e2", "changed")])


def test_lexical_configuration_requires_encoder() -> None:
    lexical = GenerationIndexConfiguration(
        **{
            **CONFIGURATION.__dict__,
            "lexical": SparseLexicalSettings(
                "scientific-en", "v1", "vocab", 1.5, 0.75, 3.0, 3.0
            ),
        }
    )
    with pytest.raises(ValueError, match="sparse encoder is required"):
        asyncio.run(
            build_generation_passages(
                registry=_Registry(),
                inputs=_Inputs((_input("e1"),)),
                passages=cast(GenerationQdrantCollection, _Collection()),
                embedder=_Embedder(),
                configuration=lexical,
                collection_id=uuid4(),
                snapshot_id=uuid4(),
            )
        )
