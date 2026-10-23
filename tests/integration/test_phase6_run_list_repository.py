"""PostgreSQL coverage for principal-scoped keyset run history."""

from __future__ import annotations

import asyncio
import os
from urllib.parse import urlparse
from uuid import UUID

import asyncpg
import pytest

from research_platform.persistence.migrations import apply_migrations
from research_platform.runs.contracts import ResearchMode, ResearchRequest
from research_platform.runs.repository import RunRepository

TEST_DATABASE_URL = os.environ.get("RESEARCH_PLATFORM_TEST_DATABASE_URL")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not TEST_DATABASE_URL,
        reason="requires the dedicated disposable PostgreSQL service",
    ),
]


def test_repository_lists_principal_runs_with_keyset() -> None:
    assert TEST_DATABASE_URL is not None
    assert urlparse(TEST_DATABASE_URL).path.removeprefix("/") == "research_test", (
        "integration tests require the isolated research_test database"
    )

    async def exercise() -> None:
        await apply_migrations(TEST_DATABASE_URL)
        pool = await asyncpg.create_pool(TEST_DATABASE_URL, min_size=1, max_size=2)
        repository = RunRepository(pool)
        run_ids: list[UUID] = []
        try:
            first = await repository.create_run(
                ResearchRequest(question="Synthetic first", mode=ResearchMode.QUICK),
                principal="list-test-alice",
            )
            run_ids.append(first)
            other = await repository.create_run(
                ResearchRequest(question="Synthetic other", mode=ResearchMode.QUICK),
                principal="list-test-bob",
            )
            run_ids.append(other)
            second = await repository.create_run(
                ResearchRequest(question="Synthetic second", mode=ResearchMode.QUICK),
                principal="list-test-alice",
            )
            run_ids.append(second)

            rows = await repository.list_principal_runs("list-test-alice", limit=10)
            older = await repository.list_principal_runs(
                "list-test-alice",
                limit=10,
                before=(rows[0].created_at, rows[0].run_id),
            )
            assert [row.run_id for row in rows] == [second, first]
            assert [row.run_id for row in older] == [first]
            assert all(
                (row.created_at, row.run_id) < (rows[0].created_at, rows[0].run_id)
                for row in older
            )
        finally:
            async with pool.acquire() as connection:
                await connection.execute(
                    "DELETE FROM research_runs WHERE id = ANY($1::uuid[])", run_ids
                )
            await pool.close()

    asyncio.run(exercise())
