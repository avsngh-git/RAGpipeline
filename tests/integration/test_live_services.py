"""Live boundary tests for explicitly configured disposable services."""

import asyncio
import os
from urllib.parse import urlparse
from uuid import uuid4

import asyncpg
import httpx
import pytest

from research_platform.config import Settings
from research_platform.services.readiness import LiveDependencyChecker
from scripts.migrate import apply_migrations

TEST_DATABASE_URL = os.environ.get("RESEARCH_PLATFORM_TEST_DATABASE_URL")
TEST_QDRANT_URL = os.environ.get("RESEARCH_PLATFORM_TEST_QDRANT_URL")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not TEST_DATABASE_URL or not TEST_QDRANT_URL,
        reason="requires dedicated disposable PostgreSQL and Qdrant services",
    ),
]


async def _wait_for_services() -> None:
    assert TEST_DATABASE_URL is not None
    assert TEST_QDRANT_URL is not None
    loop = asyncio.get_running_loop()
    deadline = loop.time() + 30
    last_error = "no connection attempt"

    while loop.time() < deadline:
        try:
            connection = await asyncpg.connect(TEST_DATABASE_URL, timeout=1)
            try:
                await connection.fetchval("SELECT 1")
            finally:
                await connection.close()

            async with httpx.AsyncClient(timeout=1) as client:
                response = await client.get(f"{TEST_QDRANT_URL.rstrip('/')}/healthz")
                response.raise_for_status()
            return
        except Exception as error:
            last_error = type(error).__name__
            await asyncio.sleep(0.5)

    raise AssertionError(f"disposable services did not become ready: {last_error}")


@pytest.fixture(scope="module", autouse=True)
def disposable_services_ready() -> None:
    assert TEST_DATABASE_URL is not None
    database_name = urlparse(TEST_DATABASE_URL).path.removeprefix("/")
    assert database_name == "research_test", (
        "integration tests require the isolated research_test database"
    )
    asyncio.run(_wait_for_services())


def test_live_readiness_reports_postgres_and_qdrant() -> None:
    assert TEST_DATABASE_URL is not None
    assert TEST_QDRANT_URL is not None
    settings = Settings(
        database_url=TEST_DATABASE_URL,
        qdrant_url=TEST_QDRANT_URL,
        dependency_timeout_seconds=2,
    )

    report = asyncio.run(LiveDependencyChecker(settings).check())

    assert report.dependencies == {"postgres": True, "qdrant": True}


def test_migration_is_repeatable_and_database_constraints_are_enforced() -> None:
    assert TEST_DATABASE_URL is not None

    async def exercise_database() -> None:
        await apply_migrations(TEST_DATABASE_URL)
        await apply_migrations(TEST_DATABASE_URL)
        connection = await asyncpg.connect(TEST_DATABASE_URL)
        transaction = connection.transaction()
        await transaction.start()
        try:
            versions = await connection.fetch(
                "SELECT version FROM schema_migrations ORDER BY version"
            )
            assert [row["version"] for row in versions] == ["001_initial"]

            collection_name = f"integration-{uuid4().hex}"
            await connection.execute(
                "INSERT INTO collections (name) VALUES ($1)",
                collection_name,
            )

            with pytest.raises(asyncpg.UniqueViolationError):
                async with connection.transaction():
                    await connection.execute(
                        "INSERT INTO collections (name) VALUES ($1)",
                        collection_name,
                    )

            with pytest.raises(asyncpg.ForeignKeyViolationError):
                async with connection.transaction():
                    await connection.execute(
                        """
                        INSERT INTO documents (paper_id, source_type, version)
                        VALUES ('missing-paper', 'integration-test', 'v1')
                        """
                    )
        finally:
            await transaction.rollback()
            await connection.close()

    asyncio.run(exercise_database())


def test_qdrant_accepts_and_removes_a_temporary_collection() -> None:
    assert TEST_QDRANT_URL is not None
    collection_name = f"phase0-integration-{uuid4().hex}"

    async def exercise_qdrant() -> None:
        async with httpx.AsyncClient(timeout=5) as client:
            created = False
            try:
                response = await client.put(
                    f"{TEST_QDRANT_URL.rstrip('/')}/collections/{collection_name}",
                    json={"vectors": {"size": 2, "distance": "Dot"}},
                )
                response.raise_for_status()
                created = True

                details = await client.get(
                    f"{TEST_QDRANT_URL.rstrip('/')}/collections/{collection_name}"
                )
                details.raise_for_status()
                assert details.json()["result"]["status"] == "green"
            finally:
                if created:
                    deleted = await client.delete(
                        f"{TEST_QDRANT_URL.rstrip('/')}/collections/{collection_name}"
                    )
                    deleted.raise_for_status()

    asyncio.run(exercise_qdrant())
