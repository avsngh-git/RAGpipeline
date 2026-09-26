"""Tests for versioned embedding identities and repeatable Qdrant operations."""

from __future__ import annotations

import asyncio
import json
import math
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from typing import cast
from uuid import UUID, uuid4

import httpx
import pytest

from research_platform.ingestion.embeddings import (
    BGEBaseEnV15Embedder,
    E5SmallV2Embedder,
)
from research_platform.ingestion.indexing import (
    DENSE_FILTER_PAYLOAD_REVISION,
    IndexConfiguration,
    IndexConfigurationMismatch,
    IndexInput,
    IndexPoint,
    IndexReconciliationRequired,
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
        self.payload_indexes: dict[str, dict[str, str]] = {}
        self.omit_payload_fields: set[str] = set()

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
        if request.method == "PUT" and pieces[2:] == ["index"]:
            self.payload_indexes.setdefault(name, {})[body["field_name"]] = body[
                "field_schema"
            ]
            return httpx.Response(200, json={"result": {"status": "ok"}})
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
            query = cast(list[float], body["query"])
            filter_body = cast(Mapping[str, object], body["filter"])
            scored = []
            for point in self.points[name].values():
                if not _payload_matches_filter(point["payload"], filter_body):
                    continue
                vector = cast(list[float], point["vector"])
                dot = sum(left * right for left, right in zip(query, vector))
                query_norm = math.sqrt(sum(value * value for value in query))
                vector_norm = math.sqrt(sum(value * value for value in vector))
                score = dot / (query_norm * vector_norm)
                scored.append((score, point["payload"]["evidence_id"], point))
            scored.sort(key=lambda item: (-item[0], item[1]))
            matches = [
                {"payload": point["payload"], "score": score}
                for score, _evidence_id, point in scored[: body["limit"]]
            ]
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
            fields = cast(list[str], body["with_payload"])
            points = [
                {
                    "payload": {
                        field: point["payload"][field]
                        for field in fields
                        if field in point["payload"]
                        and field not in self.omit_payload_fields
                    }
                }
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


def _payload_matches_filter(
    payload: Mapping[str, object], filter_body: Mapping[str, object]
) -> bool:
    conditions = cast(Sequence[Mapping[str, object]], filter_body["must"])
    for condition in conditions:
        key = cast(str, condition["key"])
        actual = payload.get(key)
        match = condition.get("match")
        value_range = condition.get("range")
        if isinstance(match, Mapping):
            if "value" in match and actual != match["value"]:
                return False
            if "any" in match and actual not in cast(Sequence[object], match["any"]):
                return False
        elif isinstance(value_range, Mapping):
            if not isinstance(actual, (int, float)) or isinstance(actual, bool):
                return False
            lower = value_range.get("gte")
            upper = value_range.get("lte")
            if isinstance(lower, (int, float)) and actual < lower:
                return False
            if isinstance(upper, (int, float)) and actual > upper:
                return False
    return True


def _point(config: IndexConfiguration, snapshot_id: UUID, evidence_id: str):
    return IndexPoint(
        evidence_id=evidence_id,
        vector=(1.0, 0.0),
        payload={
            "snapshot_id": str(snapshot_id),
            "index_configuration_id": config.configuration_id,
            "paper_id": "W123",
            "publication_year": 2024,
            "evidence_kind": "text",
            "document_version_kind": "published",
            "filter_payload_revision": DENSE_FILTER_PAYLOAD_REVISION,
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
            assert matches[0].score == 1.0
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
        self.state_details: list[Mapping[str, object]] = []
        self._build_gate = asyncio.Lock()
        self.active_builds = 0
        self.maximum_active_builds = 0

    @asynccontextmanager
    async def build_lock(
        self, _configuration: IndexConfiguration
    ) -> AsyncIterator[None]:
        async with self._build_gate:
            self.active_builds += 1
            self.maximum_active_builds = max(
                self.maximum_active_builds, self.active_builds
            )
            try:
                yield
            finally:
                self.active_builds -= 1

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
        self.state_details.append(dict(details))


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
                    "publication_year": 2024,
                    "evidence_kind": "text",
                    "document_version_kind": "published",
                    "filter_payload_revision": DENSE_FILTER_PAYLOAD_REVISION,
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
                    "publication_year": 2024,
                    "evidence_kind": "text",
                    "document_version_kind": "published",
                    "filter_payload_revision": DENSE_FILTER_PAYLOAD_REVISION,
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


def test_rebuilds_sharing_a_configuration_are_serialized() -> None:
    config = _configuration()
    snapshot_id = uuid4()
    inputs = tuple(
        IndexInput(
            evidence_id=f"sha256:{number}",
            text=f"evidence {number}",
            payload={
                "snapshot_id": str(snapshot_id),
                "index_configuration_id": config.configuration_id,
                "paper_id": "W123",
                "publication_year": 2024,
                "evidence_kind": "text",
                "document_version_kind": "published",
                "filter_payload_revision": DENSE_FILTER_PAYLOAD_REVISION,
                "document_id": str(uuid4()),
                "extraction_id": str(uuid4()),
            },
        )
        for number in range(3)
    )
    store = _FakeStore(inputs)
    fixture = _QdrantFixture()

    class YieldingEmbedder(_FakeEmbedder):
        async def embed(
            self, texts: Sequence[str], *, configuration: IndexConfiguration
        ) -> Sequence[Sequence[float]]:
            await asyncio.sleep(0.001)
            return await super().embed(texts, configuration=configuration)

    async def exercise() -> None:
        async with httpx.AsyncClient(
            base_url="http://qdrant.test",
            transport=httpx.MockTransport(fixture.handle),
        ) as http:
            index = QdrantIndex(config, http)
            reports = await asyncio.gather(
                rebuild_snapshot_index(store, index, YieldingEmbedder(), snapshot_id),
                rebuild_snapshot_index(store, index, YieldingEmbedder(), snapshot_id),
            )
        assert [report.indexed_count for report in reports] == [3, 3]
        assert store.maximum_active_builds == 1
        assert [status for status, _, _ in store.states] == [
            "building",
            "ready",
            "building",
            "ready",
        ]

    asyncio.run(exercise())


def test_cancelled_rebuild_is_not_published_as_ready() -> None:
    config = _configuration()
    snapshot_id = uuid4()
    store = _FakeStore(
        (
            IndexInput(
                evidence_id="sha256:cancelled",
                text="some evidence",
                payload={
                    "snapshot_id": str(snapshot_id),
                    "index_configuration_id": config.configuration_id,
                    "paper_id": "W123",
                    "publication_year": 2024,
                    "evidence_kind": "text",
                    "document_version_kind": "published",
                    "filter_payload_revision": DENSE_FILTER_PAYLOAD_REVISION,
                    "document_id": str(uuid4()),
                    "extraction_id": str(uuid4()),
                },
            ),
        )
    )
    fixture = _QdrantFixture()

    class CancellingEmbedder(VectorEmbedder):
        async def embed(
            self,
            _texts: Sequence[str],
            *,
            configuration: IndexConfiguration,
        ) -> Sequence[Sequence[float]]:
            raise asyncio.CancelledError

    async def exercise() -> None:
        async with httpx.AsyncClient(
            base_url="http://qdrant.test",
            transport=httpx.MockTransport(fixture.handle),
        ) as http:
            with pytest.raises(asyncio.CancelledError):
                await rebuild_snapshot_index(
                    store,
                    QdrantIndex(config, http),
                    CancellingEmbedder(),
                    snapshot_id,
                )
        assert [status for status, _, _ in store.states] == [
            "building",
            "reconciliation_required",
        ]

    asyncio.run(exercise())


def test_bge_index_is_separate_reconciled_reloadable_and_rebuildable() -> None:
    snapshot_id = uuid4()
    e5_configuration = E5SmallV2Embedder.index_configuration(
        collection_name="phase1-e5-lifecycle-fixture"
    )
    bge_configuration = BGEBaseEnV15Embedder.index_configuration(
        collection_name="phase2-bge-lifecycle-fixture"
    )
    evidence_ids = ("sha256:alpha", "sha256:near-alpha", "sha256:beta")
    inputs = tuple(
        IndexInput(
            evidence_id=evidence_id,
            text=text,
            payload={
                "snapshot_id": str(snapshot_id),
                "index_configuration_id": bge_configuration.configuration_id,
                "paper_id": "W123",
                "publication_year": 2024,
                "evidence_kind": (
                    "table_row_group"
                    if text == "near alpha"
                    else "table"
                    if text == "beta only"
                    else "text"
                ),
                "document_version_kind": "published",
                "filter_payload_revision": DENSE_FILTER_PAYLOAD_REVISION,
                "document_id": str(uuid4()),
                "extraction_id": str(uuid4()),
            },
        )
        for evidence_id, text in zip(
            evidence_ids,
            ("alpha target", "near alpha", "beta only"),
            strict=True,
        )
    )
    store = _FakeStore(inputs)
    fixture = _QdrantFixture()

    class _SyntheticBGEEmbedder(VectorEmbedder):
        async def embed(
            self, texts: Sequence[str], *, configuration: IndexConfiguration
        ) -> Sequence[Sequence[float]]:
            vectors: list[tuple[float, ...]] = []
            for text in texts:
                vector = [0.0] * configuration.vector_size
                if text == "alpha target":
                    vector[0] = 1.0
                elif text == "near alpha":
                    vector[0], vector[1] = 0.8, 0.6
                elif text == "beta only":
                    vector[1] = 1.0
                else:
                    raise AssertionError("unexpected synthetic passage")
                vectors.append(tuple(vector))
            return tuple(vectors)

    async def exercise() -> None:
        async with httpx.AsyncClient(
            base_url="http://qdrant.test",
            transport=httpx.MockTransport(fixture.handle),
        ) as http:
            e5_index = QdrantIndex(e5_configuration, http)
            await e5_index.ensure_collection()
            await e5_index.upsert(
                (
                    IndexPoint(
                        evidence_id="sha256:retained-e5",
                        vector=(1.0,) + (0.0,) * 383,
                        payload={
                            "snapshot_id": str(snapshot_id),
                            "index_configuration_id": e5_configuration.configuration_id,
                            "paper_id": "W123",
                            "publication_year": 2024,
                            "evidence_kind": "text",
                            "document_version_kind": "published",
                            "filter_payload_revision": DENSE_FILTER_PAYLOAD_REVISION,
                            "document_id": str(uuid4()),
                            "extraction_id": str(uuid4()),
                        },
                    ),
                )
            )

            bge_index = QdrantIndex(bge_configuration, http)
            for _ in range(2):
                report = await rebuild_snapshot_index(
                    store, bge_index, _SyntheticBGEEmbedder(), snapshot_id
                )
                assert report.configuration_id == bge_configuration.configuration_id
                assert report.expected_count == report.indexed_count == 3
                assert fixture.collections[bge_configuration.collection_name] == {
                    "size": 768,
                    "distance": "Cosine",
                }
                assert fixture.payload_indexes[bge_configuration.collection_name] == {
                    "filter_payload_revision": "keyword",
                    "paper_id": "keyword",
                    "publication_year": "integer",
                    "evidence_kind": "keyword",
                    "document_version_kind": "keyword",
                }
                assert await bge_index.count_snapshot(snapshot_id) == 3
                assert set(await bge_index.scroll_snapshot_ids(snapshot_id)) == set(
                    evidence_ids
                )
                assert store.states[-1] == ("ready", 3, 3)
                ready_details = store.state_details[-1]
                assert (
                    ready_details["evidence_ids_sha256"]
                    == ready_details["qdrant_evidence_ids_sha256"]
                )
                assert (
                    ready_details["filter_payload_revision"]
                    == DENSE_FILTER_PAYLOAD_REVISION
                )
                matches = await bge_index.query_snapshot(
                    (1.0,) + (0.0,) * 767, snapshot_id, limit=3
                )
                assert [match.evidence_id for match in matches] == [
                    "sha256:alpha",
                    "sha256:near-alpha",
                    "sha256:beta",
                ]
                filtered_matches = await bge_index.query_snapshot(
                    (1.0,) + (0.0,) * 767,
                    snapshot_id,
                    limit=1,
                    payload_conditions=(
                        {
                            "key": "filter_payload_revision",
                            "match": {"value": DENSE_FILTER_PAYLOAD_REVISION},
                        },
                        {
                            "key": "evidence_kind",
                            "match": {"any": ["table", "table_row_group"]},
                        },
                    ),
                )
                assert [match.evidence_id for match in filtered_matches] == [
                    "sha256:near-alpha"
                ]
                assert matches[0].payload["index_configuration_id"] == (
                    bge_configuration.configuration_id
                )
                assert await e5_index.count_snapshot(snapshot_id) == 1

            reloaded_bge_index = QdrantIndex(bge_configuration, http)
            assert await reloaded_bge_index.collection_exists()
            await reloaded_bge_index.ensure_collection()
            reloaded_matches = await reloaded_bge_index.query_snapshot(
                (1.0,) + (0.0,) * 767, snapshot_id, limit=1
            )
            assert reloaded_matches[0].evidence_id == "sha256:alpha"
            assert fixture.collections[e5_configuration.collection_name] == {
                "size": 384,
                "distance": "Cosine",
            }
            assert [state for state, _, _ in store.states] == [
                "building",
                "ready",
                "building",
                "ready",
            ]

    asyncio.run(exercise())


def test_rebuild_does_not_publish_when_qdrant_filter_payload_is_incomplete() -> None:
    config = _configuration()
    snapshot_id = uuid4()
    store = _FakeStore(
        (
            IndexInput(
                evidence_id="sha256:missing-filter-field",
                text="source evidence",
                payload={
                    "snapshot_id": str(snapshot_id),
                    "index_configuration_id": config.configuration_id,
                    "paper_id": "W123",
                    "publication_year": 2024,
                    "evidence_kind": "table",
                    "document_version_kind": "published",
                    "filter_payload_revision": DENSE_FILTER_PAYLOAD_REVISION,
                    "document_id": str(uuid4()),
                    "extraction_id": str(uuid4()),
                },
            ),
        )
    )
    fixture = _QdrantFixture()
    fixture.omit_payload_fields.add("evidence_kind")

    async def exercise() -> None:
        async with httpx.AsyncClient(
            base_url="http://qdrant.test",
            transport=httpx.MockTransport(fixture.handle),
        ) as http:
            with pytest.raises(IndexReconciliationRequired, match="filter payloads"):
                await rebuild_snapshot_index(
                    store, QdrantIndex(config, http), _FakeEmbedder(), snapshot_id
                )
        assert [status for status, _, _ in store.states] == [
            "building",
            "reconciliation_required",
        ]

    asyncio.run(exercise())


@pytest.mark.parametrize("model_name", ["e5", "bge"])
def test_each_pinned_embedding_space_filters_before_top_k(model_name: str) -> None:
    snapshot_id = uuid4()
    if model_name == "e5":
        configuration = E5SmallV2Embedder.index_configuration(
            collection_name="phase2-e5-filter-neighbor-fixture"
        )
    else:
        configuration = BGEBaseEnV15Embedder.index_configuration(
            collection_name="phase2-bge-filter-neighbor-fixture"
        )
    evidence_ids = ("sha256:alpha", "sha256:near-alpha", "sha256:beta")
    inputs = tuple(
        IndexInput(
            evidence_id=evidence_id,
            text=text,
            payload={
                "snapshot_id": str(snapshot_id),
                "index_configuration_id": configuration.configuration_id,
                "paper_id": "W123",
                "publication_year": 2024 if text != "beta only" else 2018,
                "evidence_kind": (
                    "table_row_group"
                    if text == "near alpha"
                    else "table"
                    if text == "beta only"
                    else "text"
                ),
                "document_version_kind": "published",
                "filter_payload_revision": DENSE_FILTER_PAYLOAD_REVISION,
                "document_id": str(uuid4()),
                "extraction_id": str(uuid4()),
            },
        )
        for evidence_id, text in zip(
            evidence_ids,
            ("alpha target", "near alpha", "beta only"),
            strict=True,
        )
    )
    store = _FakeStore(inputs)
    fixture = _QdrantFixture()

    class _DirectionalEmbedder(VectorEmbedder):
        async def embed(
            self, texts: Sequence[str], *, configuration: IndexConfiguration
        ) -> Sequence[Sequence[float]]:
            vectors: list[tuple[float, ...]] = []
            for text in texts:
                vector = [0.0] * configuration.vector_size
                if text == "alpha target":
                    vector[0] = 1.0
                elif text == "near alpha":
                    vector[0], vector[1] = 0.8, 0.6
                elif text == "beta only":
                    vector[1] = 1.0
                vectors.append(tuple(vector))
            return tuple(vectors)

    async def exercise() -> None:
        async with httpx.AsyncClient(
            base_url="http://qdrant.test",
            transport=httpx.MockTransport(fixture.handle),
        ) as http:
            index = QdrantIndex(configuration, http)
            await rebuild_snapshot_index(
                store, index, _DirectionalEmbedder(), snapshot_id
            )
            matches = await index.query_snapshot(
                (1.0,) + (0.0,) * (configuration.vector_size - 1),
                snapshot_id,
                limit=1,
                payload_conditions=(
                    {
                        "key": "filter_payload_revision",
                        "match": {"value": DENSE_FILTER_PAYLOAD_REVISION},
                    },
                    {"key": "publication_year", "range": {"gte": 2020}},
                    {
                        "key": "evidence_kind",
                        "match": {"any": ["table", "table_row_group"]},
                    },
                ),
            )
        assert [match.evidence_id for match in matches] == ["sha256:near-alpha"]

    asyncio.run(exercise())
