"""Profile binding and serving/evaluation boundaries for dense search."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from uuid import UUID

import httpx
import pytest

from research_platform.ingestion.embeddings import E5SmallV2Embedder
from research_platform.ingestion.indexing import (
    IndexConfiguration,
    IndexInput,
    IndexMatch,
    QdrantIndex,
    ReadySnapshotIndex,
)
from research_platform.ingestion.snapshot_selection import SnapshotSelection
from research_platform.search.dense_search import (
    ProfileDenseIndexMismatch,
    SnapshotDenseSearch,
    UnsupportedRetrievalProfile,
)
from research_platform.search.profiles import (
    CandidateLimits,
    DenseIndexIdentity,
    LexicalIndexIdentity,
    RetrievalProfile,
)

SNAPSHOT_ID = UUID("f1336240-dda0-45fb-a5b1-ff399bd93436")
SNAPSHOT_CONFIG_ID = "sha256:" + "a" * 64
CHUNK_SELECTION_ID = "sha256:" + "b" * 64


class _Gate:
    def __init__(self, snapshot_status: str = "finalized") -> None:
        self.snapshot_status = snapshot_status
        self.serving_calls = 0
        self.evaluation_calls = 0

    @asynccontextmanager
    async def serving_index(
        self,
        snapshot_selection: SnapshotSelection,
        configuration: IndexConfiguration,
    ) -> AsyncIterator[ReadySnapshotIndex]:
        self.serving_calls += 1
        yield ReadySnapshotIndex(
            snapshot_status="finalized",
            snapshot_selection=snapshot_selection,
            configuration_id=configuration.configuration_id,
            collection_name=configuration.collection_name,
            expected_count=1,
        )

    @asynccontextmanager
    async def evaluation_index(
        self,
        snapshot_selection: SnapshotSelection,
        configuration: IndexConfiguration,
    ) -> AsyncIterator[ReadySnapshotIndex]:
        self.evaluation_calls += 1
        yield ReadySnapshotIndex(
            snapshot_status=self.snapshot_status,  # type: ignore[arg-type]
            snapshot_selection=snapshot_selection,
            configuration_id=configuration.configuration_id,
            collection_name=configuration.collection_name,
            expected_count=1,
        )


def _configuration() -> IndexConfiguration:
    return IndexConfiguration(
        collection_name="dense-profile-test",
        embedding_model="e5-small-v2",
        embedding_revision="revision-1",
        preprocessing_revision="query-passage-prefix-v1",
        vector_size=2,
        distance="Cosine",
        batch_size=2,
        maximum_input_tokens=512,
    )


def _profile(
    configuration: IndexConfiguration,
    *,
    dense_identity: DenseIndexIdentity | None = None,
    lexical: bool = False,
) -> RetrievalProfile:
    snapshot = SnapshotSelection(
        snapshot_id=SNAPSHOT_ID,
        snapshot_configuration_id=SNAPSHOT_CONFIG_ID,
        chunk_selection_id=CHUNK_SELECTION_ID,
    )
    identity = dense_identity or DenseIndexIdentity(
        model=configuration.embedding_model,
        revision=configuration.embedding_revision,
        preprocessing_revision=configuration.preprocessing_revision,
        dimensions=configuration.vector_size,
        maximum_input_tokens=configuration.maximum_input_tokens,
        index_configuration_id=configuration.configuration_id,
    )
    lexical_identity = (
        LexicalIndexIdentity(
            implementation="bm25-candidate",
            implementation_revision="0.1",
            analyzer="english",
            analyzer_revision="1",
            normalization_revision="1",
            index_format_revision="1",
        )
        if lexical
        else None
    )
    return RetrievalProfile(
        snapshot=snapshot,
        lexical_index=lexical_identity,
        dense_index=identity,
        candidate_limits=CandidateLimits(
            lexical_top_k=10 if lexical else None,
            dense_top_k=10,
            fused_top_k=None,
            rerank_top_k=None,
        ),
    )


def test_dense_search_is_bound_to_the_requested_profile() -> None:
    configuration = _configuration()
    gate = _Gate()
    fixture_points = {
        "payload": {
            "snapshot_id": str(SNAPSHOT_ID),
            "index_configuration_id": configuration.configuration_id,
            "evidence_id": "sha256:" + "c" * 64,
        },
        "score": 0.75,
    }

    def respond(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path.endswith("/points/query"):
            return httpx.Response(200, json={"result": {"points": [fixture_points]}})
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "result": {
                        "config": {
                            "params": {
                                "vectors": {
                                    "size": 2,
                                    "distance": "Cosine",
                                }
                            }
                        }
                    }
                },
            )
        return httpx.Response(200, json={"result": {"points": []}})

    async def exercise() -> None:
        async with httpx.AsyncClient(
            base_url="http://qdrant.test", transport=httpx.MockTransport(respond)
        ) as http:
            service = SnapshotDenseSearch(gate, QdrantIndex(configuration, http))
            result = await service.search(_profile(configuration), (1.0, 0.0), limit=5)
        assert gate.serving_calls == 1
        assert gate.evaluation_calls == 0
        assert result.snapshot_id == SNAPSHOT_ID
        assert result.profile_id == _profile(configuration).profile_id
        assert result.hits[0].evidence_id == "sha256:" + "c" * 64

    asyncio.run(exercise())


def test_dense_search_rejects_a_profile_with_unavailable_stages() -> None:
    configuration = _configuration()
    gate = _Gate()

    async def exercise() -> None:
        async with httpx.AsyncClient(
            base_url="http://qdrant.test",
            transport=httpx.MockTransport(lambda _request: httpx.Response(200)),
        ) as http:
            service = SnapshotDenseSearch(gate, QdrantIndex(configuration, http))
            with pytest.raises(UnsupportedRetrievalProfile, match="lexical"):
                await service.search(
                    _profile(configuration, lexical=True), (1.0, 0.0), limit=5
                )
        assert gate.serving_calls == 0

    asyncio.run(exercise())


def test_dense_search_rejects_mismatched_dense_identity_before_query() -> None:
    configuration = _configuration()
    gate = _Gate()
    mismatched = DenseIndexIdentity(
        model=configuration.embedding_model,
        revision="different-revision",
        preprocessing_revision=configuration.preprocessing_revision,
        dimensions=configuration.vector_size,
        maximum_input_tokens=configuration.maximum_input_tokens,
        index_configuration_id=configuration.configuration_id,
    )

    async def exercise() -> None:
        async with httpx.AsyncClient(
            base_url="http://qdrant.test",
            transport=httpx.MockTransport(lambda _request: httpx.Response(200)),
        ) as http:
            service = SnapshotDenseSearch(gate, QdrantIndex(configuration, http))
            with pytest.raises(ProfileDenseIndexMismatch, match="does not match"):
                await service.search(
                    _profile(configuration, dense_identity=mismatched),
                    (1.0, 0.0),
                    limit=5,
                )
        assert gate.serving_calls == 0

    asyncio.run(exercise())


def test_evaluation_uses_the_explicit_draft_path() -> None:
    configuration = _configuration()
    gate = _Gate(snapshot_status="draft")

    async def exercise() -> None:
        async with httpx.AsyncClient(
            base_url="http://qdrant.test",
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    json={"result": {"points": []}}
                    if request.method == "POST"
                    else {
                        "result": {
                            "config": {
                                "params": {
                                    "vectors": {
                                        "size": 2,
                                        "distance": "Cosine",
                                    }
                                }
                            }
                        }
                    },
                )
            ),
        ) as http:
            service = SnapshotDenseSearch(gate, QdrantIndex(configuration, http))
            await service.evaluate(_profile(configuration), (1.0, 0.0), limit=5)
        assert gate.serving_calls == 0
        assert gate.evaluation_calls == 1

    asyncio.run(exercise())


class _QueryEmbedder:
    def __init__(self, vector: tuple[float, ...]) -> None:
        self.vector = vector
        self.calls: list[tuple[str, IndexConfiguration]] = []

    async def embed_query(
        self, text: str, *, configuration: IndexConfiguration
    ) -> tuple[float, ...]:
        self.calls.append((text, configuration))
        return self.vector


class _Hydrator:
    def __init__(self, gate: _Gate) -> None:
        self.gate = gate
        self.calls: list[tuple[SnapshotSelection, tuple[IndexMatch, ...]]] = []
        self.allow_draft_calls: list[bool] = []

    async def hydrate_snapshot_matches(
        self,
        snapshot_selection: SnapshotSelection,
        configuration: IndexConfiguration,
        matches: Sequence[IndexMatch],
        *,
        allow_draft: bool = False,
    ) -> tuple[IndexInput, ...]:
        if allow_draft:
            assert self.gate.evaluation_calls == 1
        else:
            assert self.gate.serving_calls == 1
        self.calls.append((snapshot_selection, tuple(matches)))
        self.allow_draft_calls.append(allow_draft)
        return tuple(
            IndexInput(
                evidence_id=match.evidence_id,
                text="authoritative database source text",
                payload={
                    "snapshot_id": str(snapshot_selection.snapshot_id),
                    "index_configuration_id": configuration.configuration_id,
                    "paper_id": "W123",
                    "document_id": str(UUID(int=1)),
                    "document_version": "published",
                    "extraction_id": str(UUID(int=2)),
                    "source_artifact_id": str(UUID(int=3)),
                    "source_artifact_sha256": "sha256:" + "d" * 64,
                    "publication_year": 2024,
                    "paper_title": "Fixture paper",
                    "section_id": None,
                    "section_title": "Results",
                },
            )
            for match in matches
        )


def _e5_configuration() -> IndexConfiguration:
    return E5SmallV2Embedder.index_configuration(
        collection_name="dense-e5-query-test", batch_size=2
    )


def test_e5_query_search_hydrates_ranked_hits_from_the_authoritative_source() -> None:
    configuration = _e5_configuration()
    gate = _Gate()
    evidence_id = "sha256:" + "c" * 64
    fixture_point = {
        "payload": {
            "snapshot_id": str(SNAPSHOT_ID),
            "index_configuration_id": configuration.configuration_id,
            "evidence_id": evidence_id,
            "text": "stale vector payload text",
        },
        "score": 0.875,
    }
    requests: list[dict[str, object]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path.endswith("/points/query"):
            requests.append(json.loads(request.content))
            return httpx.Response(200, json={"result": {"points": [fixture_point]}})
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "result": {
                        "config": {
                            "params": {"vectors": {"size": 384, "distance": "Cosine"}}
                        }
                    }
                },
            )
        return httpx.Response(200, json={"result": {"points": []}})

    async def exercise() -> None:
        embedder = _QueryEmbedder((1.0,) + (0.0,) * 383)
        hydrator = _Hydrator(gate)
        async with httpx.AsyncClient(
            base_url="http://qdrant.test", transport=httpx.MockTransport(respond)
        ) as http:
            service = SnapshotDenseSearch(
                gate,
                QdrantIndex(configuration, http),
                query_embedder=embedder,
                evidence_hydrator=hydrator,
            )
            result = await service.search_query(
                _profile(configuration), "retrieval query", limit=5
            )
        assert embedder.calls == [("retrieval query", configuration)]
        assert gate.serving_calls == 1
        assert gate.evaluation_calls == 0
        assert requests[0]["query"] == [1.0] + [0.0] * 383
        assert requests[0]["filter"] == {
            "must": [{"key": "snapshot_id", "match": {"value": str(SNAPSHOT_ID)}}]
        }
        assert len(hydrator.calls) == 1
        assert result.hits[0].evidence_id == evidence_id
        assert result.hydrated_hits[0].rank == 1
        assert result.hydrated_hits[0].score == 0.875
        assert result.hydrated_hits[0].evidence.text == (
            "authoritative database source text"
        )
        assert result.hydrated_hits[0].evidence.payload["source_artifact_sha256"] == (
            "sha256:" + "d" * 64
        )

    asyncio.run(exercise())


@pytest.mark.parametrize(
    ("vector", "message"),
    [
        ((1.0,), "exactly 384"),
        ((0.0,) * 384, "L2-normalized"),
        ((float("nan"),) + (0.0,) * 383, "finite numbers"),
    ],
)
def test_e5_query_search_rejects_invalid_vectors_before_qdrant(
    vector: tuple[float, ...], message: str
) -> None:
    configuration = _e5_configuration()
    gate = _Gate()

    async def exercise() -> None:
        async with httpx.AsyncClient(
            base_url="http://qdrant.test",
            transport=httpx.MockTransport(
                lambda _request: pytest.fail("invalid vectors must fail before Qdrant")
            ),
        ) as http:
            service = SnapshotDenseSearch(
                gate,
                QdrantIndex(configuration, http),
                query_embedder=_QueryEmbedder(vector),
                evidence_hydrator=_Hydrator(gate),
            )
            with pytest.raises(ValueError, match=message):
                await service.search_query(
                    _profile(configuration), "retrieval query", limit=5
                )
        assert gate.serving_calls == 0

    asyncio.run(exercise())


def test_e5_query_search_rejects_non_e5_index_configuration_before_embedding() -> None:
    configuration = _configuration()
    gate = _Gate()
    embedder = _QueryEmbedder((1.0, 0.0))

    async def exercise() -> None:
        async with httpx.AsyncClient(
            base_url="http://qdrant.test",
            transport=httpx.MockTransport(
                lambda _request: pytest.fail(
                    "mismatched config must fail before Qdrant"
                )
            ),
        ) as http:
            service = SnapshotDenseSearch(
                gate,
                QdrantIndex(configuration, http),
                query_embedder=embedder,
                evidence_hydrator=_Hydrator(gate),
            )
            with pytest.raises(ProfileDenseIndexMismatch, match="pinned E5"):
                await service.search_query(
                    _profile(configuration), "retrieval query", limit=5
                )
        assert embedder.calls == []
        assert gate.serving_calls == 0

    asyncio.run(exercise())


def test_e5_query_search_checks_profile_identity_before_embedding() -> None:
    configuration = _e5_configuration()
    gate = _Gate()
    embedder = _QueryEmbedder((1.0,) + (0.0,) * 383)
    mismatched = DenseIndexIdentity(
        model=configuration.embedding_model,
        revision="different-revision",
        preprocessing_revision=configuration.preprocessing_revision,
        dimensions=configuration.vector_size,
        maximum_input_tokens=configuration.maximum_input_tokens,
        index_configuration_id=configuration.configuration_id,
    )

    async def exercise() -> None:
        async with httpx.AsyncClient(
            base_url="http://qdrant.test",
            transport=httpx.MockTransport(
                lambda _request: pytest.fail(
                    "mismatched profile must fail before Qdrant"
                )
            ),
        ) as http:
            service = SnapshotDenseSearch(
                gate,
                QdrantIndex(configuration, http),
                query_embedder=embedder,
                evidence_hydrator=_Hydrator(gate),
            )
            with pytest.raises(ProfileDenseIndexMismatch, match="does not match"):
                await service.search_query(
                    _profile(configuration, dense_identity=mismatched),
                    "retrieval query",
                    limit=5,
                )
        assert embedder.calls == []
        assert gate.serving_calls == 0

    asyncio.run(exercise())


def test_evaluation_query_passes_explicit_draft_access_to_hydrator() -> None:
    configuration = _e5_configuration()
    gate = _Gate(snapshot_status="draft")
    hydrator = _Hydrator(gate)
    embedder = _QueryEmbedder((1.0,) + (0.0,) * 383)

    def respond(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"result": {"points": []}})
        return httpx.Response(
            200,
            json={
                "result": {
                    "config": {
                        "params": {"vectors": {"size": 384, "distance": "Cosine"}}
                    }
                }
            },
        )

    async def exercise() -> None:
        async with httpx.AsyncClient(
            base_url="http://qdrant.test", transport=httpx.MockTransport(respond)
        ) as http:
            service = SnapshotDenseSearch(
                gate,
                QdrantIndex(configuration, http),
                query_embedder=embedder,
                evidence_hydrator=hydrator,
            )
            result = await service.evaluate_query(
                _profile(configuration), "evaluation query", limit=5
            )
        assert gate.serving_calls == 0
        assert gate.evaluation_calls == 1
        assert result.hydrated_hits == ()
        assert hydrator.allow_draft_calls == [True]

    asyncio.run(exercise())
