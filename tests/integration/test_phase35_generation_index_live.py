"""Live Qdrant coverage for generation-tagged collections (P35-05)."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable
from uuid import uuid4

import httpx
import pytest

from research_platform.ingestion.generation_index import (
    GenerationIndexConfiguration,
    GenerationPoint,
    GenerationQdrantCollection,
    SparseLexicalSettings,
    SparseVector,
    generation_filter,
    passage_point_id,
    with_conditions,
)

TEST_QDRANT_URL = os.environ.get("RESEARCH_PLATFORM_TEST_QDRANT_URL")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not TEST_QDRANT_URL, reason="requires the dedicated disposable Qdrant service"
    ),
]


def _configuration() -> GenerationIndexConfiguration:
    suffix = uuid4().hex[:12]
    return GenerationIndexConfiguration(
        passages_collection=f"phase35-passages-{suffix}",
        papers_collection=f"phase35-papers-{suffix}",
        embedding_model="model",
        embedding_revision="revision",
        preprocessing_revision="preprocessing",
        vector_size=2,
        distance="Cosine",
        batch_size=16,
        maximum_input_tokens=512,
        lexical=SparseLexicalSettings(
            analyzer="scientific-en",
            analyzer_revision="v1",
            vocabulary_id="scientific-en-v1",
            k1=1.5,
            b=0.75,
            evidence_average_length=3.0,
            paper_average_length=3.0,
        ),
    )


def _points(configuration: GenerationIndexConfiguration) -> list[GenerationPoint]:
    rows = [
        ("e1", 1, (1.0, 0.0), "W1", (1,)),
        ("e2", 1, (0.9, 0.1), "W1", (1, 2)),
        ("e3", 1, (0.0, 1.0), "W2", (2,)),
        ("e4", 2, (0.8, 0.2), "W3", (1,)),
        ("e5", 2, (0.1, 0.9), "W3", (3,)),
    ]
    return [
        GenerationPoint(
            point_id=passage_point_id(evidence_id, configuration.configuration_id),
            dense=dense,
            sparse=SparseVector(terms, tuple(0.5 for _ in terms)),
            payload={
                "evidence_id": evidence_id,
                "paper_id": paper_id,
                "added_generation": generation,
                "lexical_terms": [f"t{term}" for term in terms],
            },
        )
        for evidence_id, generation, dense, paper_id, terms in rows
    ]


def _with_collection(
    operation: Callable[[GenerationQdrantCollection], Awaitable[None]],
) -> None:
    assert TEST_QDRANT_URL is not None

    async def exercise() -> None:
        async with httpx.AsyncClient(base_url=TEST_QDRANT_URL, timeout=30) as http:
            configuration = _configuration()
            collection = GenerationQdrantCollection(configuration, "passages", http)
            try:
                await collection.ensure_collection()
                await collection.ensure_collection()
                await collection.ensure_payload_indexes()
                await collection.upsert(_points(configuration))
                await collection.set_payload(
                    [passage_point_id("e2", configuration.configuration_id)],
                    {"retired_generation": 2},
                )
                await operation(collection)
            finally:
                await http.delete(f"/collections/{collection.name}")

    asyncio.run(exercise())


def test_generation_visibility_with_added_and_retired_points() -> None:
    async def exercise(collection: GenerationQdrantCollection) -> None:
        assert await collection.count(generation_filter(1)) == 3
        assert await collection.count(generation_filter(2)) == 4
        first = await collection.query_dense(
            (1.0, 0.0), filter_=generation_filter(1), limit=10
        )
        second = await collection.query_dense(
            (1.0, 0.0), filter_=generation_filter(2), limit=10
        )
        assert {m.payload["evidence_id"] for m in first} == {"e1", "e2", "e3"}
        assert {m.payload["evidence_id"] for m in second} == {"e1", "e3", "e4", "e5"}
        sparse = await collection.query_sparse(
            SparseVector((1,), (1.0,)),
            filter_=generation_filter(2),
            idf_filter=generation_filter(2),
            limit=10,
        )
        assert {m.payload["evidence_id"] for m in sparse} == {"e1", "e4"}
        payloads = await collection.scroll_payloads(
            filter_=generation_filter(2), fields=["evidence_id"]
        )
        assert sorted(p["evidence_id"] for p in payloads) == ["e1", "e3", "e4", "e5"]

    _with_collection(exercise)


def test_exact_count_with_extra_conditions() -> None:
    async def exercise(collection: GenerationQdrantCollection) -> None:
        by_paper = with_conditions(
            generation_filter(2), [{"key": "paper_id", "match": {"value": "W3"}}]
        )
        by_term = with_conditions(
            generation_filter(2),
            [{"key": "lexical_terms", "match": {"any": ["t1", "t3"]}}],
        )
        assert await collection.count(by_paper) == 2
        assert await collection.count(by_term) == 3

    _with_collection(exercise)


def test_retrieve_returns_payloads_in_requested_order() -> None:
    async def exercise(collection: GenerationQdrantCollection) -> None:
        configuration_id = collection.configuration.configuration_id
        ids = [passage_point_id(e, configuration_id) for e in ("e5", "missing", "e1")]
        matches = await collection.retrieve(ids, with_dense=True)
        assert [m.payload["evidence_id"] for m in matches] == ["e5", "e1"]
        assert matches[1].dense is not None and len(matches[1].dense) == 2
        first = await collection.query_dense(
            (0.1, 0.9), filter_=generation_filter(2), limit=5
        )
        recommended = await collection.recommend(
            first[0].point_id, filter_=generation_filter(2), limit=5
        )
        assert first[0].point_id not in {m.point_id for m in recommended}

    _with_collection(exercise)
