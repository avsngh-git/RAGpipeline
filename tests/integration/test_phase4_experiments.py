"""PostgreSQL integration coverage for experiment records."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from urllib.parse import urlparse
from uuid import UUID, uuid4

import asyncpg
import pytest

from research_platform.evaluation.experiments import (
    ExperimentOutcome,
    ExperimentRecord,
    ExperimentStatus,
    PostgresExperimentStore,
)
from research_platform.persistence.migrations import apply_migrations

TEST_DATABASE_URL = os.environ.get("RESEARCH_PLATFORM_TEST_DATABASE_URL")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not TEST_DATABASE_URL,
        reason="requires the dedicated disposable PostgreSQL service",
    ),
]


def _record(experiment_id: UUID) -> ExperimentRecord:
    return ExperimentRecord(
        experiment_id=experiment_id,
        suite="scripted-regression",
        status=ExperimentStatus.RUNNING,
        dataset_name="synthetic",
        dataset_version="v1",
        dataset_sha256="a" * 64,
        code_revision="test-revision",
        items_path=f"local-reference/experiments/{experiment_id}/items.jsonl",
        started_at=datetime.now(UTC),
    )


def _outcome() -> ExperimentOutcome:
    return ExperimentOutcome(
        configuration_id="config-v1",
        configuration={"mode": "quick"},
        versions={"generator": "scripted"},
        random_seed=11,
        metrics={"score": 0.9},
        failures={},
        item_count=3,
    )


def _with_database(operation: Callable[[asyncpg.Pool], Awaitable[None]]) -> None:
    assert TEST_DATABASE_URL is not None
    assert urlparse(TEST_DATABASE_URL).path.removeprefix("/") == "research_test", (
        "integration tests require the isolated research_test database"
    )

    async def exercise() -> None:
        await apply_migrations(TEST_DATABASE_URL)
        pool = await asyncpg.create_pool(TEST_DATABASE_URL, min_size=1, max_size=2)
        try:
            await operation(pool)
        finally:
            await pool.close()

    asyncio.run(exercise())


def test_postgres_store_lifecycle() -> None:
    async def exercise(pool: asyncpg.Pool) -> None:
        store = PostgresExperimentStore(pool)
        experiment_id = uuid4()
        try:
            await store.start(_record(experiment_id))
            running = await store.get(experiment_id)
            completed = await store.finish(
                experiment_id,
                status=ExperimentStatus.COMPLETED,
                outcome=_outcome(),
            )

            assert running.status is ExperimentStatus.RUNNING
            assert completed.status is ExperimentStatus.COMPLETED
            assert completed.completed_at is not None
            assert completed.metrics == {"score": 0.9}
            assert await store.get(experiment_id) == completed
        finally:
            await pool.execute(
                "DELETE FROM experiments WHERE experiment_id = $1", experiment_id
            )

    _with_database(exercise)


def test_status_completed_requires_completed_at() -> None:
    async def exercise(pool: asyncpg.Pool) -> None:
        experiment_id = uuid4()
        try:
            await PostgresExperimentStore(pool).start(_record(experiment_id))
            with pytest.raises(asyncpg.CheckViolationError):
                await pool.execute(
                    "UPDATE experiments SET status = 'completed' WHERE experiment_id = $1",
                    experiment_id,
                )
        finally:
            await pool.execute(
                "DELETE FROM experiments WHERE experiment_id = $1", experiment_id
            )

    _with_database(exercise)
