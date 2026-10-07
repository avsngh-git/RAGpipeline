"""PostgreSQL integration coverage for the Phase 4 retention command."""

from __future__ import annotations

import asyncio
import os
from urllib.parse import urlparse
from uuid import uuid4

import asyncpg
import pytest

from research_platform.maintenance.retention import (
    RetentionPolicy,
    delete_expired_llm_payloads,
    expired_checkpoint_runs,
    expired_llm_payloads,
    unpublished_generations,
)
from research_platform.persistence.migrations import apply_migrations
from research_platform.runs.checkpointing import CHECKPOINT_SCHEMA

TEST_DATABASE_URL = os.environ.get("RESEARCH_PLATFORM_TEST_DATABASE_URL")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not TEST_DATABASE_URL,
        reason="requires the dedicated disposable PostgreSQL service",
    ),
]


def test_expired_completed_and_failed_runs_selected() -> None:
    async def exercise(pool: asyncpg.Pool) -> None:
        selected = {
            "completed": uuid4(),
            "recent_completed": uuid4(),
            "failed": uuid4(),
            "recent_failed": uuid4(),
        }
        async with pool.acquire() as connection:
            for name, run_id in selected.items():
                status = "failed" if "failed" in name else "completed"
                days = {
                    "completed": 8,
                    "recent_completed": 2,
                    "failed": 31,
                    "recent_failed": 10,
                }[name]
                await connection.execute(
                    """
                    INSERT INTO research_runs (id, question, status, mode, completed_at)
                    VALUES ($1, 'fixture', $2, 'quick', now() - make_interval(days => $3))
                    """,
                    run_id,
                    status,
                    days,
                )
                await connection.execute(
                    f"""
                    INSERT INTO {CHECKPOINT_SCHEMA}.checkpoints
                        (thread_id, checkpoint_ns, checkpoint_id, type, checkpoint, metadata)
                    VALUES ($1, '', $2, 'json', '{{}}'::jsonb, '{{}}'::jsonb)
                    """,
                    str(run_id),
                    uuid4().hex,
                )
        try:
            found = await expired_checkpoint_runs(pool, RetentionPolicy())
            assert set(found) == {selected["completed"], selected["failed"]}
        finally:
            async with pool.acquire() as connection:
                await connection.execute(
                    f"DELETE FROM {CHECKPOINT_SCHEMA}.checkpoints WHERE thread_id = ANY($1::text[])",
                    [str(run_id) for run_id in selected.values()],
                )
                await connection.execute(
                    "DELETE FROM research_runs WHERE id = ANY($1::uuid[])",
                    list(selected.values()),
                )

    _with_database(exercise)


def test_runs_without_checkpoints_not_selected() -> None:
    async def exercise(pool: asyncpg.Pool) -> None:
        run_id = uuid4()
        async with pool.acquire() as connection:
            await connection.execute(
                """
                INSERT INTO research_runs (id, question, status, mode, completed_at)
                VALUES ($1, 'fixture', 'completed', 'quick', now() - interval '8 days')
                """,
                run_id,
            )
        try:
            assert run_id not in await expired_checkpoint_runs(pool, RetentionPolicy())
        finally:
            async with pool.acquire() as connection:
                await connection.execute(
                    "DELETE FROM research_runs WHERE id = $1", run_id
                )

    _with_database(exercise)


def test_payload_retention_counts_and_deletes() -> None:
    async def exercise(pool: asyncpg.Pool) -> None:
        run_id = uuid4()
        async with pool.acquire() as connection:
            await connection.execute(
                "INSERT INTO research_runs (id, question, status, mode) VALUES ($1, 'fixture', 'completed', 'quick')",
                run_id,
            )
            await connection.execute(
                """
                INSERT INTO llm_calls
                    (run_id, ordinal, kind, status, model_name, think, attempts, duration_ms)
                VALUES ($1, 1, 'plan', 'succeeded', 'fixture-model', false, 1, 1)
                """,
                run_id,
            )
            await connection.execute(
                """
                INSERT INTO llm_call_payloads (run_id, ordinal, messages, output)
                VALUES ($1, 1, '[]'::jsonb, 'zq7731')
                """,
                run_id,
            )
            await connection.execute(
                "UPDATE llm_call_payloads SET created_at = now() - interval '91 days' WHERE run_id = $1",
                run_id,
            )
        try:
            assert await expired_llm_payloads(pool, RetentionPolicy()) == 1
            assert await delete_expired_llm_payloads(pool, RetentionPolicy()) == 1
            assert await expired_llm_payloads(pool, RetentionPolicy()) == 0
        finally:
            async with pool.acquire() as connection:
                await connection.execute(
                    "DELETE FROM research_runs WHERE id = $1", run_id
                )

    _with_database(exercise)


def test_unpublished_generations_reported() -> None:
    async def exercise(pool: asyncpg.Pool) -> None:
        collection_id = uuid4()
        configuration_id = f"sha256:{uuid4().hex}{uuid4().hex}"
        snapshots = [uuid4() for _ in range(5)]
        unpublished_collection_id = uuid4()
        unpublished_configuration_id = f"sha256:{uuid4().hex}{uuid4().hex}"
        unpublished_snapshot_id = uuid4()
        async with pool.acquire() as connection:
            await connection.execute(
                "INSERT INTO collections (id, name) VALUES ($1, $2)",
                collection_id,
                f"retention-{collection_id}",
            )
            await connection.execute(
                "INSERT INTO index_configurations (configuration_id, configuration) VALUES ($1, '{}'::jsonb)",
                configuration_id,
            )
            for index, snapshot_id in enumerate(snapshots):
                await connection.execute(
                    """
                    INSERT INTO snapshots (id, name, configuration_id, configuration, code_revision)
                    VALUES ($1, $2, 'fixture', '{}'::jsonb, 'fixture')
                    """,
                    snapshot_id,
                    f"retention-{snapshot_id}",
                )
                generation = index + 1
                state = ("published", "building", "verified", "failed", "building")[
                    index
                ]
                await connection.execute(
                    """
                    INSERT INTO index_generations
                        (collection_id, configuration_id, generation, snapshot_id,
                         parent_generation, manifest_sha256, state, point_count)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    """,
                    collection_id,
                    configuration_id,
                    generation,
                    snapshot_id,
                    None if generation == 1 else generation - 1,
                    "a" * 64,
                    state,
                    generation * 10,
                )
            await connection.execute(
                """
                INSERT INTO index_generation_pointers
                    (collection_id, configuration_id, published_generation)
                VALUES ($1, $2, 1)
                """,
                collection_id,
                configuration_id,
            )
            await connection.execute(
                "INSERT INTO collections (id, name) VALUES ($1, $2)",
                unpublished_collection_id,
                f"retention-{unpublished_collection_id}",
            )
            await connection.execute(
                "INSERT INTO index_configurations (configuration_id, configuration) VALUES ($1, '{}'::jsonb)",
                unpublished_configuration_id,
            )
            await connection.execute(
                """
                INSERT INTO snapshots (id, name, configuration_id, configuration, code_revision)
                VALUES ($1, $2, 'fixture', '{}'::jsonb, 'fixture')
                """,
                unpublished_snapshot_id,
                f"retention-{unpublished_snapshot_id}",
            )
            await connection.execute(
                """
                INSERT INTO index_generations
                    (collection_id, configuration_id, generation, snapshot_id,
                     parent_generation, manifest_sha256, state, point_count)
                VALUES ($1, $2, 1, $3, NULL, $4, 'building', 6)
                """,
                unpublished_collection_id,
                unpublished_configuration_id,
                unpublished_snapshot_id,
                "b" * 64,
            )
        try:
            rows = await unpublished_generations(pool)
            found = [row for row in rows if row.collection_id == collection_id]
            assert [(row.generation, row.state, row.point_count) for row in found] == [
                (2, "building", 20),
                (3, "verified", 30),
                (4, "failed", 40),
                (5, "building", 50),
            ]
            assert any(
                row.collection_id == unpublished_collection_id
                and row.configuration_id == unpublished_configuration_id
                and row.generation == 1
                and row.state == "building"
                and row.point_count == 6
                for row in rows
            )
        finally:
            async with pool.acquire() as connection:
                await connection.execute(
                    "DELETE FROM index_generation_pointers WHERE collection_id = $1",
                    collection_id,
                )
                await connection.execute(
                    "DELETE FROM index_generations WHERE collection_id = $1",
                    collection_id,
                )
                await connection.execute(
                    "DELETE FROM collections WHERE id = $1", collection_id
                )
                await connection.execute(
                    "DELETE FROM index_generations WHERE collection_id = $1",
                    unpublished_collection_id,
                )
                await connection.execute(
                    "DELETE FROM collections WHERE id = $1",
                    unpublished_collection_id,
                )
                await connection.execute(
                    "DELETE FROM snapshots WHERE id = ANY($1::uuid[])",
                    [*snapshots, unpublished_snapshot_id],
                )
                await connection.execute(
                    "DELETE FROM index_configurations WHERE configuration_id = $1",
                    configuration_id,
                )
                await connection.execute(
                    "DELETE FROM index_configurations WHERE configuration_id = $1",
                    unpublished_configuration_id,
                )

    _with_database(exercise)


def _with_database(operation) -> None:
    assert TEST_DATABASE_URL is not None
    assert urlparse(TEST_DATABASE_URL).path.removeprefix("/") == "research_test", (
        "integration tests require the isolated research_test database"
    )

    async def run() -> None:
        await apply_migrations(TEST_DATABASE_URL)
        pool = await asyncpg.create_pool(TEST_DATABASE_URL, min_size=1, max_size=2)
        try:
            await operation(pool)
        finally:
            await pool.close()

    asyncio.run(run())
