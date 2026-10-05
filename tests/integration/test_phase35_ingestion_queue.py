"""PostgreSQL integration coverage for durable ingestion requests."""

import asyncio
import os
from urllib.parse import urlparse
from uuid import UUID, uuid4

import asyncpg
import pytest

from research_platform.persistence.migrations import apply_migrations
from research_platform.worker.gpu import gpu_lock
from research_platform.worker.queue import IngestionQueue

TEST_DATABASE_URL = os.environ.get("RESEARCH_PLATFORM_TEST_DATABASE_URL")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not TEST_DATABASE_URL,
        reason="requires the dedicated disposable PostgreSQL service",
    ),
]


async def _database_pool() -> asyncpg.Pool:
    assert TEST_DATABASE_URL is not None
    assert urlparse(TEST_DATABASE_URL).path.removeprefix("/") == "research_test"
    await apply_migrations(TEST_DATABASE_URL)
    return await asyncpg.create_pool(TEST_DATABASE_URL, min_size=1, max_size=4)


async def _collection_id(pool: asyncpg.Pool) -> UUID:
    async with pool.acquire() as connection:
        return await connection.fetchval(
            "INSERT INTO collections (name) VALUES ($1) RETURNING id",
            f"worker-test-{uuid4().hex}",
        )


async def _cleanup(pool: asyncpg.Pool, collection_id: UUID) -> None:
    async with pool.acquire() as connection:
        await connection.execute(
            "DELETE FROM ingestion_requests WHERE collection_id = $1", collection_id
        )
        await connection.execute("DELETE FROM collections WHERE id = $1", collection_id)


def test_enqueue_inside_caller_transaction_rolls_back() -> None:
    assert TEST_DATABASE_URL is not None

    async def exercise() -> None:
        pool = await _database_pool()
        collection_id = await _collection_id(pool)
        request_id = None
        try:
            async with pool.acquire() as connection:
                try:
                    async with connection.transaction():
                        request_id = await IngestionQueue.enqueue(
                            connection,
                            collection_id=collection_id,
                            run_id=None,
                            requested_by="api",
                            paper_ids=("W1",),
                        )
                        raise RuntimeError("rollback fixture")
                except RuntimeError as error:
                    assert str(error) == "rollback fixture"
            assert request_id is not None
            queue = IngestionQueue(pool)
            with pytest.raises(KeyError):
                await queue.get(request_id)
        finally:
            await _cleanup(pool, collection_id)
            await pool.close()

    asyncio.run(exercise())


def test_two_workers_never_claim_the_same_request() -> None:
    assert TEST_DATABASE_URL is not None

    async def exercise() -> None:
        pool = await _database_pool()
        collection_id = await _collection_id(pool)
        queue = IngestionQueue(pool)
        try:
            async with pool.acquire() as connection:
                first_id = await queue.enqueue(
                    connection,
                    collection_id=collection_id,
                    run_id=None,
                    requested_by="terminal",
                    paper_ids=("W1",),
                )
                second_id = await queue.enqueue(
                    connection,
                    collection_id=collection_id,
                    run_id=None,
                    requested_by="terminal",
                    paper_ids=("W2",),
                )
            first, second = await asyncio.gather(
                queue.claim_next("worker-a"), queue.claim_next("worker-b")
            )
            claimed_ids = {request.id for request in (first, second) if request}
            assert claimed_ids == {first_id, second_id}
            assert first is not None and second is not None
            assert first.id != second.id
        finally:
            await _cleanup(pool, collection_id)
            await pool.close()

    asyncio.run(exercise())


def test_expired_lease_is_reclaimed() -> None:
    assert TEST_DATABASE_URL is not None

    async def exercise() -> None:
        pool = await _database_pool()
        collection_id = await _collection_id(pool)
        queue = IngestionQueue(pool)
        try:
            async with pool.acquire() as connection:
                request_id = await queue.enqueue(
                    connection,
                    collection_id=collection_id,
                    run_id=None,
                    requested_by="run",
                    paper_ids=("W1",),
                )
            first = await queue.claim_next("worker-a", lease_seconds=0.05)
            await asyncio.sleep(0.1)
            second = await queue.claim_next("worker-b", lease_seconds=30)
            assert first is not None and second is not None
            assert second.id == request_id
            assert second.attempts == 2
        finally:
            await _cleanup(pool, collection_id)
            await pool.close()

    asyncio.run(exercise())


def test_stale_worker_cannot_complete() -> None:
    assert TEST_DATABASE_URL is not None

    async def exercise() -> None:
        pool = await _database_pool()
        collection_id = await _collection_id(pool)
        queue = IngestionQueue(pool)
        try:
            async with pool.acquire() as connection:
                request_id = await queue.enqueue(
                    connection,
                    collection_id=collection_id,
                    run_id=None,
                    requested_by="api",
                    paper_ids=("W1",),
                )
            assert await queue.claim_next("worker-a", lease_seconds=0.05)
            await asyncio.sleep(0.1)
            assert await queue.claim_next("worker-b", lease_seconds=30)
            with pytest.raises(RuntimeError, match="no longer owns"):
                await queue.complete(
                    request_id, "worker-a", status="succeeded", result={}
                )
            await queue.complete(
                request_id, "worker-b", status="succeeded", result={"ok": True}
            )
        finally:
            await _cleanup(pool, collection_id)
            await pool.close()

    asyncio.run(exercise())


def test_waiting_status_is_allowed_on_runs() -> None:
    assert TEST_DATABASE_URL is not None

    async def exercise() -> None:
        pool = await _database_pool()
        run_id = uuid4()
        try:
            async with pool.acquire() as connection:
                await connection.execute(
                    "INSERT INTO research_runs (id, question, status, mode) "
                    "VALUES ($1, 'integration fixture', 'waiting_for_ingestion', 'quick')",
                    run_id,
                )
                await connection.execute(
                    "DELETE FROM research_runs WHERE id = $1", run_id
                )
        finally:
            await pool.close()

    asyncio.run(exercise())


def test_gpu_lock_is_exclusive() -> None:
    assert TEST_DATABASE_URL is not None

    async def exercise() -> None:
        pool = await _database_pool()
        second_acquired = asyncio.Event()
        try:
            async with gpu_lock(pool):

                async def wait_for_lock() -> None:
                    async with gpu_lock(pool):
                        second_acquired.set()

                second = asyncio.create_task(wait_for_lock())
                await asyncio.sleep(0.05)
                assert not second_acquired.is_set()
            await asyncio.wait_for(second, timeout=2)
            assert second_acquired.is_set()
        finally:
            await pool.close()

    asyncio.run(exercise())
