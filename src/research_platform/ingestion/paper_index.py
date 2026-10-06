"""The ``papers`` collection: one point per known paper (P35-07, ADR-0022 item 5).

Dense vectors embed the title and decoded OpenAlex abstract. Papers that belong to a
generation carry ``indexed_generation``; every other paper is ``metadata_only``.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol, cast
from uuid import UUID

import asyncpg  # type: ignore[import-untyped]

from research_platform.ingestion.generation_index import (
    GenerationIndexConfiguration,
    GenerationPoint,
    GenerationQdrantCollection,
    SparseVector,
    paper_point_id,
)
from research_platform.ingestion.indexing import VectorEmbedder
from research_platform.ingestion.openalex import abstract_from_openalex_metadata

CatalogStatus = Literal["ingested", "metadata_only"]


class SparsePaperEncoder(Protocol):
    async def encode_papers(
        self, texts: Sequence[str]
    ) -> tuple[tuple[SparseVector, tuple[str, ...]], ...]: ...


def paper_lexical_text(title: str | None) -> str:
    """The text the Phase 2 BM25S paper index scored: the stripped title only.

    That index never decoded the metadata JSON, so abstracts were not used (P35-07
    finding); lexical parity with profile v10 requires the same text.
    """
    return title.strip() if title is not None else ""


_KNOWN_PAPERS_SQL = """
SELECT paper.id AS paper_id, paper.title, paper.publication_year, paper.metadata,
       (SELECT normalized_identifier FROM paper_identifiers
        WHERE paper_id = paper.id AND namespace = 'openalex'
        ORDER BY normalized_identifier LIMIT 1) AS openalex_id,
       (SELECT normalized_identifier FROM paper_identifiers
        WHERE paper_id = paper.id AND namespace = 'doi'
        ORDER BY normalized_identifier LIMIT 1) AS doi
FROM papers AS paper
ORDER BY paper.id
"""


@dataclass(frozen=True)
class PaperIndexInput:
    paper_id: str
    title: str | None
    abstract: str | None
    publication_year: int | None
    openalex_id: str | None
    doi: str | None

    @property
    def index_text(self) -> str:
        """Title and abstract joined as in ``PaperLexicalDocument.index_text``."""
        fields = tuple(
            field.strip()
            for field in (self.title, self.abstract)
            if field is not None and field.strip()
        )
        return "\n\n".join(fields)

    @property
    def index_text_sha256(self) -> str:
        return hashlib.sha256(self.index_text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class PaperSyncReport:
    upserted_count: int
    newly_indexed_count: int
    skipped_without_text: int


class PaperIndexRepository:
    """Read every known paper and the members of a snapshot."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def load_known_papers(self) -> tuple[PaperIndexInput, ...]:
        async with self._pool.acquire() as connection:
            rows = await connection.fetch(_KNOWN_PAPERS_SQL)
        return tuple(_paper_input(row) for row in rows)

    async def snapshot_member_ids(self, snapshot_id: UUID) -> frozenset[str]:
        async with self._pool.acquire() as connection:
            rows = await connection.fetch(
                "SELECT paper_id FROM snapshot_items WHERE snapshot_id = $1",
                snapshot_id,
            )
        return frozenset(str(row["paper_id"]) for row in rows)


def paper_payload(
    paper: PaperIndexInput,
    configuration: GenerationIndexConfiguration,
    *,
    catalog_status: CatalogStatus,
    indexed_generation: int | None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "paper_id": paper.paper_id,
        "title": paper.title,
        "abstract": paper.abstract,
        "publication_year": paper.publication_year,
        "openalex_id": paper.openalex_id,
        "doi": paper.doi,
        "index_text_sha256": paper.index_text_sha256,
        "catalog_status": catalog_status,
        "index_configuration_id": configuration.configuration_id,
        "payload_revision": configuration.payload_revision,
    }
    if indexed_generation is not None:
        payload["indexed_generation"] = indexed_generation
    return payload


async def sync_papers(
    *,
    repository: PaperIndexRepository,
    papers: GenerationQdrantCollection,
    embedder: VectorEmbedder,
    configuration: GenerationIndexConfiguration,
    generation: int,
    snapshot_id: UUID,
    sparse_encoder: SparsePaperEncoder | None = None,
) -> PaperSyncReport:
    """Upsert new or changed papers and mark the snapshot's members as indexed."""
    if (configuration.lexical is None) != (sparse_encoder is None):
        raise ValueError(
            "a sparse encoder is required exactly when lexical settings are configured"
        )
    await papers.ensure_collection()
    await papers.ensure_payload_indexes()
    known = await repository.load_known_papers()
    existing = {
        cast(str, payload["paper_id"]): payload
        for payload in await papers.scroll_payloads(
            filter_={},
            fields=[
                "paper_id",
                "index_text_sha256",
                "indexed_generation",
                "catalog_status",
            ],
        )
    }
    with_text = [paper for paper in known if paper.index_text]
    changed = [
        paper
        for paper in with_text
        if existing.get(paper.paper_id, {}).get("index_text_sha256")
        != paper.index_text_sha256
    ]
    for start in range(0, len(changed), configuration.batch_size):
        batch = changed[start : start + configuration.batch_size]
        vectors = await embedder.embed(
            [paper.index_text for paper in batch],
            configuration=configuration.dense_configuration(),
        )
        if len(vectors) != len(batch):
            raise ValueError("embedding adapter returned a different item count")
        sparse = (
            await sparse_encoder.encode_papers(
                [paper_lexical_text(paper.title) for paper in batch]
            )
            if sparse_encoder is not None
            else None
        )
        points = []
        for index, (paper, vector) in enumerate(zip(batch, vectors, strict=True)):
            previous = existing.get(paper.paper_id, {})
            indexed = previous.get("indexed_generation")
            payload = paper_payload(
                paper,
                configuration,
                catalog_status=cast(
                    CatalogStatus,
                    previous.get("catalog_status", "metadata_only"),
                ),
                indexed_generation=None if indexed is None else int(cast(int, indexed)),
            )
            sparse_vector = None
            if sparse is not None:
                sparse_vector, terms = sparse[index]
                payload["lexical_terms"] = list(terms)
            points.append(
                GenerationPoint(
                    point_id=paper_point_id(
                        paper.paper_id, configuration.configuration_id
                    ),
                    dense=vector,
                    sparse=sparse_vector,
                    payload=payload,
                )
            )
        await papers.upsert(points)
    members = await repository.snapshot_member_ids(snapshot_id)
    indexed_ids = {
        paper_id
        for paper_id, payload in existing.items()
        if payload.get("indexed_generation") is not None
    }
    available = {paper.paper_id for paper in with_text}
    missing = members - available
    if missing:
        raise ValueError(f"{len(missing)} snapshot members have no paper text to index")
    newly_indexed = sorted(members - indexed_ids)
    await papers.set_payload(
        [
            paper_point_id(paper_id, configuration.configuration_id)
            for paper_id in newly_indexed
        ],
        {"indexed_generation": generation, "catalog_status": "ingested"},
    )
    return PaperSyncReport(
        upserted_count=len(changed),
        newly_indexed_count=len(newly_indexed),
        skipped_without_text=len(known) - len(with_text),
    )


def _paper_input(row: Mapping[str, object]) -> PaperIndexInput:
    metadata = row["metadata"]
    if isinstance(metadata, str):
        metadata = json.loads(metadata)
    abstract = (
        abstract_from_openalex_metadata(metadata)
        if isinstance(metadata, Mapping)
        else None
    )
    year = row["publication_year"]
    return PaperIndexInput(
        paper_id=cast(str, row["paper_id"]),
        title=cast(str | None, row["title"]),
        abstract=abstract,
        publication_year=None if year is None else int(cast(int, year)),
        openalex_id=cast(str | None, row["openalex_id"]),
        doi=cast(str | None, row["doi"]),
    )
