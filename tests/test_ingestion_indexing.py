"""Tests for versioned embedding identities and repeatable Qdrant operations."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import cast
from uuid import UUID, uuid4

import httpx
import pytest

from research_platform.ingestion.indexing import (
    IndexConfiguration,
    IndexConfigurationMismatch,
    IndexInput,
    IndexPoint,
    IndexState,
    IndexStateStore,
    QdrantIndex,
    VectorEmbedder,
    rebuild_snapshot_index,
)


def _configuration(*, collection_name: str = "phase1-test", vector_size: int = 2):
    return IndexConfiguration(
        collection_name=collection_name,
        embedding_model="pilot-selected-model",
        embedding_revision="revision-1",
        preprocessing_revision="text-normalization-1",
        vector_size=vector_size,
        distance="Cosine",
        batch_size=2,
        maximum_input_tokens=512,
    )


class _QdrantFixture:
    def __init__(self) -> None:
        self.collections: dict[str, dict[str, object]] = {}
        self.points: dict[str, dict[str, dict[str, object]]] = {}

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        pieces = path.strip("/").split("/")
        if len(pieces) < 2 or pieces[0] != "collections":
            return httpx.Response(404)
        name = pieces[1]
        if request.method == "GET" and len(pieces) == 2:
            if name not in self.collections:
                return httpx.Response(404)
            return httpx.Response(
                200,
                json={
                    "result": {
                        "config": {"params": {"vectors": self.collections[name]}}
                    }
                },
            )
        if request.method == "PUT" and len(pieces) == 2:
            body = request.read().decode("utf-8")
            config = json.loads(body)["vectors"]
            self.collections.setdefault(name, config)
            self.points.setdefault(name, {})
            return httpx.Response(200, json={"result": {"status": "ok"}})
        if name not in self.collections:
            return httpx.Response(404)
        body = json.loads(request.read().decode("utf-8"))
        if request.method == "PUT" and pieces[2:] == ["points"]:
            for point in body["points"]:
                self.points[name][point["id"]] = point
            return httpx.Response(200, json={"result": {"status": "acknowledged"}})
        if request.method == "POST" and pieces[2:] == ["points", "count"]:
            snapshot_id = _snapshot_id_from_filter(body["filter"])
            count = sum(
                point["payload"]["snapshot_id"] == snapshot_id
                for point in self.points[name].values()
            )
            return httpx.Response(200, json={"result": {"count": count}})
        if request.method == "POST" and pieces[2:] == ["points", "query"]:
            snapshot_id = _snapshot_id_from_filter(body["filter"])
            matches = [
                {"payload": point["payload"], "score": 0.75}
                for point in self.points[name].values()
                if point["payload"]["snapshot_id"] == snapshot_id
            ][: body["limit"]]
            return httpx.Response(200, json={"result": {"points": matches}})
        if request.method == "POST" and pieces[2:] == ["points", "delete"]:
            snapshot_id = _snapshot_id_from_filter(body["filter"])
            self.points[name] = {
                point_id: point
                for point_id, point in self.points[name].items()
                if point["payload"]["snapshot_id"] != snapshot_id
            }
            return httpx.Response(200, json={"result": {"status": "acknowledged"}})
        if request.method == "POST" and pieces[2:] == ["points", "scroll"]:
            snapshot_id = _snapshot_id_from_filter(body["filter"])
            points = [
                {"payload": {"evidence_id": point["payload"]["evidence_id"]}}
                for point in self.points[name].values()
                if point["payload"]["snapshot_id"] == snapshot_id
            ][: body["limit"]]
            return httpx.Response(
                200, json={"result": {"points": points, "next_page_offset": None}}
            )
        return httpx.Response(404)


def _snapshot_id_from_filter(filter_body: Mapping[str, object]) -> str:
    conditions = cast(list[Mapping[str, object]], filter_body["must"])
    match = cast(Mapping[str, object], conditions[0]["match"])
    return cast(str, match["value"])


def _point(config: IndexConfiguration, snapshot_id: UUID, evidence_id: str):
    return IndexPoint(
        evidence_id=evidence_id,
        vector=(1.0, 0.0),
        payload={
            "snapshot_id": str(snapshot_id),
            "index_configuration_id": config.configuration_id,
            "paper_id": "W123",
            "document_id": str(uuid4()),
            "extraction_id": str(uuid4()),
        },
    )


def test_index_configuration_round_trips_and_identifies_model_inputs() -> None:
    config = _configuration()
    assert IndexConfiguration.from_dict(config.to_dict()) == config
    assert IndexConfiguration.from_dict(config.to_dict()).configuration_id == (
        config.configuration_id
    )

    changed = IndexConfiguration(
        **{**config.__dict__, "embedding_revision": "revision-2"}
    )
    assert changed.configuration_id != config.configuration_id
    with pytest.raises(ValueError, match="fields or version"):
        IndexConfiguration.from_dict({**config.to_dict(), "unknown": True})


def test_qdrant_upsert_is_idempotent_and_queries_only_the_requested_snapshot() -> None:
    fixture = _QdrantFixture()
    config = _configuration()
    first_snapshot = uuid4()
    other_snapshot = uuid4()

    async def exercise() -> None:
        async with httpx.AsyncClient(
            base_url="http://qdrant.test",
            transport=httpx.MockTransport(fixture.handle),
        ) as http:
            index = QdrantIndex(config, http)
            await index.ensure_collection()
            one = _point(config, first_snapshot, "sha256:one")
            other = _point(config, other_snapshot, "sha256:two")
            assert await index.upsert((one, other)) == 2
            assert await index.upsert((one,)) == 1
            assert await index.count_snapshot(first_snapshot) == 1
            assert await index.scroll_snapshot_ids(first_snapshot) == ("sha256:one",)
            matches = await index.query_snapshot((1.0, 0.0), first_snapshot, limit=5)
            assert [match.evidence_id for match in matches] == ["sha256:one"]
            assert matches[0].score == 0.75
            await index.delete_snapshot(first_snapshot)
            assert await index.count_snapshot(first_snapshot) == 0
            assert await index.count_snapshot(other_snapshot) == 1

    import asyncio

    asyncio.run(exercise())


def test_collection_inspection_does_not_create_a_missing_collection() -> None:
    fixture = _QdrantFixture()
    config = _configuration()

    async def exercise() -> None:
        async with httpx.AsyncClient(
            base_url="http://qdrant.test",
            transport=httpx.MockTransport(fixture.handle),
        ) as http:
            index = QdrantIndex(config, http)
            assert not await index.collection_exists()
            assert fixture.collections == {}

    import asyncio

    asyncio.run(exercise())


def test_qdrant_rejects_dimension_mismatch_and_oversized_batches() -> None:
    fixture = _QdrantFixture()
    config = _configuration()
    snapshot_id = uuid4()

    async def exercise() -> None:
        async with httpx.AsyncClient(
            base_url="http://qdrant.test",
            transport=httpx.MockTransport(fixture.handle),
        ) as http:
            index = QdrantIndex(config, http)
            await index.ensure_collection()
            incompatible = QdrantIndex(_configuration(vector_size=3), http)
            with pytest.raises(IndexConfigurationMismatch, match="dimensions"):
                await incompatible.ensure_collection()
            point = _point(config, snapshot_id, "a")
            with pytest.raises(ValueError, match="exactly 2"):
                await index.upsert((IndexPoint("bad", (1.0,), point.payload),))
            with pytest.raises(ValueError, match="batch size"):
                await index.upsert((point, point, point))

    import asyncio

    asyncio.run(exercise())


class _FakeStore(IndexStateStore):
    def __init__(self, inputs: tuple[IndexInput, ...]) -> None:
        self.inputs = inputs
        self.states: list[tuple[IndexState, int, int]] = []

    async def load_snapshot_inputs(
        self, _snapshot_id: UUID, _configuration: IndexConfiguration
    ) -> tuple[IndexInput, ...]:
        return self.inputs

    async def set_index_state(
        self,
        _snapshot_id: UUID,
        _configuration: IndexConfiguration,
        *,
        status: IndexState,
        expected_count: int,
        indexed_count: int,
        details: Mapping[str, object],
    ) -> None:
        self.states.append((status, expected_count, indexed_count))


class _FakeEmbedder(VectorEmbedder):
    def __init__(self, *, return_wrong_count: bool = False) -> None:
        self.batch_sizes: list[int] = []
        self.return_wrong_count = return_wrong_count

    async def embed(
        self, texts: Sequence[str], *, configuration: IndexConfiguration
    ) -> Sequence[Sequence[float]]:
        self.batch_sizes.append(len(texts))
        if self.return_wrong_count:
            return ()
        return tuple((1.0, 0.0) for _ in texts)


def test_rebuild_batches_vectors_and_marks_index_ready() -> None:
    config = _configuration()
    snapshot_id = uuid4()
    store = _FakeStore(
        tuple(
            IndexInput(
                evidence_id=f"sha256:{number}",
                text=f"evidence {number}",
                payload={
                    "snapshot_id": str(snapshot_id),
                    "index_configuration_id": config.configuration_id,
                    "paper_id": "W123",
                    "document_id": str(uuid4()),
                    "extraction_id": str(uuid4()),
                },
            )
            for number in range(3)
        )
    )
    fixture = _QdrantFixture()
    embedder = _FakeEmbedder()

    async def exercise() -> None:
        async with httpx.AsyncClient(
            base_url="http://qdrant.test",
            transport=httpx.MockTransport(fixture.handle),
        ) as http:
            report = await rebuild_snapshot_index(
                store,
                QdrantIndex(config, http),
                embedder,
                snapshot_id,
            )
        assert report.expected_count == report.indexed_count == 3
        assert report.batch_count == 2
        assert embedder.batch_sizes == [2, 1]
        assert store.states[-1] == ("ready", 3, 3)

    import asyncio

    asyncio.run(exercise())


def test_rebuild_marks_reconciliation_required_when_embedding_fails() -> None:
    config = _configuration()
    snapshot_id = uuid4()
    store = _FakeStore(
        (
            IndexInput(
                evidence_id="sha256:one",
                text="some evidence",
                payload={
                    "snapshot_id": str(snapshot_id),
                    "index_configuration_id": config.configuration_id,
                    "paper_id": "W123",
                    "document_id": str(uuid4()),
                    "extraction_id": str(uuid4()),
                },
            ),
        )
    )
    fixture = _QdrantFixture()

    async def exercise() -> None:
        async with httpx.AsyncClient(
            base_url="http://qdrant.test",
            transport=httpx.MockTransport(fixture.handle),
        ) as http:
            with pytest.raises(ValueError, match="different item count"):
                await rebuild_snapshot_index(
                    store,
                    QdrantIndex(config, http),
                    _FakeEmbedder(return_wrong_count=True),
                    snapshot_id,
                )
        assert store.states[-1][0] == "reconciliation_required"

    import asyncio

    asyncio.run(exercise())
