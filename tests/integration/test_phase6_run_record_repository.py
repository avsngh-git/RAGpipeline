"""PostgreSQL coverage for timestamps on run record calls."""

from __future__ import annotations

import asyncio
import os
from urllib.parse import urlparse

import asyncpg
import pytest

from research_platform.llm.types import CallKind
from research_platform.persistence.migrations import apply_migrations
from research_platform.runs.contracts import ResearchMode, ResearchRequest
from research_platform.runs.llm_records import LLMCallRecord
from research_platform.runs.repository import RunRepository, ToolCallRecord

TEST_DATABASE_URL = os.environ.get("RESEARCH_PLATFORM_TEST_DATABASE_URL")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not TEST_DATABASE_URL,
        reason="requires the dedicated disposable PostgreSQL service",
    ),
]


def test_repository_fills_recorded_at() -> None:
    assert TEST_DATABASE_URL is not None
    assert urlparse(TEST_DATABASE_URL).path.removeprefix("/") == "research_test", (
        "integration tests require the isolated research_test database"
    )

    async def exercise() -> None:
        await apply_migrations(TEST_DATABASE_URL)
        pool = await asyncpg.create_pool(TEST_DATABASE_URL, min_size=1, max_size=2)
        run_id = None
        try:
            repo = RunRepository(pool)
            run_id = await repo.create_run(
                ResearchRequest(question="Synthetic zq7731", mode=ResearchMode.QUICK)
            )
            await repo.append_tool_call(
                run_id,
                ToolCallRecord(
                    ordinal=1,
                    tool_name="synthetic_tool",
                    arguments={},
                    status="succeeded",
                    result_summary={},
                    duration_ms=1,
                ),
            )
            await repo.append_llm_call(
                run_id,
                LLMCallRecord(
                    kind=CallKind.PLAN,
                    status="succeeded",
                    model_name="synthetic-model",
                    think=False,
                    attempts=1,
                    duration_ms=1,
                ),
            )
            tool_calls = await repo.list_tool_calls(run_id)
            llm_calls = await repo.list_llm_calls(run_id)
            assert tool_calls[0].recorded_at is not None
            assert tool_calls[0].recorded_at.tzinfo is not None
            assert llm_calls[0].recorded_at is not None
            assert llm_calls[0].recorded_at.tzinfo is not None
        finally:
            if run_id is not None:
                async with pool.acquire() as connection:
                    await connection.execute(
                        "DELETE FROM research_runs WHERE id = $1", run_id
                    )
            await pool.close()

    asyncio.run(exercise())
