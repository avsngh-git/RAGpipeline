"""Gate D scripted cases for online discovery and ingestion (P35-29)."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Mapping
from urllib.parse import urlparse
from uuid import uuid4

import pytest

from research_platform.evaluation.phase35_regression import OFFLINE_CASES

TEST_DATABASE_URL = os.environ.get("RESEARCH_PLATFORM_TEST_DATABASE_URL")


@pytest.mark.anyio
@pytest.mark.parametrize("case", OFFLINE_CASES, ids=lambda case: case.__name__)
async def test_offline_case(case) -> None:
    result = await case()

    assert result.passed, "; ".join(result.mismatches)


def test_seven_gate_d_cases_are_covered() -> None:
    # Six offline cases plus the PostgreSQL worker-crash case below.
    assert len(OFFLINE_CASES) == 6


@pytest.mark.integration
@pytest.mark.skipif(
    not TEST_DATABASE_URL, reason="requires the dedicated disposable PostgreSQL service"
)
def test_worker_crash_lease_is_reclaimed_and_completes_once() -> None:
    """4. A crashed worker's lease expires; a second worker completes it once."""
    import asyncpg

    from research_platform.ingestion.generation_registry import GenerationRegistry
    from research_platform.persistence.migrations import apply_migrations
    from research_platform.worker.main import run_worker
    from research_platform.worker.queue import IngestionQueue, IngestionRequest

    assert TEST_DATABASE_URL is not None
    assert urlparse(TEST_DATABASE_URL).path.removeprefix("/") == "research_test"

    class CountingHandler:
        def __init__(self) -> None:
            self.calls = 0

        async def handle(
            self, request: IngestionRequest
        ) -> tuple[str, Mapping[str, object]]:
            self.calls += 1
            return "succeeded", {"outcomes": [], "generation": None}

    async def exercise() -> None:
        await apply_migrations(TEST_DATABASE_URL)
        pool = await asyncpg.create_pool(TEST_DATABASE_URL, min_size=1, max_size=4)
        try:
            collection_id = await GenerationRegistry(pool).ensure_collection(
                f"gate-d-{uuid4().hex[:12]}"
            )
            queue = IngestionQueue(pool)
            async with pool.acquire() as connection:
                # Other tests may leave claimable requests in the disposable database.
                await connection.execute(
                    """
                    UPDATE ingestion_requests
                    SET status = 'failed', claimed_by = NULL, lease_expires_at = NULL
                    WHERE status IN ('pending', 'claimed')
                    """
                )
                async with connection.transaction():
                    request_id = await queue.enqueue(
                        connection,
                        collection_id=collection_id,
                        run_id=None,
                        requested_by="terminal",
                        paper_ids=("W501",),
                    )
            # Worker A claims and then dies without heartbeats or completion.
            crashed = await queue.claim_next("worker-a", lease_seconds=0.2)
            assert crashed is not None and crashed.id == request_id
            await asyncio.sleep(0.4)

            handler = CountingHandler()
            stop = asyncio.Event()
            worker = asyncio.create_task(
                run_worker(
                    queue, handler, worker_id="worker-b", poll_seconds=0.05, stop=stop
                )
            )
            for _ in range(100):
                if (await queue.get(request_id)).status == "succeeded":
                    break
                await asyncio.sleep(0.05)
            stop.set()
            await asyncio.wait_for(worker, timeout=5)

            completed = await queue.get(request_id)
            assert completed.status == "succeeded"
            assert completed.attempts == 2
            assert handler.calls == 1
            with pytest.raises(RuntimeError, match="no longer owns"):
                await queue.complete(request_id, "worker-a", status="failed", result={})
            assert (await queue.get(request_id)).status == "succeeded"
        finally:
            await pool.close()

    asyncio.run(exercise())
