"""Run executor cancellation and shutdown coverage."""

from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

from research_platform.runs.contracts import ResearchMode, ResearchRequest, RunStatus
from research_platform.runs.executor import RunExecutor
from research_platform.runs.memory import InMemoryRunStore


class BlockingRunner:
    def __init__(self) -> None:
        self.started: dict[UUID, asyncio.Event] = {}
        self.release: dict[UUID, asyncio.Event] = {}
        self.cancelled: list[UUID] = []
        self.finished: list[UUID] = []

    def prepare(self, run_id: UUID) -> None:
        self.started[run_id] = asyncio.Event()
        self.release[run_id] = asyncio.Event()

    async def run(self, run_id: UUID) -> None:
        self.started[run_id].set()
        try:
            await self.release[run_id].wait()
        except asyncio.CancelledError:
            self.cancelled.append(run_id)
            raise
        self.finished.append(run_id)


async def _wait(event: asyncio.Event) -> None:
    async with asyncio.timeout(2):
        await event.wait()


def test_cancel_running_run_stops_it_and_worker_continues() -> None:
    async def exercise() -> tuple[list[UUID], list[UUID], UUID, UUID]:
        runner = BlockingRunner()
        first, second = uuid4(), uuid4()
        runner.prepare(first)
        runner.prepare(second)
        executor = RunExecutor(runner, InMemoryRunStore())  # type: ignore[arg-type]
        await executor.start()
        await executor.submit(first)
        await executor.submit(second)
        await _wait(runner.started[first])
        await executor.cancel(first)
        await _wait(runner.started[second])
        await executor.stop()
        return runner.cancelled, runner.finished, first, second

    cancelled, finished, first, second = asyncio.run(exercise())
    assert cancelled == [first, second]
    assert len(finished) == 0


def test_cancel_queued_run_is_skipped() -> None:
    async def exercise() -> tuple[list[UUID], list[UUID]]:
        runner = BlockingRunner()
        first, second = uuid4(), uuid4()
        runner.prepare(first)
        runner.prepare(second)
        executor = RunExecutor(runner, InMemoryRunStore())  # type: ignore[arg-type]
        await executor.start()
        await executor.submit(first)
        await executor.submit(second)
        await _wait(runner.started[first])
        await executor.cancel(second)
        runner.release[first].set()
        async with asyncio.timeout(2):
            await executor._queue.join()
        await executor.stop()
        started = [run_id for run_id, event in runner.started.items() if event.is_set()]
        return started, runner.finished

    started, finished = asyncio.run(exercise())
    assert len(started) == 1
    assert len(finished) == 1


def test_stop_still_leaves_running_run_resumable() -> None:
    async def exercise() -> tuple[list[UUID], list[UUID], set[UUID], RunStatus]:
        runner = BlockingRunner()
        store = InMemoryRunStore()
        run_id = await store.create_run(
            ResearchRequest(
                question="Synthetic resumable question", mode=ResearchMode.QUICK
            )
        )
        runner.prepare(run_id)
        executor = RunExecutor(runner, store)  # type: ignore[arg-type]
        await executor.start()
        await executor.submit(run_id)
        await _wait(runner.started[run_id])
        await executor.stop()
        status = (await store.get_run(run_id)).status
        return runner.cancelled, runner.finished, executor._cancelled, status

    cancelled, finished, skipped, status = asyncio.run(exercise())
    assert len(cancelled) == 1
    assert finished == []
    assert skipped == set()
    assert status is RunStatus.QUEUED
