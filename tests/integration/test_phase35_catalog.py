"""PostgreSQL coverage for discovered OpenAlex catalog works."""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Awaitable, Callable
from urllib.parse import urlparse
from uuid import uuid4

import asyncpg
import pytest

from research_platform.ingestion.catalog import CatalogRepository
from research_platform.ingestion.openalex import OpenAlexWork
from research_platform.persistence.migrations import apply_migrations

TEST_DATABASE_URL = os.environ.get("RESEARCH_PLATFORM_TEST_DATABASE_URL")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not TEST_DATABASE_URL,
        reason="requires the dedicated disposable PostgreSQL service",
    ),
]


def test_new_work_creates_paper_and_first_revision() -> None:
    async def exercise(pool: asyncpg.Pool, openalex_id: str, author_id: str) -> None:
        metadata = _metadata(openalex_id, author_id)
        work = OpenAlexWork.from_payload(metadata)

        result = await CatalogRepository(pool).upsert_openalex_work(work, metadata)

        assert result.paper_id == openalex_id
        assert result.created
        assert result.revision == 1
        assert await CatalogRepository(pool).abstract_for(result.paper_id) == (
            "A useful abstract."
        )
        async with pool.acquire() as connection:
            paper = await connection.fetchrow(
                "SELECT title, publication_year FROM papers WHERE id = $1",
                result.paper_id,
            )
            revision = await connection.fetchrow(
                """
                SELECT source, metadata, metadata_sha256
                FROM paper_metadata_revisions
                WHERE paper_id = $1 AND revision = 1
                """,
                result.paper_id,
            )
            author_count = await connection.fetchval(
                "SELECT count(*) FROM paper_authors WHERE paper_id = $1",
                result.paper_id,
            )
            document_count = await connection.fetchval(
                "SELECT count(*) FROM documents WHERE paper_id = $1",
                result.paper_id,
            )
            membership_count = await connection.fetchval(
                "SELECT count(*) FROM collection_papers WHERE paper_id = $1",
                result.paper_id,
            )

        assert paper["title"] == "Catalog test work"
        assert paper["publication_year"] == 2024
        assert revision["source"] == "openalex"
        stored_metadata = revision["metadata"]
        if isinstance(stored_metadata, str):
            stored_metadata = json.loads(stored_metadata)
        assert stored_metadata["id"].endswith(openalex_id)
        assert len(revision["metadata_sha256"]) == 64
        assert author_count == 1
        assert document_count == 0
        assert membership_count == 0

    _with_database(exercise)


def test_same_metadata_adds_no_revision() -> None:
    async def exercise(pool: asyncpg.Pool, openalex_id: str, author_id: str) -> None:
        metadata = _metadata(openalex_id, author_id)
        work = OpenAlexWork.from_payload(metadata)
        repository = CatalogRepository(pool)

        first = await repository.upsert_openalex_work(work, metadata)
        reordered = dict(reversed(tuple(metadata.items())))
        second = await repository.upsert_openalex_work(
            OpenAlexWork.from_payload(reordered), reordered
        )
        revision_count = await pool.fetchval(
            "SELECT count(*) FROM paper_metadata_revisions WHERE paper_id = $1",
            first.paper_id,
        )

        assert first.revision == 1
        assert second.created is False
        assert second.revision is None
        assert revision_count == 1

    _with_database(exercise)


def test_changed_metadata_adds_revision() -> None:
    async def exercise(pool: asyncpg.Pool, openalex_id: str, author_id: str) -> None:
        original = _metadata(openalex_id, author_id)
        changed = {**original, "cited_by_count": 4}
        repository = CatalogRepository(pool)

        first = await repository.upsert_openalex_work(
            OpenAlexWork.from_payload(original), original
        )
        second = await repository.upsert_openalex_work(
            OpenAlexWork.from_payload(changed), changed
        )
        revisions = await pool.fetch(
            """
            SELECT revision, metadata_sha256 FROM paper_metadata_revisions
            WHERE paper_id = $1 ORDER BY revision
            """,
            first.paper_id,
        )

        assert first.revision == 1
        assert second.revision == 2
        assert revisions[0]["revision"] == 1
        assert revisions[1]["revision"] == 2
        assert revisions[0]["metadata_sha256"] != revisions[1]["metadata_sha256"]

    _with_database(exercise)


def test_existing_paper_resolved_by_doi() -> None:
    async def exercise(pool: asyncpg.Pool, openalex_id: str, author_id: str) -> None:
        paper_id = f"doi-match-{uuid4().hex}"
        doi = "10.1234/catalog-test"
        async with pool.acquire() as connection:
            await connection.execute(
                "INSERT INTO papers (id, title) VALUES ($1, 'Existing DOI paper')",
                paper_id,
            )
            await connection.execute(
                """
                INSERT INTO paper_identifiers
                    (paper_id, namespace, identifier, normalized_identifier,
                     verification_method)
                VALUES ($1, 'doi', $2, $2, 'integration-test')
                """,
                paper_id,
                doi,
            )
        metadata = {
            **_metadata(openalex_id, author_id),
            "doi": f"https://doi.org/{doi}",
        }

        result = await CatalogRepository(pool).upsert_openalex_work(
            OpenAlexWork.from_payload(metadata), metadata
        )

        assert result.paper_id == paper_id
        assert result.created is False
        assert result.revision == 1
        assert (
            await pool.fetchval(
                "SELECT count(*) FROM papers WHERE openalex_id = $1", openalex_id
            )
            == 1
        )

    _with_database(exercise)


def _metadata(openalex_id: str, author_id: str) -> dict[str, object]:
    return {
        "id": f"https://openalex.org/{openalex_id}",
        "title": "Catalog test work",
        "publication_year": 2024,
        "doi": None,
        "language": "en",
        "type": "article",
        "cited_by_count": 1,
        "authorships": [
            {
                "author": {
                    "id": f"https://openalex.org/{author_id}",
                    "display_name": "Catalog Test Author",
                }
            }
        ],
        "abstract_inverted_index": {
            "A": [0],
            "useful": [1],
            "abstract.": [2],
        },
    }


def _with_database(
    operation: Callable[[asyncpg.Pool, str, str], Awaitable[None]],
) -> None:
    assert TEST_DATABASE_URL is not None
    assert urlparse(TEST_DATABASE_URL).path.removeprefix("/") == "research_test", (
        "integration tests require the isolated research_test database"
    )

    async def exercise() -> None:
        await apply_migrations(TEST_DATABASE_URL)
        pool = await asyncpg.create_pool(TEST_DATABASE_URL, min_size=1, max_size=2)
        openalex_id = f"W{uuid4().int % 10**12}"
        author_id = f"A{uuid4().int % 10**12}"
        try:
            await operation(pool, openalex_id, author_id)
        finally:
            async with pool.acquire() as connection:
                async with connection.transaction():
                    paper_ids = await connection.fetch(
                        """
                        SELECT id FROM papers
                        WHERE openalex_id = $1 OR id LIKE 'doi-match-%'
                        """,
                        openalex_id,
                    )
                    for row in paper_ids:
                        paper_id = row["id"]
                        await connection.execute(
                            "DELETE FROM paper_metadata_revisions WHERE paper_id = $1",
                            paper_id,
                        )
                        await connection.execute(
                            "DELETE FROM paper_identifiers WHERE paper_id = $1",
                            paper_id,
                        )
                        await connection.execute(
                            "DELETE FROM paper_authors WHERE paper_id = $1", paper_id
                        )
                        await connection.execute(
                            "DELETE FROM papers WHERE id = $1", paper_id
                        )
                    await connection.execute(
                        "DELETE FROM authors WHERE openalex_id = $1", author_id
                    )
            await pool.close()

    asyncio.run(exercise())
