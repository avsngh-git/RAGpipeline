"""Profile binding and serving/evaluation boundaries for dense search."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from uuid import UUID

import httpx
import pytest

from research_platform.ingestion.embeddings import (
    BGEBaseEnV15Embedder,
    E5SmallV2Embedder,
)
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
from research_platform.search.contracts import SearchFilters
from research_platform.search.dense_search import (
    ProfileDenseIndexMismatch,
    SnapshotDenseSearch,
    UnsupportedRetrievalProfile,
)
from research_platform.search.profiles import (
    CandidateLimits,
    DenseIndexIdentity,
    FusionSettings,
    LexicalIndexIdentity,
    RetrievalProfile,
)

SNAPSHOT_ID = UUID("f1336240-dda0-45fb-a5b1-ff399bd93436")
SNAPSHOT_CONFIG_ID = "sha256:" + "a" * 64
CHUNK_SELECTION_ID = "sha256:" + "b" * 64


class _Gate:
    def __init__(
        self,
        snapshot_status: str = "finalized",
        filter_payload_revision: str | None = DENSE_FILTER_PAYLOAD_REVISION,
        expected_count: int = 1,
    ) -> None:
        self.snapshot_status = snapshot_status
        self.filter_payload_revision = filter_payload_revision
        self.expected_count = expected_count
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
            expected_count=self.expected_count,
            filter_payload_revision=self.filter_payload_revision,
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
            expected_count=self.expected_count,
            filter_payload_revision=self.filter_payload_revision,
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
    fusion: bool = False,
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
        fusion=FusionSettings() if fusion else None,
        candidate_limits=CandidateLimits(
            lexical_top_k=10 if lexical else None,
            dense_top_k=10,
            fused_top_k=10 if fusion else None,
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
    def __init__(
        self,
        gate: _Gate,
        payload_overrides: Mapping[str, object] | None = None,
    ) -> None:
        self.gate = gate
        self.payload_overrides = dict(payload_overrides or {})
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
            assert self.gate.serving_calls >= 1
        self.calls.append((snapshot_selection, tuple(matches)))
        self.allow_draft_calls.append(allow_draft)
        hydrated: list[IndexInput] = []
        for match in matches:
            payload: dict[str, object] = {
                "snapshot_id": str(snapshot_selection.snapshot_id),
                "index_configuration_id": configuration.configuration_id,
                "paper_id": "W123",
                "document_id": str(UUID(int=1)),
                "document_version": "published",
                "document_version_kind": "preprint",
                "evidence_kind": "table_row_group",
                "extraction_id": str(UUID(int=2)),
                "source_artifact_id": str(UUID(int=3)),
                "source_artifact_sha256": "sha256:" + "d" * 64,
                "publication_year": 2024,
                "paper_title": "Fixture paper",
                "section_id": None,
                "section_title": "Results",
            }
            payload.update(self.payload_overrides)
            hydrated.append(
                IndexInput(
                    evidence_id=match.evidence_id,
                    text="authoritative database source text",
                    payload=payload,
                )
            )
        return tuple(hydrated)


def _e5_configuration() -> IndexConfiguration:
    return E5SmallV2Embedder.index_configuration(
        collection_name="dense-e5-query-test", batch_size=2
    )


@pytest.mark.parametrize("hybrid_component", [False, True])
def test_e5_query_search_hydrates_ranked_hits_from_the_authoritative_source(
    hybrid_component: bool,
) -> None:
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
    count_requests: list[dict[str, object]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path.endswith("/points/count"):
            count_requests.append(json.loads(request.content))
            return httpx.Response(200, json={"result": {"count": 1}})
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
            profile = _profile(
                configuration,
                lexical=hybrid_component,
                fusion=hybrid_component,
            )
            search = (
                service.search_hybrid_component_query
                if hybrid_component
                else service.search_query
            )
            result = await search(profile, "retrieval query", limit=5)
        assert embedder.calls == [("retrieval query", configuration)]
        assert gate.serving_calls == 1
        assert gate.evaluation_calls == 0
        assert requests[0]["query"] == [1.0] + [0.0] * 383
        assert requests[0]["filter"] == {
            "must": [{"key": "snapshot_id", "match": {"value": str(SNAPSHOT_ID)}}]
        }
        assert len(hydrator.calls) == 1
        assert result.profile_id == profile.profile_id
        assert result.candidate_count == 1
        assert result.truncated is False
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


def test_bge_query_search_uses_a_separate_768_dim_index_and_hydrates() -> None:
    configuration = BGEBaseEnV15Embedder.index_configuration(
        collection_name="dense-bge-query-test", batch_size=2
    )
    gate = _Gate()
    evidence_id = "sha256:" + "e" * 64
    fixture_point = {
        "payload": {
            "snapshot_id": str(SNAPSHOT_ID),
            "index_configuration_id": configuration.configuration_id,
            "evidence_id": evidence_id,
            "text": "stale vector payload text",
        },
        "score": 0.91,
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
                            "params": {"vectors": {"size": 768, "distance": "Cosine"}}
                        }
                    }
                },
            )
        return httpx.Response(200, json={"result": {"points": []}})

    async def exercise() -> None:
        embedder = _QueryEmbedder((1.0,) + (0.0,) * 767)
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
        assert requests[0]["query"] == [1.0] + [0.0] * 767
        assert result.index_configuration_id == configuration.configuration_id
        assert result.hits[0].evidence_id == evidence_id
        assert result.hydrated_hits[0].evidence.text == (
            "authoritative database source text"
        )

    asyncio.run(exercise())


def test_bge_query_rejects_unreviewed_revision_before_embedding() -> None:
    compatible = BGEBaseEnV15Embedder.index_configuration(
        collection_name="dense-bge-revision-test"
    )
    configuration = IndexConfiguration.from_dict(
        {**compatible.to_dict(), "embedding_revision": "unreviewed-revision"}
    )
    gate = _Gate()
    embedder = _QueryEmbedder((1.0,) + (0.0,) * 767)

    async def exercise() -> None:
        async with httpx.AsyncClient(
            base_url="http://qdrant.test",
            transport=httpx.MockTransport(
                lambda _request: pytest.fail(
                    "unreviewed embedding identity must fail before Qdrant"
                )
            ),
        ) as http:
            service = SnapshotDenseSearch(
                gate,
                QdrantIndex(configuration, http),
                query_embedder=embedder,
                evidence_hydrator=_Hydrator(gate),
            )
            with pytest.raises(ProfileDenseIndexMismatch, match="BGE-base-en-v1.5"):
                await service.search_query(
                    _profile(configuration), "retrieval query", limit=5
                )
        assert embedder.calls == []
        assert gate.serving_calls == 0

    asyncio.run(exercise())


@pytest.mark.parametrize("model_name", ["e5", "bge"])
def test_dense_query_sends_all_metadata_filters_to_qdrant_before_top_k(
    model_name: str,
) -> None:
    if model_name == "e5":
        configuration = _e5_configuration()
        dimensions = 384
    else:
        configuration = BGEBaseEnV15Embedder.index_configuration(
            collection_name="dense-bge-filter-test", batch_size=2
        )
        dimensions = 768
    gate = _Gate(expected_count=2)
    evidence_id = "sha256:" + "f" * 64
    global_top_point = {
        "payload": {
            "snapshot_id": str(SNAPSHOT_ID),
            "index_configuration_id": configuration.configuration_id,
            "filter_payload_revision": DENSE_FILTER_PAYLOAD_REVISION,
            "paper_id": "W999",
            "publication_year": 2018,
            "evidence_kind": "text",
            "document_version_kind": "published",
            "evidence_id": "sha256:" + "e" * 64,
        },
        "score": 0.99,
    }
    fixture_point = {
        "payload": {
            "snapshot_id": str(SNAPSHOT_ID),
            "index_configuration_id": configuration.configuration_id,
            "filter_payload_revision": DENSE_FILTER_PAYLOAD_REVISION,
            "paper_id": "W123",
            "publication_year": 2024,
            "evidence_kind": "table_row_group",
            "document_version_kind": "preprint",
            "evidence_id": evidence_id,
        },
        "score": 0.93,
    }
    requests: list[dict[str, object]] = []
    count_requests: list[dict[str, object]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path.endswith("/points/count"):
            count_requests.append(json.loads(request.content))
            return httpx.Response(200, json={"result": {"count": 1}})
        if request.method == "POST" and request.url.path.endswith("/points/query"):
            query = json.loads(request.content)
            requests.append(query)
            filter_keys = {
                item.get("key")
                for item in query["filter"]["must"]
                if isinstance(item, dict)
            }
            point = (
                fixture_point if "publication_year" in filter_keys else global_top_point
            )
            return httpx.Response(200, json={"result": {"points": [point]}})
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "result": {
                        "config": {
                            "params": {
                                "vectors": {
                                    "size": dimensions,
                                    "distance": "Cosine",
                                }
                            }
                        }
                    }
                },
            )
        return httpx.Response(200, json={"result": {"points": []}})

    filters = SearchFilters(
        year_from=2020,
        year_to=2024,
        paper_ids=("W123", "W456"),
        evidence_kinds=("table", "table_row_group"),
        document_version_kinds=("preprint", "published"),
    )

    async def exercise() -> None:
        async with httpx.AsyncClient(
            base_url="http://qdrant.test", transport=httpx.MockTransport(respond)
        ) as http:
            service = SnapshotDenseSearch(
                gate,
                QdrantIndex(configuration, http),
                query_embedder=_QueryEmbedder((1.0,) + (0.0,) * (dimensions - 1)),
                evidence_hydrator=_Hydrator(gate),
            )
            profile = _profile(configuration)
            unfiltered = await service.search_query(profile, "filtered query", limit=1)
            result = await service.search_query(
                profile, "filtered query", limit=1, filters=filters
            )
        assert unfiltered.hits[0].evidence_id == "sha256:" + "e" * 64
        assert unfiltered.truncated is True
        assert requests[0]["limit"] == requests[1]["limit"] == 1
        assert count_requests[0]["exact"] is True
        assert count_requests[0]["filter"] == requests[1]["filter"]
        assert requests[1]["filter"] == {
            "must": [
                {"key": "snapshot_id", "match": {"value": str(SNAPSHOT_ID)}},
                {
                    "key": "filter_payload_revision",
                    "match": {"value": DENSE_FILTER_PAYLOAD_REVISION},
                },
                {
                    "key": "publication_year",
                    "range": {"gte": 2020, "lte": 2024},
                },
                {"key": "paper_id", "match": {"any": ["W123", "W456"]}},
                {
                    "key": "evidence_kind",
                    "match": {"any": ["table", "table_row_group"]},
                },
                {
                    "key": "document_version_kind",
                    "match": {"any": ["preprint", "published"]},
                },
            ]
        }
        assert result.hits[0].evidence_id == evidence_id
        assert result.hydrated_hits[0].evidence.payload["publication_year"] == 2024
        assert result.candidate_count == 1
        assert result.truncated is False
        assert result.applied_filters == filters

    asyncio.run(exercise())


def test_dense_query_rechecks_filters_against_authoritative_hydration() -> None:
    configuration = _e5_configuration()
    gate = _Gate()
    evidence_id = "sha256:" + "f" * 64
    fixture_point = {
        "payload": {
            "snapshot_id": str(SNAPSHOT_ID),
            "index_configuration_id": configuration.configuration_id,
            "filter_payload_revision": DENSE_FILTER_PAYLOAD_REVISION,
            "evidence_id": evidence_id,
            "publication_year": 2024,
        },
        "score": 0.93,
    }

    def respond(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path.endswith("/points/count"):
            return httpx.Response(200, json={"result": {"count": 1}})
        if request.method == "POST" and request.url.path.endswith("/points/query"):
            return httpx.Response(200, json={"result": {"points": [fixture_point]}})
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
                query_embedder=_QueryEmbedder((1.0,) + (0.0,) * 383),
                evidence_hydrator=_Hydrator(gate, {"publication_year": 2019}),
            )
            with pytest.raises(SnapshotIndexMismatch, match="authoritative evidence"):
                await service.search_query(
                    _profile(configuration),
                    "filtered query",
                    limit=1,
                    filters=SearchFilters(year_from=2020),
                )

    asyncio.run(exercise())


@pytest.mark.parametrize(
    ("filters", "missing_field"),
    [
        (SearchFilters(year_from=2020), "publication_year"),
        (SearchFilters(evidence_kinds=("table",)), "evidence_kind"),
        (SearchFilters(document_version_kinds=("preprint",)), "document_version_kind"),
    ],
)
def test_dense_filters_return_empty_when_required_payload_metadata_is_missing(
    filters: SearchFilters, missing_field: str
) -> None:
    configuration = _e5_configuration()
    gate = _Gate()
    calls: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            calls.append(request)
            if request.url.path.endswith("/points/count"):
                return httpx.Response(200, json={"result": {"count": 0}})
            if request.url.path.endswith("/points/query"):
                return httpx.Response(200, json={"result": {"points": []}})
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
        return httpx.Response(200, json={"result": {}})

    async def exercise() -> None:
        async with httpx.AsyncClient(
            base_url="http://qdrant.test", transport=httpx.MockTransport(respond)
        ) as http:
            service = SnapshotDenseSearch(
                gate,
                QdrantIndex(configuration, http),
                query_embedder=_QueryEmbedder((1.0,) + (0.0,) * 383),
                evidence_hydrator=_Hydrator(gate),
            )
            result = await service.search_query(
                _profile(configuration), "filtered query", limit=5, filters=filters
            )
        assert result.hits == ()
        assert result.hydrated_hits == ()
        assert result.candidate_count == 0
        assert result.eligible_count == 0
        assert result.result_status.value == "no_eligible_records"
        assert result.truncated is False
        assert result.applied_filters == filters
        count_body = json.loads(calls[0].content)
        assert count_body["exact"] is True
        assert any(
            condition.get("key") == missing_field
            for condition in count_body["filter"]["must"]
        )

    asyncio.run(exercise())


def test_dense_filter_rejects_stale_index_payload_revision() -> None:
    configuration = _e5_configuration()
    gate = _Gate(filter_payload_revision=None)
    qdrant_calls: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        qdrant_calls.append(request)
        return httpx.Response(200)

    async def exercise() -> None:
        async with httpx.AsyncClient(
            base_url="http://qdrant.test", transport=httpx.MockTransport(respond)
        ) as http:
            service = SnapshotDenseSearch(
                gate,
                QdrantIndex(configuration, http),
                query_embedder=_QueryEmbedder((1.0,) + (0.0,) * 383),
                evidence_hydrator=_Hydrator(gate),
            )
            with pytest.raises(SnapshotIndexMismatch, match="rebuild the index"):
                await service.search_query(
                    _profile(configuration),
                    "filtered query",
                    limit=1,
                    filters=SearchFilters(year_from=2020),
                )
        assert qdrant_calls == []

    asyncio.run(exercise())
