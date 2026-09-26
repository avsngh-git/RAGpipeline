"""PostgreSQL coverage for the bounded snapshot paper-read query."""

import asyncio
import json
import os
from urllib.parse import urlparse
from uuid import uuid4

import asyncpg
import pytest

from research_platform.persistence.migrations import apply_migrations
from research_platform.search.paper_reads import (
    MetadataAvailability,
    PaperReadStatus,
    SnapshotPaperReader,
)

TEST_DATABASE_URL = os.environ.get("RESEARCH_PLATFORM_TEST_DATABASE_URL")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not TEST_DATABASE_URL,
        reason="requires the dedicated disposable PostgreSQL service",
    ),
]


def test_snapshot_paper_reader_resolves_membership_and_metadata() -> None:
    assert TEST_DATABASE_URL is not None
    assert urlparse(TEST_DATABASE_URL).path.removeprefix("/") == "research_test", (
        "integration tests require the isolated research_test database"
    )

    async def exercise() -> None:
        await apply_migrations(TEST_DATABASE_URL)
        pool = await asyncpg.create_pool(TEST_DATABASE_URL, min_size=1, max_size=2)
        snapshot_id = uuid4()
        document_id = uuid4()
        paper_number = uuid4().int
        selected_paper_id = f"W{paper_number}"
        outside_paper_id = f"W{paper_number + 1}"
        outside_local_id = f"local-{paper_number + 1}"
        selected_document_version = "published-version-2026-01"
        metadata = {"abstract_inverted_index": {"A": [0], "summary.": [1]}}
        try:
            async with pool.acquire() as connection:
                await connection.execute(
                    """
                    INSERT INTO snapshots
                        (id, name, configuration_id, configuration, code_revision)
                    VALUES ($1, $2, $3, '{}'::jsonb, $4)
                    """,
                    snapshot_id,
                    "paper-read-integration",
                    "test-configuration",
                    "test-revision",
                )
                await connection.executemany(
                    """
                    INSERT INTO papers
                        (id, openalex_id, title, publication_year, metadata)
                    VALUES ($1, $2, $3, $4, $5::jsonb)
                    """,
                    [
                        (
                            selected_paper_id,
                            selected_paper_id,
                            "Selected paper",
                            2026,
                            json.dumps(metadata),
                        ),
                        (
                            outside_local_id,
                            None,
                            "Outside paper",
                            None,
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
                    outside_local_id,
                    outside_paper_id,
                )
                await connection.execute(
                    """
                    INSERT INTO documents
                        (id, paper_id, source_type, version, version_kind)
                    VALUES ($1, $2, 'integration', $3, 'published')
                    """,
                    document_id,
                    selected_paper_id,
                    selected_document_version,
                )
                await connection.execute(
                    """
                    INSERT INTO snapshot_items
                        (snapshot_id, paper_id, document_id, selection_reason)
                    VALUES ($1, $2, $3, 'integration fixture')
                    """,
                    snapshot_id,
                    selected_paper_id,
                    document_id,
                )

            reader = SnapshotPaperReader(pool)
            selected = await reader.read_paper(snapshot_id, selected_paper_id)
            outside = await reader.read_paper(snapshot_id, outside_paper_id)
            unknown = await reader.read_paper(snapshot_id, "W999999999999999999")

            assert selected.status is PaperReadStatus.IN_SNAPSHOT
            assert selected.document_id == document_id
            assert selected.document_version == selected_document_version
            assert selected.metadata_availability.abstract
            assert outside.status is PaperReadStatus.OUTSIDE_SNAPSHOT
            assert outside.document_version is None
            assert outside.metadata_availability == MetadataAvailability(
                False, False, False
            )
            assert unknown.status is PaperReadStatus.UNKNOWN
        finally:
            async with pool.acquire() as connection:
                await connection.execute(
                    "DELETE FROM snapshot_items WHERE snapshot_id = $1", snapshot_id
                )
                await connection.execute(
                    "DELETE FROM snapshots WHERE id = $1", snapshot_id
                )
                await connection.execute(
                    "DELETE FROM documents WHERE id = $1", document_id
                )
                await connection.execute(
                    "DELETE FROM papers WHERE id = ANY($1::text[])",
                    [selected_paper_id, outside_local_id],
                )
            await pool.close()

    asyncio.run(exercise())
