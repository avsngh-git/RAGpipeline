"""Offline tests for semantic related-paper reads from the Qdrant catalog."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any
from uuid import UUID

import httpx
import pytest

from research_platform.ingestion.generation_index import (
    GenerationIndexConfiguration,
    GenerationQdrantCollection,
    paper_point_id,
)
from research_platform.search.paper_similarity import (
    PaperSimilarityReader,
    SimilarPaper,
)

PAPER_A = "W100"
PAPER_B = "W200"


def _configuration() -> GenerationIndexConfiguration:
    return GenerationIndexConfiguration(
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


class _Embedder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    async def embed_query(
        self, text: str, *, configuration: object
    ) -> tuple[float, float]:
        self.calls.append((text, configuration))
        return (0.1, 0.2)


class _Qdrant:
    def __init__(self, *, source_exists: bool = True) -> None:
        self.source_exists = source_exists
        self.requests: list[tuple[str, dict[str, Any]]] = []
        self.recommendation_points: list[dict[str, object]] = []
        self.query_points: list[dict[str, object]] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else {}
        self.requests.append((request.url.path, body))
        if request.url.path.endswith("/points/query"):
            points = (
                self.recommendation_points
                if isinstance(body.get("query"), Mapping)
                else self.query_points
            )
            return httpx.Response(200, json={"result": {"points": points}})
        if request.url.path.endswith("/points"):
            points = (
                [
                    {
                        "id": body["ids"][0],
                        "payload": {"paper_id": PAPER_A},
                    }
                ]
                if self.source_exists
                else []
            )
            return httpx.Response(200, json={"result": points})
        return httpx.Response(404)


def _paper_point(
    paper_id: str,
    *,
    score: float,
    status: str = "ingested",
    title: str | None = "A paper",
    year: int | None = 2024,
) -> dict[str, object]:
    return {
        "id": str(UUID(int=len(paper_id))),
        "score": score,
        "payload": {
            "paper_id": paper_id,
            "title": title,
            "publication_year": year,
            "catalog_status": status,
        },
    }


@pytest.mark.anyio
async def test_recommend_excludes_source_and_respects_generation() -> None:
    configuration = _configuration()
    source_id = paper_point_id(PAPER_A, configuration.configuration_id)
    qdrant = _Qdrant()
    qdrant.recommendation_points = [
        _paper_point(PAPER_B, score=0.83, title="Related retrieval paper")
    ]
    embedder = _Embedder()

    async with httpx.AsyncClient(
        base_url="http://qdrant", transport=httpx.MockTransport(qdrant.handle)
    ) as http:
        reader = PaperSimilarityReader(
            GenerationQdrantCollection(configuration, "papers", http), embedder
        )
        result = await reader.similar_to_paper(PAPER_A, generation=7, limit=3)

    assert result == (
        SimilarPaper(
            paper_id=PAPER_B,
            title="Related retrieval paper",
            publication_year=2024,
            similarity=0.83,
            catalog_status="ingested",
        ),
    )
    assert all(paper.paper_id != PAPER_A for paper in result)
    recommend_request = qdrant.requests[-1][1]
    assert recommend_request["query"] == {"recommend": {"positive": [str(source_id)]}}
    assert recommend_request["filter"] == {
        "must": [{"key": "indexed_generation", "range": {"lte": 7}}],
        "must_not": [{"has_id": [str(source_id)]}],
    }
    assert recommend_request["limit"] == 3


@pytest.mark.anyio
async def test_missing_source_returns_empty() -> None:
    qdrant = _Qdrant(source_exists=False)

    async with httpx.AsyncClient(
        base_url="http://qdrant", transport=httpx.MockTransport(qdrant.handle)
    ) as http:
        reader = PaperSimilarityReader(
            GenerationQdrantCollection(_configuration(), "papers", http), _Embedder()
        )
        result = await reader.similar_to_paper(PAPER_A, generation=1, limit=5)

    assert result == ()
    assert len(qdrant.requests) == 1
    assert qdrant.requests[0][0].endswith("/points")


@pytest.mark.anyio
async def test_uningested_filters_status_and_threshold() -> None:
    configuration = _configuration()
    qdrant = _Qdrant()
    qdrant.query_points = [
        _paper_point("W300", score=0.74, status="metadata_only"),
        _paper_point("W400", score=0.49, status="metadata_only"),
        _paper_point("W500", score=0.92, status="ingested"),
    ]
    embedder = _Embedder()

    async with httpx.AsyncClient(
        base_url="http://qdrant", transport=httpx.MockTransport(qdrant.handle)
    ) as http:
        reader = PaperSimilarityReader(
            GenerationQdrantCollection(configuration, "papers", http), embedder
        )
        result = await reader.uningested_for_question(
            "What does synthetic retrieval show?", limit=3, minimum_similarity=0.5
        )

    assert tuple(paper.paper_id for paper in result) == ("W300",)
    assert result[0].similarity == 0.74
    assert result[0].catalog_status == "metadata_only"
    assert embedder.calls[0][0] == "What does synthetic retrieval show?"
    assert embedder.calls[0][1] == configuration.dense_configuration()
    query_request = qdrant.requests[-1][1]
    assert query_request["filter"] == {
        "must": [{"key": "catalog_status", "match": {"value": "metadata_only"}}]
    }
    assert query_request["limit"] == 3
