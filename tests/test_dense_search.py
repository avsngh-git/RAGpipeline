"""Profile binding and serving/evaluation boundaries for dense search."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

import httpx
import pytest

from research_platform.ingestion.indexing import (
    IndexConfiguration,
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
