"""Offline coverage for serialized and resumable run execution."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from research_platform.runs.contracts import ResearchMode, ResearchRequest, RunStatus
from research_platform.runs.executor import ResearchQueueFull, RunExecutor
from research_platform.runs.memory import InMemoryRunStore


class RecordingRunner:
    def __init__(self, *, blocked_run: UUID | None = None) -> None:
        self.calls: list[UUID] = []
        self.active = 0
        self.maximum_active = 0
        self.blocked_run = blocked_run
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.finished = asyncio.Event()
        self.fail_runs: set[UUID] = set()
        self.expected_calls = 0

    async def run(self, run_id: UUID) -> RunStatus:
        self.calls.append(run_id)
        self.active += 1
        self.maximum_active = max(self.maximum_active, self.active)
        self.entered.set()
        try:
            if run_id == self.blocked_run:
                await self.release.wait()
            if run_id in self.fail_runs:
                raise RuntimeError("synthetic worker exception")
            return RunStatus.COMPLETED
        finally:
            self.active -= 1
            if len(self.calls) == self.expected_calls:
                self.finished.set()


def _request() -> ResearchRequest:
    return ResearchRequest(
        question="A synthetic research question", mode=ResearchMode.QUICK
    )


async def _stored_run(
    store: InMemoryRunStore,
    *,
    status: RunStatus = RunStatus.QUEUED,
    created_at: datetime,
) -> UUID:
    run_id = await store.create_run(_request())
    run = await store.get_run(run_id)
    store._runs[run_id] = replace(run, status=status, created_at=created_at)
    return run_id


def test_start_requeues_running_then_queued_in_created_order() -> None:
    async def exercise() -> None:
        store = InMemoryRunStore()
        base = datetime(2026, 1, 1, tzinfo=UTC)
        queued_new = await _stored_run(store, created_at=base + timedelta(seconds=4))
        running_new = await _stored_run(
            store,
            status=RunStatus.RUNNING,
            created_at=base + timedelta(seconds=2),
        )
        queued_old = await _stored_run(store, created_at=base + timedelta(seconds=3))
        running_old = await _stored_run(
            store, status=RunStatus.RUNNING, created_at=base + timedelta(seconds=1)
        )
        expected = (running_old, running_new, queued_old, queued_new)
        runner = RecordingRunner()
        runner.expected_calls = len(expected)
        executor = RunExecutor(runner, store)

        await executor.start()
        await asyncio.wait_for(runner.finished.wait(), timeout=1)
        await executor.stop()

        assert runner.calls == list(expected)
        assert runner.maximum_active == 1

    asyncio.run(exercise())


def test_start_restores_backlog_larger_than_submission_capacity() -> None:
    async def exercise() -> None:
        store = InMemoryRunStore()
        base = datetime(2026, 1, 1, tzinfo=UTC)
        queued_new = await _stored_run(store, created_at=base + timedelta(seconds=3))
        running = await _stored_run(store, status=RunStatus.RUNNING, created_at=base)
        queued_old = await _stored_run(store, created_at=base + timedelta(seconds=2))
        runner = RecordingRunner(blocked_run=running)
        runner.expected_calls = 3
        executor = RunExecutor(runner, store, max_queue=2)

        await asyncio.wait_for(executor.start(), timeout=1)
        await asyncio.wait_for(runner.entered.wait(), timeout=1)

        assert runner.calls == [running]
        assert executor.pending == 2
        with pytest.raises(ResearchQueueFull):
            await executor.submit(uuid4())

        runner.release.set()
        await asyncio.wait_for(runner.finished.wait(), timeout=1)
        await executor.stop()

        assert runner.calls == [running, queued_old, queued_new]

    asyncio.run(exercise())


def test_runs_execute_one_at_a_time_in_submit_order() -> None:
    async def exercise() -> None:
        runner = RecordingRunner(blocked_run=UUID(int=1))
        runner.expected_calls = 3
        executor = RunExecutor(runner, InMemoryRunStore())
        run_ids = [UUID(int=value) for value in (1, 2, 3)]

        await executor.start()
        for run_id in run_ids:
            await executor.submit(run_id)
        await asyncio.wait_for(runner.entered.wait(), timeout=1)
        await asyncio.sleep(0)

        assert runner.calls == [run_ids[0]]
        assert executor.pending == 2

        runner.release.set()
        await asyncio.wait_for(runner.finished.wait(), timeout=1)
        await executor.stop()

        assert runner.calls == run_ids
        assert runner.maximum_active == 1

    asyncio.run(exercise())


def test_worker_survives_runner_exception(caplog: pytest.LogCaptureFixture) -> None:
    async def exercise() -> None:
        runner = RecordingRunner()
        runner.expected_calls = 2
        failed_run, next_run = UUID(int=4), UUID(int=5)
        runner.fail_runs.add(failed_run)
        executor = RunExecutor(runner, InMemoryRunStore())
        await executor.start()
        await executor.submit(failed_run)
        await executor.submit(next_run)
        await asyncio.wait_for(runner.finished.wait(), timeout=1)
        await executor.stop()

        assert runner.calls == [failed_run, next_run]

    asyncio.run(exercise())
    records = [
        record
        for record in caplog.records
        if record.getMessage() == "research_worker_error"
    ]
    assert len(records) == 1
    assert records[0].run_id == str(UUID(int=4))
    assert records[0].error_type == "RuntimeError"
    assert "synthetic worker exception" not in caplog.text


def test_queue_full_raises() -> None:
    async def exercise() -> None:
        runner = RecordingRunner(blocked_run=UUID(int=6))
        runner.expected_calls = 2
        executor = RunExecutor(runner, InMemoryRunStore(), max_queue=1)
        await executor.start()
        await executor.submit(UUID(int=6))
        await asyncio.wait_for(runner.entered.wait(), timeout=1)
        await executor.submit(UUID(int=7))

        with pytest.raises(ResearchQueueFull):
            await executor.submit(UUID(int=8))

        runner.release.set()
        await asyncio.wait_for(runner.finished.wait(), timeout=1)
        await executor.stop()

    asyncio.run(exercise())


def test_stop_cancels_worker_and_leaves_run_running() -> None:
    async def exercise() -> None:
        store = InMemoryRunStore()
        run_id = await _stored_run(
            store, status=RunStatus.RUNNING, created_at=datetime.now(UTC)
        )
        runner = RecordingRunner(blocked_run=run_id)
        runner.expected_calls = 2
        executor = RunExecutor(runner, store)

        await executor.start()
        await asyncio.wait_for(runner.entered.wait(), timeout=1)
        await executor.stop()

        assert runner.calls == [run_id]
        assert (await store.get_run(run_id)).status is RunStatus.RUNNING

    asyncio.run(exercise())


def test_start_twice_raises() -> None:
    async def exercise() -> None:
        executor = RunExecutor(RecordingRunner(), InMemoryRunStore())
        await executor.start()
        with pytest.raises(RuntimeError, match="already been started"):
            await executor.start()
        await executor.stop()

    asyncio.run(exercise())


def test_start_fails_explicitly_when_recovery_query_is_saturated() -> None:
    class SaturatedStore:
        async def list_runs(self, statuses, *, limit: int = 100):
            assert statuses == [RunStatus.RUNNING]
            assert limit == 1000
            now = datetime.now(UTC)
            return tuple(
                SimpleNamespace(run_id=UUID(int=value + 1), created_at=now)
                for value in range(limit)
            )

    async def exercise() -> None:
        executor = RunExecutor(RecordingRunner(), SaturatedStore())  # type: ignore[arg-type]

        with pytest.raises(RuntimeError, match="recovery reached the 1000-run limit"):
            await executor.start()

        assert executor.pending == 0
        assert executor._worker is None

    asyncio.run(exercise())


def test_waiting_runs_are_recovered_before_queued() -> None:
    async def exercise() -> None:
        store = InMemoryRunStore()
        base = datetime(2026, 1, 1, tzinfo=UTC)
        queued = await _stored_run(store, created_at=base)
        waiting = await _stored_run(
            store,
            status=RunStatus.WAITING_FOR_INGESTION,
            created_at=base + timedelta(seconds=1),
        )
        running = await _stored_run(
            store, status=RunStatus.RUNNING, created_at=base + timedelta(seconds=2)
        )
        runner = RecordingRunner()
        runner.expected_calls = 3
        executor = RunExecutor(runner, store)

        await executor.start()
        await asyncio.wait_for(runner.finished.wait(), timeout=1)
        await executor.stop()

        assert runner.calls == [running, waiting, queued]

    asyncio.run(exercise())
