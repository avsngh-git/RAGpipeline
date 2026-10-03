"""PostgreSQL coverage for persisted research run records."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable
from datetime import timedelta
from urllib.parse import urlparse
from uuid import UUID, uuid4

import asyncpg
import pytest

from research_platform.llm.types import CallKind, ModelIdentity
from research_platform.persistence.migrations import apply_migrations
from research_platform.runs.contracts import (
    AnswerOutcome,
    ClaimResult,
    EvidenceCitation,
    FailureCategory,
    ResearchFilters,
    ResearchMode,
    ResearchRequest,
    RunBudgets,
    RunProvenance,
    RunStatus,
    RunUsage,
    SupportLabel,
)
from research_platform.runs.repository import (
    EvidenceRecord,
    InvalidRunTransition,
    RunNotFound,
    RunRepository,
    ToolCallRecord,
)

TEST_DATABASE_URL = os.environ.get("RESEARCH_PLATFORM_TEST_DATABASE_URL")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not TEST_DATABASE_URL,
        reason="requires the dedicated disposable PostgreSQL service",
    ),
]


def test_migration_016_applies_and_is_recorded() -> None:
    async def exercise(
        _pool: asyncpg.Pool,
        _repo: RunRepository,
        _snapshot_id: UUID,
        _paper_id: str,
        _chunk_id: str,
    ) -> None:
        assert TEST_DATABASE_URL is not None
        connection = await asyncpg.connect(TEST_DATABASE_URL)
        try:
            applied = await connection.fetchval(
                "SELECT 1 FROM schema_migrations WHERE version = '016_phase3_research_runs'"
            )
            evidence_table = await connection.fetchval(
                """
                SELECT to_regclass('public.research_run_evidence') IS NOT NULL
                """
            )
            assert applied == 1
            assert evidence_table
        finally:
            await connection.close()

    _with_database(exercise)


def test_create_get_and_list_by_status() -> None:
    async def exercise(
        _pool: asyncpg.Pool,
        repo: RunRepository,
        snapshot_id: UUID,
        _paper_id: str,
        _chunk_id: str,
    ) -> None:
        request = _request(snapshot_id)
        run_id = await repo.create_run(request)
        stored = await repo.get_run(run_id)
        queued = await repo.list_runs([RunStatus.QUEUED])
        completed = await repo.list_runs([RunStatus.COMPLETED])

        assert stored.run_id == run_id
        assert stored.status is RunStatus.QUEUED
        assert stored.mode is request.mode
        assert stored.request == request
        assert run_id in {run.run_id for run in queued}
        assert run_id not in {run.run_id for run in completed}

    _with_database(exercise)


def test_mark_running_sets_provenance_and_keeps_started_at_on_resume() -> None:
    async def exercise(
        _pool: asyncpg.Pool,
        repo: RunRepository,
        snapshot_id: UUID,
        _paper_id: str,
        _chunk_id: str,
    ) -> None:
        run_id = await repo.create_run(_request(snapshot_id))
        provenance = _provenance(snapshot_id)
        await repo.mark_running(run_id, provenance=provenance)
        first = await repo.get_run(run_id)
        await repo.mark_running(run_id, provenance=provenance)
        resumed = await repo.get_run(run_id)

        assert first.status is RunStatus.RUNNING
        assert first.configuration_id == provenance.configuration_id
        assert first.started_at is not None
        assert resumed.started_at == first.started_at

    _with_database(exercise)


def test_invalid_transitions_raise() -> None:
    async def exercise(
        _pool: asyncpg.Pool,
        repo: RunRepository,
        snapshot_id: UUID,
        _paper_id: str,
        _chunk_id: str,
    ) -> None:
        run_id = await repo.create_run(_request(snapshot_id))
        with pytest.raises(InvalidRunTransition):
            await repo.complete_run(
                run_id,
                answer="Answer",
                outcome=AnswerOutcome.ANSWERED,
                claims=(),
                usage=RunUsage(),
            )
        with pytest.raises(RunNotFound):
            await repo.get_run(uuid4())
        with pytest.raises(RunNotFound):
            await repo.mark_running(uuid4(), provenance=_provenance(snapshot_id))

    _with_database(exercise)


def test_tool_call_and_evidence_writes_are_idempotent() -> None:
    async def exercise(
        _pool: asyncpg.Pool,
        repo: RunRepository,
        snapshot_id: UUID,
        paper_id: str,
        chunk_id: str,
    ) -> None:
        run_id = await repo.create_run(_request(snapshot_id))
        tool_call = ToolCallRecord(
            ordinal=1,
            tool_name="search_evidence",
            arguments={"query": "retrieval"},
            status="succeeded",
            result_summary={"count": 1},
            duration_ms=12.5,
        )
        evidence = EvidenceRecord(
            handle="E1",
            chunk_id=chunk_id,
            paper_id=paper_id,
            text="A copied research passage.",
            metadata={"title": "Fixture paper", "publication_year": 2025},
        )
        await repo.append_tool_call(run_id, tool_call)
        await repo.append_tool_call(run_id, tool_call)
        await repo.save_evidence(run_id, [evidence])
        await repo.save_evidence(run_id, [evidence])

        calls = await _pool.fetch(
            "SELECT count(*) FROM tool_calls WHERE run_id = $1", run_id
        )
        loaded = await repo.load_evidence(run_id)
        selected = await repo.load_evidence(run_id, ["E1"])

        assert calls[0]["count"] == 1
        assert loaded == {"E1": evidence}
        assert selected == loaded

    _with_database(exercise)


def test_complete_run_rewrites_claims_and_builds_view() -> None:
    async def exercise(
        _pool: asyncpg.Pool,
        repo: RunRepository,
        snapshot_id: UUID,
        paper_id: str,
        chunk_id: str,
    ) -> None:
        run_id = await repo.create_run(_request(snapshot_id))
        await repo.mark_running(run_id, provenance=_provenance(snapshot_id))
        await repo.save_evidence(
            run_id,
            [
                EvidenceRecord(
                    handle="E1",
                    chunk_id=chunk_id,
                    paper_id=paper_id,
                    text="Evidence passage.",
                    metadata={"title": "Fixture paper", "publication_year": 2025},
                )
            ],
        )
        async with _pool.acquire() as connection:
            prior_claim_id = await connection.fetchval(
                """
                INSERT INTO claims (run_id, claim_text, ordinal, support)
                VALUES ($1, 'Earlier persisted claim', 1, 'supported')
                RETURNING id
                """,
                run_id,
            )
            await connection.execute(
                "INSERT INTO claim_evidence (claim_id, chunk_id, handle) VALUES ($1, $2, $3)",
                prior_claim_id,
                chunk_id,
                "E1",
            )
        replacement = ClaimResult(
            claim_id="claim-1",
            text="The resumed answer replaces the earlier claim.",
            evidence=(
                EvidenceCitation(handle="E1", chunk_id=chunk_id, paper_id=paper_id),
            ),
            support=SupportLabel.PARTIAL,
        )
        await repo.complete_run(
            run_id,
            answer="Second answer",
            outcome=AnswerOutcome.PARTIALLY_SUPPORTED,
            claims=[replacement],
            usage=RunUsage(model_calls=2, resumes=1),
        )
        view = await repo.get_run_view(run_id)
        claim_count = await _pool.fetchval(
            "SELECT count(*) FROM claims WHERE run_id = $1", run_id
        )

        assert view.status is RunStatus.COMPLETED
        assert view.answer == "Second answer"
        assert view.answer_outcome is AnswerOutcome.PARTIALLY_SUPPORTED
        assert view.claims == (replacement,)
        assert view.papers[0].paper_id == paper_id
        assert view.papers[0].title == "Fixture paper"
        assert claim_count == 1

    _with_database(exercise)


def test_fail_run_truncates_message_and_view_has_category() -> None:
    async def exercise(
        _pool: asyncpg.Pool,
        repo: RunRepository,
        snapshot_id: UUID,
        _paper_id: str,
        _chunk_id: str,
    ) -> None:
        run_id = await repo.create_run(_request(snapshot_id))
        await repo.mark_running(run_id, provenance=_provenance(snapshot_id))
        await repo.fail_run(
            run_id,
            category=FailureCategory.MODEL_UNAVAILABLE,
            message="x" * 700,
            usage=RunUsage(model_calls=1),
        )
        view = await repo.get_run_view(run_id)

        assert view.status is RunStatus.FAILED
        assert view.failure_category is FailureCategory.MODEL_UNAVAILABLE
        assert view.error_message == "x" * 500

    _with_database(exercise)


def test_fail_run_accepts_queued_but_rejects_terminal_run() -> None:
    async def exercise(
        _pool: asyncpg.Pool,
        repo: RunRepository,
        snapshot_id: UUID,
        _paper_id: str,
        _chunk_id: str,
    ) -> None:
        run_id = await repo.create_run(_request(snapshot_id))
        await repo.fail_run(
            run_id,
            category=FailureCategory.MODEL_UNAVAILABLE,
            message="identity unavailable",
            usage=RunUsage(),
        )
        view = await repo.get_run_view(run_id)

        assert view.status is RunStatus.FAILED
        assert view.failure_category is FailureCategory.MODEL_UNAVAILABLE
        assert view.error_message == "identity unavailable"
        assert view.completed_at is not None
        with pytest.raises(InvalidRunTransition):
            await repo.fail_run(
                run_id,
                category=FailureCategory.INTERNAL,
                message="duplicate failure",
                usage=RunUsage(),
            )

    _with_database(exercise)


def test_prune_removes_only_old_terminal_runs() -> None:
    async def exercise(
        _pool: asyncpg.Pool,
        repo: RunRepository,
        snapshot_id: UUID,
        _paper_id: str,
        _chunk_id: str,
    ) -> None:
        old_completed = await repo.create_run(_request(snapshot_id))
        await repo.mark_running(old_completed, provenance=_provenance(snapshot_id))
        await repo.complete_run(
            old_completed,
            answer="Done",
            outcome=AnswerOutcome.INSUFFICIENT_EVIDENCE,
            claims=(),
            usage=RunUsage(),
        )
        old_failed = await repo.create_run(_request(snapshot_id))
        await repo.mark_running(old_failed, provenance=_provenance(snapshot_id))
        await repo.fail_run(
            old_failed,
            category=FailureCategory.TIMEOUT,
            message="timeout",
            usage=RunUsage(),
        )
        queued = await repo.create_run(_request(snapshot_id))
        async with _pool.acquire() as connection:
            await connection.execute(
                "UPDATE research_runs SET completed_at = now() - interval '3 days' "
                "WHERE id = ANY($1::uuid[])",
                [old_completed, old_failed],
            )

        removed = await repo.prune(older_than=timedelta(days=1))

        assert set(removed) == {old_completed, old_failed}
        assert (await repo.get_run(queued)).status is RunStatus.QUEUED

    _with_database(exercise)


def test_record_resume_and_add_active_seconds_accumulate() -> None:
    async def exercise(
        _pool: asyncpg.Pool,
        repo: RunRepository,
        snapshot_id: UUID,
        _paper_id: str,
        _chunk_id: str,
    ) -> None:
        run_id = await repo.create_run(_request(snapshot_id))
        await repo.mark_running(run_id, provenance=_provenance(snapshot_id))

        assert await repo.record_resume(run_id) == 1
        assert await repo.record_resume(run_id) == 2
        assert await repo.add_active_seconds(run_id, 3.25) == 3.25
        assert await repo.add_active_seconds(run_id, 2.0) == 5.25

    _with_database(exercise)


def _with_database(
    operation: Callable[[asyncpg.Pool, RunRepository, UUID, str, str], Awaitable[None]],
) -> None:
    assert TEST_DATABASE_URL is not None
    assert urlparse(TEST_DATABASE_URL).path.removeprefix("/") == "research_test", (
        "integration tests require the isolated research_test database"
    )

    async def exercise() -> None:
        await apply_migrations(TEST_DATABASE_URL)
        pool = await asyncpg.create_pool(TEST_DATABASE_URL, min_size=1, max_size=2)
        snapshot_id = uuid4()
        paper_id = f"fixture-{uuid4().hex}"
        document_id = uuid4()
        chunk_id = f"chunk-{uuid4().hex}"
        try:
            async with pool.acquire() as connection:
                await connection.execute(
                    """
                    INSERT INTO snapshots (id, name, configuration_id, configuration,
                                          code_revision)
                    VALUES ($1, $2, 'test-config', '{}'::jsonb, 'test-revision')
                    """,
                    snapshot_id,
                    f"run-repository-{snapshot_id}",
                )
                await connection.execute(
                    """
                    INSERT INTO papers (id, title, publication_year, metadata)
                    VALUES ($1, 'Fixture paper', 2025, '{}'::jsonb)
                    """,
                    paper_id,
                )
                await connection.execute(
                    """
                    INSERT INTO documents (id, paper_id, source_type, version)
                    VALUES ($1, $2, 'integration', 'v1')
                    """,
                    document_id,
                    paper_id,
                )
                await connection.execute(
                    "INSERT INTO chunks (id, document_id, text) VALUES ($1, $2, 'passage')",
                    chunk_id,
                    document_id,
                )
                await connection.execute(
                    """
                    INSERT INTO snapshot_items
                        (snapshot_id, paper_id, document_id, selection_reason)
                    VALUES ($1, $2, $3, 'integration fixture')
                    """,
                    snapshot_id,
                    paper_id,
                    document_id,
                )
            await operation(pool, RunRepository(pool), snapshot_id, paper_id, chunk_id)
        finally:
            async with pool.acquire() as connection:
                await connection.execute(
                    "DELETE FROM research_runs WHERE snapshot_id = $1", snapshot_id
                )
                await connection.execute(
                    "DELETE FROM snapshot_items WHERE snapshot_id = $1", snapshot_id
                )
                await connection.execute(
                    "DELETE FROM snapshots WHERE id = $1", snapshot_id
                )
                await connection.execute(
                    "DELETE FROM documents WHERE id = $1", document_id
                )
                await connection.execute("DELETE FROM papers WHERE id = $1", paper_id)
            await pool.close()

    asyncio.run(exercise())


def _request(snapshot_id: UUID) -> ResearchRequest:
    return ResearchRequest(
        question="What does the evidence show?",
        mode=ResearchMode.QUICK,
        snapshot_id=snapshot_id,
        filters=ResearchFilters(year_from=2020),
    )


def _provenance(snapshot_id: UUID) -> RunProvenance:
    return RunProvenance(
        snapshot_id=snapshot_id,
        retrieval_profile_id="profile-v10",
        configuration_id=f"sha256:{'b' * 64}",
        code_revision="test-revision",
        model=ModelIdentity(name="qwen", runtime="ollama", context_tokens=8192),
        thinking={CallKind.PLAN: False},
        prompt_versions={"system": "v1"},
        budgets=RunBudgets(),
        trace_id="trace-1",
    )
