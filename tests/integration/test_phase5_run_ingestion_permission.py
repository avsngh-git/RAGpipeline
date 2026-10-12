"""PostgreSQL coverage for run ingestion permissions."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from urllib.parse import urlparse
from uuid import UUID, uuid4

import asyncpg
import pytest

from research_platform.config import DiscoverySettings
from research_platform.ingestion.membership_policy import MembershipPolicy
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


def test_repository_round_trips_ingestion_permitted() -> None:
    async def exercise(
        _pool: asyncpg.Pool,
        repo: RunRepository,
        snapshot_id: UUID,
        _collection_id: UUID,
    ) -> None:
        request = _request(snapshot_id)
        refused_run_id = await repo.create_run(request, ingestion_permitted=False)
        permitted_run_id = await repo.create_run(request)

        assert (await repo.get_run(refused_run_id)).ingestion_permitted is False
        assert (await repo.get_run(permitted_run_id)).ingestion_permitted is True

    _with_database(exercise)


def test_existing_rows_default_to_permitted() -> None:
    async def exercise(
        pool: asyncpg.Pool,
        repo: RunRepository,
        snapshot_id: UUID,
        _collection_id: UUID,
    ) -> None:
        request = _request(snapshot_id)
        async with pool.acquire() as connection:
            run_id = await connection.fetchval(
                """
                INSERT INTO research_runs
                    (question, status, mode, request, snapshot_id, generation, principal)
                VALUES ($1, 'queued', $2, $3::jsonb, $4, NULL, 'integration-test')
                RETURNING id
                """,
                request.question,
                request.mode.value,
                request.model_dump_json(),
                snapshot_id,
            )

        stored = await repo.get_run(run_id)

        assert stored.ingestion_permitted is True

    _with_database(exercise)


def test_membership_policy_refuses_when_run_lacks_ingest_permission() -> None:
    async def exercise(
        pool: asyncpg.Pool,
        repo: RunRepository,
        snapshot_id: UUID,
        collection_id: UUID,
    ) -> None:
        run_id = await repo.create_run(_request(snapshot_id), ingestion_permitted=False)
        policy = MembershipPolicy(
            pool,
            _PaperFixture(),  # type: ignore[arg-type]
            DiscoverySettings(),
            collection_id=collection_id,
        )

        result = await policy.submit(
            run_id=run_id,
            requested_by="run",
            paper_ids=["W123"],
            max_papers=5,
        )

        assert result.request_id is None
        assert [
            (decision.decision, decision.reason) for decision in result.decisions
        ] == [("refused", "ingest_scope_required")]
        async with pool.acquire() as connection:
            queued = await connection.fetchval(
                "SELECT count(*) FROM ingestion_requests WHERE run_id = $1", run_id
            )
        assert queued == 0

    _with_database(exercise)


def _with_database(
    operation: Callable[[asyncpg.Pool, RunRepository, UUID, UUID], Awaitable[None]],
) -> None:
    assert TEST_DATABASE_URL is not None
    assert urlparse(TEST_DATABASE_URL).path.removeprefix("/") == "research_test", (
        "integration tests require the isolated research_test database"
    )

    async def exercise() -> None:
        await apply_migrations(TEST_DATABASE_URL)
        pool = await asyncpg.create_pool(TEST_DATABASE_URL, min_size=1, max_size=2)
        snapshot_id = uuid4()
        collection_id = uuid4()
        try:
            async with pool.acquire() as connection:
                await connection.execute(
                    """
                    INSERT INTO snapshots (id, name, configuration_id, configuration,
                                          code_revision)
                    VALUES ($1, $2, 'test-config', '{}'::jsonb, 'test-revision')
                    """,
                    snapshot_id,
                    f"phase5-run-permission-{snapshot_id}",
                )
                await connection.execute(
                    "INSERT INTO collections (id, name) VALUES ($1, $2)",
                    collection_id,
                    f"phase5-run-permission-{collection_id}",
                )
            await operation(pool, RunRepository(pool), snapshot_id, collection_id)
        finally:
            async with pool.acquire() as connection:
                await connection.execute(
                    "DELETE FROM research_runs WHERE snapshot_id = $1", snapshot_id
                )
                await connection.execute(
                    "DELETE FROM snapshots WHERE id = $1", snapshot_id
                )
                await connection.execute(
                    "DELETE FROM collections WHERE id = $1", collection_id
                )
            await pool.close()

    asyncio.run(exercise())


def _request(snapshot_id: UUID) -> ResearchRequest:
    return ResearchRequest(
        question="Synthetic integration fixture",
        mode=ResearchMode.QUICK,
        snapshot_id=snapshot_id,
    )


@dataclass(frozen=True)
class _Configuration:
    configuration_id: str = "integration-fixture"


@dataclass(frozen=True)
class _Point:
    payload: dict[str, object]


class _PaperFixture:
    configuration = _Configuration()

    async def retrieve(self, _point_ids: Sequence[str]) -> list[_Point]:
        return [_Point({"paper_id": "W123", "publication_year": 2025})]
