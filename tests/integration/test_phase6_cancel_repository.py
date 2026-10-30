"""PostgreSQL coverage for principal-cancelled research runs."""

from __future__ import annotations

import asyncio
import os
from urllib.parse import urlparse
from uuid import uuid4

import asyncpg
import pytest

from research_platform.llm.types import CallKind, ModelIdentity
from research_platform.persistence.migrations import apply_migrations
from research_platform.runs.contracts import (
    FailureCategory,
    ResearchMode,
    ResearchRequest,
    RunBudgets,
    RunProvenance,
    RunUsage,
)
from research_platform.runs.repository import RunRepository

TEST_DATABASE_URL = os.environ.get("RESEARCH_PLATFORM_TEST_DATABASE_URL")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not TEST_DATABASE_URL,
        reason="requires the dedicated disposable PostgreSQL service",
    ),
]


def test_failure_category_accepts_cancelled_by_principal() -> None:
    assert TEST_DATABASE_URL is not None
    assert urlparse(TEST_DATABASE_URL).path.removeprefix("/") == "research_test", (
        "integration tests require the isolated research_test database"
    )

    async def exercise() -> None:
        await apply_migrations(TEST_DATABASE_URL)
        pool = await asyncpg.create_pool(TEST_DATABASE_URL, min_size=1, max_size=2)
        snapshot_id = uuid4()
        try:
            async with pool.acquire() as connection:
                constraint = await connection.fetchval(
                    """
                    SELECT conname FROM pg_constraint
                    WHERE conrelid = 'research_runs'::regclass
                      AND conname = 'research_runs_failure_category_check'
                    """
                )
                assert constraint == "research_runs_failure_category_check"
                await connection.execute(
                    """
                    INSERT INTO snapshots (id, name, configuration_id, configuration,
                                          code_revision)
                    VALUES ($1, $2, 'test-config', '{}'::jsonb, 'test-revision')
                    """,
                    snapshot_id,
                    f"cancel-test-{snapshot_id}",
                )
            repository = RunRepository(pool)
            run_id = await repository.create_run(
                ResearchRequest(
                    question="Synthetic cancellation integration question",
                    mode=ResearchMode.QUICK,
                    snapshot_id=snapshot_id,
                )
            )
            await repository.mark_running(
                run_id,
                provenance=RunProvenance(
                    snapshot_id=snapshot_id,
                    retrieval_profile_id="profile-v1",
                    configuration_id=f"sha256:{'b' * 64}",
                    code_revision="test-revision",
                    model=ModelIdentity(
                        name="qwen", runtime="ollama", context_tokens=8192
                    ),
                    thinking={CallKind.PLAN: False},
                    prompt_versions={"system": "v1"},
                    budgets=RunBudgets(),
                    trace_id="trace-test-cancel",
                ),
            )
            await repository.fail_run(
                run_id,
                category=FailureCategory.CANCELLED_BY_PRINCIPAL,
                message="cancelled_by_principal",
                usage=RunUsage(),
            )
            stored = await repository.get_run_view(run_id)
            assert stored.failure_category is FailureCategory.CANCELLED_BY_PRINCIPAL
        finally:
            async with pool.acquire() as connection:
                await connection.execute(
                    "DELETE FROM research_runs WHERE snapshot_id = $1", snapshot_id
                )
                await connection.execute(
                    "DELETE FROM snapshots WHERE id = $1", snapshot_id
                )
            await pool.close()

    asyncio.run(exercise())
