"""PostgreSQL coverage for snapshot-bound, paginated paper graph reads."""

import asyncio
import os
from urllib.parse import urlparse
from uuid import uuid4

import asyncpg
import pytest

from research_platform.persistence.migrations import apply_migrations
from research_platform.search.paper_graph import (
    CitationDirection,
    CitationEndpointStatus,
    CitationGraphReader,
)

TEST_DATABASE_URL = os.environ.get("RESEARCH_PLATFORM_TEST_DATABASE_URL")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not TEST_DATABASE_URL,
        reason="requires the dedicated disposable PostgreSQL service",
    ),
]


def test_stored_graph_pages_resolved_unresolved_and_out_of_snapshot_endpoints() -> None:
    assert TEST_DATABASE_URL is not None
    assert urlparse(TEST_DATABASE_URL).path.removeprefix("/") == "research_test", (
        "integration tests require the isolated research_test database"
    )

    async def exercise() -> None:
        await apply_migrations(TEST_DATABASE_URL)
        pool = await asyncpg.create_pool(TEST_DATABASE_URL, min_size=1, max_size=2)
        snapshot_id = uuid4()
        source_document_id = uuid4()
        citing_document_id = uuid4()
        paper_number = uuid4().int
        source_paper_id = f"W{paper_number}"
        source_local_id = f"local-{paper_number}"
        target_paper_id = f"W{paper_number + 1}"
        citing_paper_id = f"W{paper_number + 2}"
        unresolved_citing_paper_id = f"W{paper_number + 3}"
        unresolved_target_id = f"W{paper_number + 4}"
        local_paper_ids = [
            source_local_id,
            target_paper_id,
            citing_paper_id,
            unresolved_citing_paper_id,
        ]
        document_ids = [source_document_id, citing_document_id]
        try:
            async with pool.acquire() as connection:
                await connection.execute(
                    """
                    INSERT INTO snapshots
                        (id, name, configuration_id, configuration, code_revision)
                    VALUES ($1, 'paper-graph-integration', 'test-config', '{}'::jsonb,
                            'test-revision')
                    """,
                    snapshot_id,
                )
                await connection.executemany(
                    """
                    INSERT INTO papers (id, openalex_id, title, publication_year, metadata)
                    VALUES ($1, $2, $3, $4, $5::jsonb)
                    """,
                    [
                        (source_local_id, None, "Source paper", 2025, "{}"),
                        (
                            target_paper_id,
                            target_paper_id,
                            "Outside target",
                            2024,
                            "{}",
                        ),
                        (
                            citing_paper_id,
                            citing_paper_id,
                            "In-snapshot citing paper",
                            2023,
                            "{}",
                        ),
                        (
                            unresolved_citing_paper_id,
                            unresolved_citing_paper_id,
                            "Outside unresolved citer",
                            2022,
                            "{}",
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
                    source_local_id,
                    source_paper_id,
                )
                await connection.executemany(
                    """
                    INSERT INTO documents (id, paper_id, source_type, version)
                    VALUES ($1, $2, 'integration', 'v1')
                    """,
                    [
                        (source_document_id, source_local_id),
                        (citing_document_id, citing_paper_id),
                    ],
                )
                await connection.executemany(
                    """
                    INSERT INTO snapshot_items
                        (snapshot_id, paper_id, document_id, selection_reason)
                    VALUES ($1, $2, $3, 'integration fixture')
                    """,
                    [
                        (snapshot_id, source_local_id, source_document_id),
                        (snapshot_id, citing_paper_id, citing_document_id),
                    ],
                )
                await connection.executemany(
                    """
                    INSERT INTO citations (citing_paper_id, cited_paper_id, source)
                    VALUES ($1, $2, 'openalex')
                    """,
                    [
                        (source_local_id, target_paper_id),
                        (citing_paper_id, source_local_id),
                    ],
                )
                await connection.executemany(
                    """
                    INSERT INTO unresolved_citations
                        (citing_paper_id, target_namespace, target_identifier, source)
                    VALUES ($1, 'openalex', $2, $3)
                    """,
                    [
                        (source_local_id, unresolved_target_id, "fixture-reference"),
                        (
                            unresolved_citing_paper_id,
                            source_paper_id,
                            "fixture-incoming-reference",
                        ),
                    ],
                )

            reader = CitationGraphReader(pool)
            first_reference_page = await reader.read_one_hop(
                snapshot_id,
                source_paper_id,
                CitationDirection.REFERENCES,
                limit=1,
            )
            second_reference_page = await reader.read_one_hop(
                snapshot_id,
                source_paper_id,
                CitationDirection.REFERENCES,
                limit=1,
                cursor=first_reference_page.next_cursor,
            )
            citation_page = await reader.read_one_hop(
                snapshot_id,
                source_paper_id,
                CitationDirection.CITATIONS,
                limit=10,
            )

            assert first_reference_page.has_more
            assert (
                first_reference_page.edges[0].endpoint.status
                is CitationEndpointStatus.UNRESOLVED
            )
            assert second_reference_page.edges[0].endpoint.paper_id == target_paper_id
            assert (
                second_reference_page.edges[0].endpoint.status
                is CitationEndpointStatus.OUTSIDE_SNAPSHOT
            )
            assert citation_page.source_status.value == "in_snapshot"
            assert {edge.endpoint.paper_id for edge in citation_page.edges} == {
                citing_paper_id,
                unresolved_citing_paper_id,
            }
            assert any(
                edge.endpoint.status is CitationEndpointStatus.OUTSIDE_SNAPSHOT
                for edge in citation_page.edges
            )
            assert "not a complete global citation list" in citation_page.coverage_note
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
                    "DELETE FROM papers WHERE id = ANY($1::text[])", local_paper_ids
                )
            await pool.close()

    asyncio.run(exercise())
