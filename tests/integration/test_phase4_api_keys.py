"""PostgreSQL coverage for API keys and run principals."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable
from urllib.parse import urlparse

import asyncpg
import pytest

from research_platform.auth.keys import PostgresApiKeyStore, Scope, hash_api_key
from research_platform.persistence.migrations import apply_migrations

TEST_DATABASE_URL = os.environ.get("RESEARCH_PLATFORM_TEST_DATABASE_URL")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not TEST_DATABASE_URL,
        reason="requires the dedicated disposable PostgreSQL service",
    ),
]


def test_migration_026_adds_principal_default() -> None:
    async def exercise(pool: asyncpg.Pool) -> None:
        run_id = await pool.fetchval(
            """INSERT INTO research_runs (question, status, mode, request)
               VALUES ('synthetic question', 'queued', 'quick', '{}'::jsonb)
               RETURNING id"""
        )
        try:
            principal = await pool.fetchval(
                "SELECT principal FROM research_runs WHERE id = $1", run_id
            )
            assert principal == "legacy-local"
        finally:
            await pool.execute("DELETE FROM research_runs WHERE id = $1", run_id)

    _with_database(exercise)


def test_postgres_create_authenticate_revoke() -> None:
    async def exercise(pool: asyncpg.Pool) -> None:
        store = PostgresApiKeyStore(pool)
        record, key = await store.create(
            "integration-test", [Scope.READ, Scope.RESEARCH]
        )
        try:
            principal = await store.authenticate(key)
            listed = await store.list()

            assert principal is not None
            assert principal.name == "integration-test"
            assert principal.scopes == frozenset({Scope.READ, Scope.RESEARCH})
            assert principal.key_id == record.key_id
            assert record in listed
            assert await store.revoke(record.key_id)
            assert await store.authenticate(key) is None
            assert not await store.revoke(record.key_id)
        finally:
            await pool.execute("DELETE FROM api_keys WHERE key_id = $1", record.key_id)

    _with_database(exercise)


def test_plain_key_not_stored() -> None:
    async def exercise(pool: asyncpg.Pool) -> None:
        record, key = await PostgresApiKeyStore(pool).create(
            "integration-test", [Scope.READ]
        )
        try:
            serialized = await pool.fetchval(
                "SELECT to_jsonb(api_keys)::text FROM api_keys WHERE key_id = $1",
                record.key_id,
            )
            assert key not in serialized
            assert hash_api_key(key) in serialized
        finally:
            await pool.execute("DELETE FROM api_keys WHERE key_id = $1", record.key_id)

    _with_database(exercise)


def test_invalid_scope_rejected_by_database() -> None:
    async def exercise(pool: asyncpg.Pool) -> None:
        with pytest.raises(asyncpg.CheckViolationError):
            async with pool.acquire() as connection:
                async with connection.transaction():
                    await connection.execute(
                        """INSERT INTO api_keys (principal, key_prefix, key_sha256, scopes)
                           VALUES ('integration-test', 'abcdefgh', $1, ARRAY['invalid'])""",
                        "0" * 64,
                    )

    _with_database(exercise)


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
