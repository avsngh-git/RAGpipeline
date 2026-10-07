"""PostgreSQL coverage for Phase 4 run records (ADR-0026)."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable
from urllib.parse import urlparse
from uuid import uuid4

import asyncpg
import pytest

from research_platform.llm.contracts import ChatMessage
from research_platform.llm.types import CallKind
from research_platform.persistence.migrations import apply_migrations
from research_platform.runs.contracts import (
    AnswerOutcome,
    ClaimVerdict,
    DraftClaimOutcome,
    ResearchMode,
    ResearchRequest,
    RunUsage,
    SynthesisSummary,
    configuration_id,
)
from research_platform.runs.llm_records import LLMCallPayload, LLMCallRecord
from research_platform.runs.repository import (
    ConfigurationNotFound,
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
                    [value for value in created if value.startswith("sha256:")],
                )
                await connection.execute(
                    "DELETE FROM research_runs WHERE id::text = ANY($1)",
                    [value for value in created if not value.startswith("sha256:")],
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


def _call(kind: CallKind = CallKind.PLAN, **overrides: object) -> LLMCallRecord:
    values: dict[str, object] = {
        "kind": kind,
        "status": "succeeded",
        "model_name": "qwen",
        "think": True,
        "attempts": 2,
        "duration_ms": 1500.5,
        "options": {"seed": 7, "num_ctx": 32768},
        "prompt_version": "p3-plan-v1",
        "prompt_fingerprint": "a" * 64,
        "prompt_tokens": 1000,
        "output_tokens": 200,
        "thinking_chars": 4000,
        "trace_id": "0" * 32,
        "span_id": "1" * 16,
    }
    values.update(overrides)
    return LLMCallRecord(**values)  # type: ignore[arg-type]


async def _new_run(repo: RunRepository, created: list[str]):  # type: ignore[no-untyped-def]
    run_id = await repo.create_run(
        ResearchRequest(question="what helps", mode=ResearchMode.QUICK)
    )
    created.append(str(run_id))
    return run_id


def test_append_llm_calls_numbers_from_one() -> None:
    async def exercise(
        _pool: asyncpg.Pool, repo: RunRepository, created: list[str]
    ) -> None:
        run_id = await _new_run(repo, created)

        first = await repo.append_llm_call(run_id, _call())
        second = await repo.append_llm_call(
            run_id,
            _call(CallKind.SYNTHESIZE, status="failed", error_type="LLMTimeout"),
        )
        calls = await repo.list_llm_calls(run_id)

        assert (first, second) == (1, 2)
        assert [call.ordinal for call in calls] == [1, 2]
        assert calls[0].record == _call()
        assert calls[1].record.error_type == "LLMTimeout"

    _with_repository(exercise)


def test_payload_round_trip() -> None:
    async def exercise(
        _pool: asyncpg.Pool, repo: RunRepository, created: list[str]
    ) -> None:
        run_id = await _new_run(repo, created)
        payload = LLMCallPayload(
            messages=(
                ChatMessage("system", "rules ✓"),
                ChatMessage("user", 'question with "quotes"'),
            ),
            output='{"answer": "x"}',
            thinking="long thinking\nlines",
        )

        await repo.append_llm_call(run_id, _call(), payload)
        stored = (await repo.list_llm_calls(run_id, include_payloads=True))[0]

        assert stored.payload == payload

    _with_repository(exercise)


def test_payload_hidden_unless_requested() -> None:
    async def exercise(
        _pool: asyncpg.Pool, repo: RunRepository, created: list[str]
    ) -> None:
        run_id = await _new_run(repo, created)
        await repo.append_llm_call(
            run_id, _call(), LLMCallPayload(messages=(ChatMessage("user", "q"),))
        )
        await repo.append_llm_call(run_id, _call())

        hidden = await repo.list_llm_calls(run_id)
        shown = await repo.list_llm_calls(run_id, include_payloads=True)

        assert [call.payload for call in hidden] == [None, None]
        assert shown[0].payload is not None
        assert shown[1].payload is None

    _with_repository(exercise)


def test_list_tool_calls_in_order() -> None:
    async def exercise(
        _pool: asyncpg.Pool, repo: RunRepository, created: list[str]
    ) -> None:
        run_id = await _new_run(repo, created)
        later = ToolCallRecord(
            ordinal=2,
            tool_name="search_evidence",
            arguments={"limit": 3},
            status="succeeded",
            result_summary={"count": 2},
            duration_ms=4.5,
        )
        earlier = ToolCallRecord(
            ordinal=1,
            tool_name="search_papers",
            arguments={"query_id": "zq7731"},
            status="rejected",
            result_summary={"reason": "budget"},
            duration_ms=2.0,
            error_category="budget",
        )
        await repo.append_tool_call(run_id, later)
        await repo.append_tool_call(run_id, earlier)

        assert await repo.list_tool_calls(run_id) == (earlier, later)

    _with_repository(exercise)


def test_llm_calls_cascade_with_run() -> None:
    async def exercise(
        pool: asyncpg.Pool, repo: RunRepository, created: list[str]
    ) -> None:
        run_id = await _new_run(repo, created)
        await repo.append_llm_call(
            run_id, _call(), LLMCallPayload(messages=(ChatMessage("user", "q"),))
        )

        async with pool.acquire() as connection:
            await connection.execute("DELETE FROM research_runs WHERE id = $1", run_id)
            calls = await connection.fetchval(
                "SELECT count(*) FROM llm_calls WHERE run_id = $1", run_id
            )
            payloads = await connection.fetchval(
                "SELECT count(*) FROM llm_call_payloads WHERE run_id = $1", run_id
            )
        assert (calls, payloads) == (0, 0)

    _with_repository(exercise)


def test_append_for_unknown_run_raises() -> None:
    async def exercise(
        _pool: asyncpg.Pool, repo: RunRepository, _created: list[str]
    ) -> None:
        with pytest.raises(RunNotFound):
            await repo.append_llm_call(uuid4(), _call())

    _with_repository(exercise)


_DRAFTS = (
    DraftClaimOutcome(
        ordinal=1,
        handle="E1",
        quote="a quote ✓",
        text="a claim",
        verdict=ClaimVerdict.NOT_SHOWN,
        chunk_id="chunk-x",
        paper_id="W1",
    ),
    DraftClaimOutcome(
        ordinal=2,
        handle="E7",
        quote="other",
        text="other claim",
        verdict=ClaimVerdict.FAILED_CHECKS,
        failed_checks=("quote_found", "numbers_from_quote"),
    ),
)
_SUMMARY = SynthesisSummary(
    model_declared_insufficient=False,
    relevant_handles=("E1",),
    packed_handles=("E1", "E7"),
    omitted_handles=("E9",),
    drafted=2,
)


async def _completed_run(  # type: ignore[no-untyped-def]
    pool: asyncpg.Pool, repo: RunRepository, created: list[str]
):
    run_id = await _new_run(repo, created)
    async with pool.acquire() as connection:
        await connection.execute(
            "UPDATE research_runs SET status = 'running', started_at = now() "
            "WHERE id = $1",
            run_id,
        )
    await repo.complete_run(
        run_id,
        answer="No supported claims.",
        outcome=AnswerOutcome.INSUFFICIENT_EVIDENCE,
        claims=(),
        usage=RunUsage(),
        drafts=_DRAFTS,
        synthesis=_SUMMARY,
    )
    return run_id


def test_complete_run_persists_drafts_and_synthesis() -> None:
    async def exercise(
        pool: asyncpg.Pool, repo: RunRepository, created: list[str]
    ) -> None:
        run_id = await _completed_run(pool, repo, created)

        assert await repo.list_draft_claims(run_id) == _DRAFTS
        assert await repo.get_synthesis_summary(run_id) == _SUMMARY

    _with_repository(exercise)


def test_drafts_cascade_with_run() -> None:
    async def exercise(
        pool: asyncpg.Pool, repo: RunRepository, created: list[str]
    ) -> None:
        run_id = await _completed_run(pool, repo, created)

        async with pool.acquire() as connection:
            await connection.execute("DELETE FROM research_runs WHERE id = $1", run_id)
            remaining = await connection.fetchval(
                "SELECT count(*) FROM draft_claims WHERE run_id = $1", run_id
            )
        assert remaining == 0

    _with_repository(exercise)
