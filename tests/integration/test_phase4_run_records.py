"""PostgreSQL coverage for Phase 4 run records (ADR-0026)."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable
from urllib.parse import urlparse
from uuid import uuid4

import asyncpg
import pytest

from research_platform.persistence.migrations import apply_migrations
from research_platform.runs.contracts import configuration_id
from research_platform.runs.repository import ConfigurationNotFound, RunRepository

TEST_DATABASE_URL = os.environ.get("RESEARCH_PLATFORM_TEST_DATABASE_URL")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not TEST_DATABASE_URL,
        reason="requires the dedicated disposable PostgreSQL service",
    ),
]


def _payload() -> dict[str, object]:
    return {
        "provenance_version": 2,
        "nonce": uuid4().hex,
        "mode": "deep_research",
        "budgets": {"max_active_seconds": 1800.0, "max_tool_calls": 12},
        "decoding": {
            "seed": 20261001,
            "context_tokens": 32768,
            "timeout_seconds": 1200.0,
            "temperature": None,
        },
        "filters": {"year_from": None, "year_to": 2024},
        "prompt_fingerprints": {"plan": "a" * 64},
        "values": [1, 0.5, "x", None, True],
    }


def _with_repository(
    operation: Callable[[asyncpg.Pool, RunRepository, list[str]], Awaitable[None]],
) -> None:
    assert TEST_DATABASE_URL is not None
    assert urlparse(TEST_DATABASE_URL).path.removeprefix("/") == "research_test", (
        "integration tests require the isolated research_test database"
    )

    async def exercise() -> None:
        await apply_migrations(TEST_DATABASE_URL)
        pool = await asyncpg.create_pool(TEST_DATABASE_URL, min_size=1, max_size=2)
        created: list[str] = []
        try:
            await operation(pool, RunRepository(pool), created)
        finally:
            async with pool.acquire() as connection:
                await connection.execute(
                    "DELETE FROM run_configurations WHERE configuration_id = ANY($1)",
                    created,
                )
            await pool.close()

    asyncio.run(exercise())


def test_migration_022_creates_run_configurations() -> None:
    async def exercise(
        pool: asyncpg.Pool, _repo: RunRepository, _created: list[str]
    ) -> None:
        async with pool.acquire() as connection:
            applied = await connection.fetchval(
                "SELECT 1 FROM schema_migrations WHERE version = '022_run_configurations'"
            )
            table = await connection.fetchval(
                "SELECT to_regclass('public.run_configurations') IS NOT NULL"
            )
        assert applied == 1
        assert table

    _with_repository(exercise)


def test_round_trip_preserves_configuration_id() -> None:
    async def exercise(
        _pool: asyncpg.Pool, repo: RunRepository, created: list[str]
    ) -> None:
        payload = _payload()
        expected = configuration_id(payload)
        created.append(expected)

        await repo.save_run_configuration(expected, payload, provenance_version=2)
        loaded = await repo.load_run_configuration(expected)

        assert loaded == payload
        assert configuration_id(loaded) == expected

    _with_repository(exercise)


def test_save_is_idempotent() -> None:
    async def exercise(
        pool: asyncpg.Pool, repo: RunRepository, created: list[str]
    ) -> None:
        payload = _payload()
        expected = configuration_id(payload)
        created.append(expected)

        await repo.save_run_configuration(expected, payload, provenance_version=2)
        await repo.save_run_configuration(expected, payload, provenance_version=2)

        async with pool.acquire() as connection:
            rows = await connection.fetchval(
                "SELECT count(*) FROM run_configurations WHERE configuration_id = $1",
                expected,
            )
        assert rows == 1

    _with_repository(exercise)


def test_save_rejects_wrong_id() -> None:
    async def exercise(
        _pool: asyncpg.Pool, repo: RunRepository, _created: list[str]
    ) -> None:
        with pytest.raises(ValueError, match="does not match"):
            await repo.save_run_configuration(
                "sha256:" + "0" * 64, _payload(), provenance_version=2
            )

    _with_repository(exercise)


def test_load_missing_raises() -> None:
    async def exercise(
        _pool: asyncpg.Pool, repo: RunRepository, _created: list[str]
    ) -> None:
        with pytest.raises(ConfigurationNotFound):
            await repo.load_run_configuration("sha256:" + uuid4().hex + uuid4().hex)

    _with_repository(exercise)
