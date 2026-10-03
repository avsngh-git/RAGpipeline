"""Single-worker execution queue for persisted research runs."""

from __future__ import annotations

import asyncio
import logging
from uuid import UUID

from research_platform.runs.contracts import RunStatus
from research_platform.runs.runner import ResearchRunner
from research_platform.runs.store import RunStore

logger = logging.getLogger(__name__)
_RECOVERY_LIMIT = 1000


class ResearchQueueFull(RuntimeError):
    """Raised when the in-memory queue has reached its submission limit."""


class RunExecutor:
    """Serialize run execution and restore interrupted runs at startup."""

    def __init__(
        self, runner: ResearchRunner, store: RunStore, *, max_queue: int = 100
    ) -> None:
        if (
            isinstance(max_queue, bool)
            or not isinstance(max_queue, int)
            or max_queue < 1
        ):
            raise ValueError("max_queue must be a positive integer")
        self._runner = runner
        self._store = store
        self._max_queue = max_queue
        self._queue: asyncio.Queue[UUID] = asyncio.Queue()
        self._worker: asyncio.Task[None] | None = None
        self._started = False
        self._start_lock = asyncio.Lock()

    @property
    def pending(self) -> int:
        """Return the number of run IDs waiting for the worker."""
        return self._queue.qsize()

    async def start(self) -> None:
        """Restore running runs before queued runs, then start one worker."""
        async with self._start_lock:
            if self._started:
                raise RuntimeError("run executor has already been started")

            recovered: list[UUID] = []
            for status in (RunStatus.RUNNING, RunStatus.QUEUED):
                runs = await self._store.list_runs([status], limit=_RECOVERY_LIMIT)
                if len(runs) >= _RECOVERY_LIMIT:
                    raise RuntimeError(
                        f"research run recovery reached the {_RECOVERY_LIMIT}-run limit"
                    )
                ordered = sorted(
                    runs,
                    key=lambda run: (run.created_at, str(run.run_id)),
                )
                recovered.extend(run.run_id for run in ordered)

            for run_id in recovered:
                self._queue.put_nowait(run_id)
            self._started = True
            self._worker = asyncio.create_task(self._work(), name="research-run-worker")

    async def submit(self, run_id: UUID) -> None:
        """Queue a newly persisted run subject to the admission limit."""
        if self.pending >= self._max_queue:
            raise ResearchQueueFull("research run queue is full")
        self._queue.put_nowait(run_id)

    async def stop(self) -> None:
        """Cancel and await the worker, leaving an active run resumable."""
        worker = self._worker
        if worker is None:
            return
        worker.cancel()
        try:
            await worker
        except asyncio.CancelledError:
            pass
        finally:
            self._worker = None

    async def _work(self) -> None:
        while True:
            run_id = await self._queue.get()
            try:
                await self._runner.run(run_id)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                logger.error(
                    "research_worker_error",
                    extra={"run_id": str(run_id), "error_type": type(error).__name__},
                )
            finally:
                self._queue.task_done()
