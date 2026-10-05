"""Semantic related-paper reads from the generation-tagged Qdrant paper catalog."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

from research_platform.ingestion.generation_index import (
    GenerationMatch,
    GenerationQdrantCollection,
    indexed_paper_filter,
    paper_point_id,
)
from research_platform.ingestion.identity import is_valid_paper_id
from research_platform.search.dense_search import DenseQueryEmbedder


@dataclass(frozen=True)
class SimilarPaper:
    """One paper returned by semantic similarity search."""

    paper_id: str
    title: str | None
    publication_year: int | None
    similarity: float
    catalog_status: Literal["ingested", "metadata_only"]

    def __post_init__(self) -> None:
        if not is_valid_paper_id(self.paper_id):
            raise ValueError("paper_id must be a canonical OpenAlex work ID")
        if self.title is not None and not isinstance(self.title, str):
            raise ValueError("title must be text or null")
        if self.publication_year is not None and (
            isinstance(self.publication_year, bool)
            or not isinstance(self.publication_year, int)
            or self.publication_year < 0
        ):
            raise ValueError("publication_year must be non-negative or null")
        if (
            isinstance(self.similarity, bool)
            or not isinstance(self.similarity, (int, float))
            or not math.isfinite(self.similarity)
        ):
            raise ValueError("similarity must be finite")
        if self.catalog_status not in ("ingested", "metadata_only"):
            raise ValueError("catalog_status must be ingested or metadata_only")


class PaperSimilarityReader:
    """Read semantic neighbours and metadata-only candidates from Qdrant."""

    def __init__(
        self, papers: GenerationQdrantCollection, embedder: DenseQueryEmbedder
    ) -> None:
        self._papers = papers
        self._embedder = embedder

    async def similar_to_paper(
        self, paper_id: str, *, generation: int, limit: int
    ) -> tuple[SimilarPaper, ...]:
        """Recommend papers visible in ``generation`` from one catalog paper."""
        _validate_paper_id(paper_id)
        _validate_limit(limit)
        filter_ = indexed_paper_filter(generation)
        source_point_id = paper_point_id(
            paper_id, self._papers.configuration.configuration_id
        )
        source_matches = await self._papers.retrieve((source_point_id,))
        if not source_matches:
            return ()
        if source_matches[0].payload.get("paper_id") != paper_id:
            raise RuntimeError("paper point identity does not match its payload")

        matches = await self._papers.recommend(
            source_point_id, filter_=filter_, limit=limit
        )
        return tuple(_similar_paper(match) for match in matches)

    async def uningested_for_question(
        self,
        question: str,
        *,
        limit: int = 5,
        minimum_similarity: float = 0.5,
    ) -> tuple[SimilarPaper, ...]:
        """Find metadata-only catalog papers above a diagnostic score threshold."""
        if not isinstance(question, str) or not question.strip():
            raise ValueError("question must be non-empty text")
        _validate_limit(limit)
        _validate_threshold(minimum_similarity)
        vector = await self._embedder.embed_query(
            question,
            configuration=self._papers.configuration.dense_configuration(),
        )
        matches = await self._papers.query_dense(
            vector,
            filter_={
                "must": [
                    {
                        "key": "catalog_status",
                        "match": {"value": "metadata_only"},
                    }
                ]
            },
            limit=limit,
        )
        return tuple(
            paper
            for paper in (_similar_paper(match) for match in matches)
            if paper.catalog_status == "metadata_only"
            and paper.similarity >= minimum_similarity
        )


def _similar_paper(match: GenerationMatch) -> SimilarPaper:
    payload = match.payload
    paper_id = payload.get("paper_id")
    title = payload.get("title")
    year = payload.get("publication_year")
    catalog_status = payload.get("catalog_status")
    if not isinstance(paper_id, str):
        raise RuntimeError("Qdrant paper result has no paper ID")
    if title is not None and not isinstance(title, str):
        raise RuntimeError("Qdrant paper result has an invalid title")
    if year is not None and (isinstance(year, bool) or not isinstance(year, int)):
        raise RuntimeError("Qdrant paper result has an invalid publication year")
    if catalog_status not in ("ingested", "metadata_only"):
        raise RuntimeError("Qdrant paper result has an invalid catalog status")
    return SimilarPaper(
        paper_id=paper_id,
        title=title,
        publication_year=year,
        similarity=match.score,
        catalog_status=catalog_status,
    )


def _validate_paper_id(paper_id: str) -> None:
    if not is_valid_paper_id(paper_id):
        raise ValueError("paper_id must be a canonical OpenAlex work ID")


def _validate_limit(limit: int) -> None:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 20:
        raise ValueError("limit must be between 1 and 20")


def _validate_threshold(minimum_similarity: float) -> None:
    if (
        isinstance(minimum_similarity, bool)
        or not isinstance(minimum_similarity, (int, float))
        or not math.isfinite(minimum_similarity)
        or not -1 <= minimum_similarity <= 1
    ):
        raise ValueError("minimum_similarity must be finite and between -1 and 1")
