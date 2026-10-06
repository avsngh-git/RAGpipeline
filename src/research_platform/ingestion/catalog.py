"""Store discovered OpenAlex works and their metadata history."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass

import asyncpg  # type: ignore[import-untyped]

from research_platform.ingestion.openalex import (
    OpenAlexWork,
    abstract_from_openalex_metadata,
)
from research_platform.ingestion.papers import PaperRepository


@dataclass(frozen=True)
class CatalogUpsert:
    paper_id: str
    created: bool
    revision: int | None


class CatalogRepository:
    """Upsert catalog metadata without adding snapshot membership or documents."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def upsert_openalex_work(
        self, work: OpenAlexWork, metadata: Mapping[str, object]
    ) -> CatalogUpsert:
        """Persist one work and append a revision only when its metadata changes."""
        canonical_metadata = json.dumps(
            dict(metadata),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        metadata_sha256 = hashlib.sha256(canonical_metadata.encode("utf-8")).hexdigest()
        repository = PaperRepository(self._pool)

        async with self._pool.acquire() as connection:
            async with connection.transaction():
                paper_id, created = await repository.resolve_paper_identity(
                    connection,
                    work.openalex_id,
                    work.doi,
                    work.title,
                    work.publication_year,
                    metadata,
                )
                await repository.persist_authors(connection, paper_id, metadata)
                await connection.fetchval(
                    "SELECT id FROM papers WHERE id = $1 FOR UPDATE", paper_id
                )
                latest = await connection.fetchrow(
                    """
                    SELECT revision, metadata_sha256
                    FROM paper_metadata_revisions
                    WHERE paper_id = $1
                    ORDER BY revision DESC
                    LIMIT 1
                    """,
                    paper_id,
                )
                if latest is not None and latest["metadata_sha256"] == metadata_sha256:
                    revision = None
                else:
                    revision = 1 if latest is None else latest["revision"] + 1
                    await connection.execute(
                        """
                        INSERT INTO paper_metadata_revisions
                            (paper_id, revision, source, metadata, metadata_sha256)
                        VALUES ($1, $2, 'openalex', $3::jsonb, $4)
                        """,
                        paper_id,
                        revision,
                        canonical_metadata,
                        metadata_sha256,
                    )

        return CatalogUpsert(paper_id, created, revision)

    async def abstract_for(self, paper_id: str) -> str | None:
        """Return the latest catalog abstract for a paper, if one is available."""
        async with self._pool.acquire() as connection:
            metadata = await connection.fetchval(
                """
                SELECT metadata
                FROM paper_metadata_revisions
                WHERE paper_id = $1
                ORDER BY revision DESC
                LIMIT 1
                """,
                paper_id,
            )
        if metadata is None:
            return None
        if isinstance(metadata, str):
            metadata = json.loads(metadata)
        if not isinstance(metadata, Mapping):
            raise ValueError("stored OpenAlex metadata has an unexpected shape")
        return abstract_from_openalex_metadata(metadata)
