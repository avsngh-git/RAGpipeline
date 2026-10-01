"""PostgreSQL coverage for snapshot-bound related-paper reads."""

import asyncio
import os
from collections.abc import Awaitable, Callable
from urllib.parse import urlparse
from uuid import UUID, uuid4

import asyncpg
import pytest

from research_platform.persistence.migrations import apply_migrations
from research_platform.search.paper_reads import PaperReadStatus, SnapshotNotFound
from research_platform.search.paper_related import (
    RelatedPaperReader,
    RelationKind,
)

TEST_DATABASE_URL = os.environ.get("RESEARCH_PLATFORM_TEST_DATABASE_URL")
PaperGraphCheck = Callable[[RelatedPaperReader, UUID, dict[str, str]], Awaitable[None]]

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not TEST_DATABASE_URL,
        reason="requires the dedicated disposable PostgreSQL service",
    ),
]


def _run_with_graph(check: PaperGraphCheck) -> None:
    assert TEST_DATABASE_URL is not None
    assert urlparse(TEST_DATABASE_URL).path.removeprefix("/") == "research_test", (
        "integration tests require the isolated research_test database"
    )

    async def exercise() -> None:
        await apply_migrations(TEST_DATABASE_URL)
        pool = await asyncpg.create_pool(TEST_DATABASE_URL, min_size=1, max_size=2)
        snapshot_id = uuid4()
        number = uuid4().int
        paper_ids = {
            "source": f"W{number}",
            "shared": f"W{number + 1}",
            "co_cited": f"W{number + 2}",
            "both": f"W{number + 3}",
            "isolated": f"W{number + 4}",
            "outside": f"W{number + 5}",
        }
        local_paper_ids = {
            "source": f"local-{number}",
            "shared": paper_ids["shared"],
            "co_cited": paper_ids["co_cited"],
            "both": paper_ids["both"],
            "isolated": paper_ids["isolated"],
            "outside": paper_ids["outside"],
        }
        document_ids = [uuid4() for _ in range(5)]
        try:
            async with pool.acquire() as connection:
                await connection.execute(
                    """
                    INSERT INTO snapshots
                        (id, name, configuration_id, configuration, code_revision)
                    VALUES ($1, 'paper-related-integration', 'test-config', '{}'::jsonb,
                            'test-revision')
                    """,
                    snapshot_id,
                )
                await connection.executemany(
                    """
                    INSERT INTO papers (id, openalex_id, title, publication_year, metadata)
                    VALUES ($1, $2, $3, $4, '{}'::jsonb)
                    """,
                    [
                        (local_paper_ids["source"], None, "Source paper", 2025),
                        (
                            paper_ids["shared"],
                            paper_ids["shared"],
                            "Shared paper",
                            2024,
                        ),
                        (
                            paper_ids["co_cited"],
                            paper_ids["co_cited"],
                            "Co-cited paper",
                            2023,
                        ),
                        (paper_ids["both"], paper_ids["both"], "Both paper", 2022),
                        (
                            paper_ids["isolated"],
                            paper_ids["isolated"],
                            "Isolated paper",
                            2021,
                        ),
                        (
                            paper_ids["outside"],
                            paper_ids["outside"],
                            "Outside paper",
                            2020,
                        ),
                    ],
                )
                await connection.execute(
                    """
                    INSERT INTO paper_identifiers
                        (paper_id, namespace, identifier, normalized_identifier,
                         verification_method)
                    VALUES ($1, 'openalex', $2, $2, 'integration-fixture')
                    """,
                    local_paper_ids["source"],
                    paper_ids["source"],
                )
                await connection.executemany(
                    """
                    INSERT INTO documents (id, paper_id, source_type, version)
                    VALUES ($1, $2, 'integration', 'v1')
                    """,
                    [
                        (document_ids[index], local_paper_ids[name])
                        for index, name in enumerate(
                            ("source", "shared", "co_cited", "both", "isolated")
                        )
                    ],
                )
                await connection.executemany(
                    """
                    INSERT INTO snapshot_items
                        (snapshot_id, paper_id, document_id, selection_reason)
                    VALUES ($1, $2, $3, 'integration fixture')
                    """,
                    [
                        (snapshot_id, local_paper_ids[name], document_ids[index])
                        for index, name in enumerate(
                            ("source", "shared", "co_cited", "both", "isolated")
                        )
                    ],
                )
                await connection.executemany(
                    """
                    INSERT INTO citations (citing_paper_id, cited_paper_id, source)
                    VALUES ($1, $2, 'openalex')
                    """,
                    [
                        (local_paper_ids["source"], paper_ids["outside"]),
                        (paper_ids["shared"], paper_ids["outside"]),
                        (paper_ids["both"], paper_ids["outside"]),
                        (paper_ids["outside"], local_paper_ids["source"]),
                        (paper_ids["outside"], paper_ids["co_cited"]),
                        (paper_ids["outside"], paper_ids["both"]),
                    ],
                )
                await connection.executemany(
                    """
                    INSERT INTO unresolved_citations
                        (citing_paper_id, target_namespace, target_identifier, source)
                    VALUES ($1, 'openalex', $2, 'integration-unresolved')
                    """,
                    [
                        (local_paper_ids["source"], f"W{number + 20}"),
                        (paper_ids["shared"], f"W{number + 20}"),
                    ],
                )

            await check(RelatedPaperReader(pool), snapshot_id, paper_ids)
        finally:
            async with pool.acquire() as connection:
                await connection.execute(
                    "DELETE FROM snapshot_items WHERE snapshot_id = $1", snapshot_id
                )
                await connection.execute(
                    "DELETE FROM snapshots WHERE id = $1", snapshot_id
                )
                await connection.execute(
                    "DELETE FROM documents WHERE id = ANY($1::uuid[])", document_ids
                )
                await connection.execute(
                    "DELETE FROM papers WHERE id = ANY($1::text[])",
                    list(local_paper_ids.values()),
                )
            await pool.close()

    asyncio.run(exercise())


def test_counts_shared_references_and_co_citations() -> None:
    async def check(
        reader: RelatedPaperReader, snapshot_id: UUID, paper_ids: dict[str, str]
    ) -> None:
        page = await reader.find_related(snapshot_id, paper_ids["source"])

        by_id = {paper.paper_id: paper for paper in page.papers}
        assert by_id[paper_ids["both"]].shared_reference_count == 1
        assert by_id[paper_ids["both"]].co_citation_count == 1
        assert by_id[paper_ids["both"]].score == 2
        assert by_id[paper_ids["shared"]].relations == (RelationKind.SHARED_REFERENCES,)
        assert by_id[paper_ids["co_cited"]].relations == (RelationKind.CO_CITED,)
        assert page.coverage_note == (
            "Related papers are based on stored in-corpus citation edges only."
        )

    _run_with_graph(check)


def test_excludes_source_and_papers_outside_snapshot() -> None:
    async def check(
        reader: RelatedPaperReader, snapshot_id: UUID, paper_ids: dict[str, str]
    ) -> None:
        page = await reader.find_related(snapshot_id, paper_ids["source"])

        result_ids = {paper.paper_id for paper in page.papers}
        assert paper_ids["source"] not in result_ids
        assert paper_ids["outside"] not in result_ids
        assert paper_ids["isolated"] not in result_ids

    _run_with_graph(check)


def test_unknown_snapshot_raises() -> None:
    async def check(
        reader: RelatedPaperReader, _snapshot_id: UUID, paper_ids: dict[str, str]
    ) -> None:
        with pytest.raises(SnapshotNotFound):
            await reader.find_related(uuid4(), paper_ids["source"])

    _run_with_graph(check)


def test_source_outside_snapshot_returns_empty_page_with_status() -> None:
    async def check(
        reader: RelatedPaperReader, snapshot_id: UUID, paper_ids: dict[str, str]
    ) -> None:
        page = await reader.find_related(snapshot_id, paper_ids["outside"])

        assert page.source_status is PaperReadStatus.OUTSIDE_SNAPSHOT
        assert page.papers == ()

    _run_with_graph(check)


def test_isolated_paper_returns_empty_page() -> None:
    async def check(
        reader: RelatedPaperReader, snapshot_id: UUID, paper_ids: dict[str, str]
    ) -> None:
        page = await reader.find_related(snapshot_id, paper_ids["isolated"])

        assert page.source_status is PaperReadStatus.IN_SNAPSHOT
        assert page.papers == ()

    _run_with_graph(check)


def test_invalid_limit_raises() -> None:
    async def check(
        reader: RelatedPaperReader, snapshot_id: UUID, paper_ids: dict[str, str]
    ) -> None:
        with pytest.raises(ValueError, match="between 1 and 20"):
            await reader.find_related(snapshot_id, paper_ids["source"], limit=0)

    _run_with_graph(check)
