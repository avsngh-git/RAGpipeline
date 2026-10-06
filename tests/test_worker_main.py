"""Focused behaviour tests for the ingestion worker loop."""

import asyncio
from uuid import uuid4

from research_platform.worker.main import _make_handler, run_worker
from research_platform.worker.queue import IngestionRequest


def _request() -> IngestionRequest:
    return IngestionRequest(
        id=uuid4(),
        collection_id=uuid4(),
        run_id=None,
        requested_by="terminal",
        paper_ids=("W123",),
        status="claimed",
        attempts=1,
        result={},
    )


class _Queue:
    def __init__(self, stop: asyncio.Event) -> None:
        self.stop = stop
        self.request = _request()
        self.completed: tuple[str, dict[str, object]] | None = None

    async def claim_next(
        self, worker_id: str, *, lease_seconds: float = 300
    ) -> IngestionRequest | None:
        del worker_id, lease_seconds
        request, self.request = self.request, None  # type: ignore[assignment]
        return request

    async def heartbeat(
        self, request_id: object, worker_id: str, *, lease_seconds: float = 300
    ) -> bool:
        del request_id, worker_id, lease_seconds
        return True

    async def complete(
        self,
        request_id: object,
        worker_id: str,
        *,
        status: str,
        result: dict[str, object],
    ) -> None:
        del request_id, worker_id
        self.completed = (status, result)
        self.stop.set()


class _SuccessfulHandler:
    async def handle(self, request: IngestionRequest) -> tuple[str, dict[str, object]]:
        return "succeeded", {"papers": len(request.paper_ids)}


class _BrokenHandler:
    async def handle(self, request: IngestionRequest) -> tuple[str, dict[str, object]]:
        del request
        raise LookupError("private handler details")


def test_worker_completes_handler_result() -> None:
    async def exercise() -> None:
        stop = asyncio.Event()
        queue = _Queue(stop)
        await run_worker(queue, _SuccessfulHandler(), worker_id="worker-1", stop=stop)  # type: ignore[arg-type]
        assert queue.completed == ("succeeded", {"papers": 1})

    asyncio.run(exercise())


def test_handler_exception_marks_failed() -> None:
    async def exercise() -> None:
        stop = asyncio.Event()
        queue = _Queue(stop)
        await run_worker(queue, _BrokenHandler(), worker_id="worker-1", stop=stop)  # type: ignore[arg-type]
        assert queue.completed == ("failed", {"error_type": "LookupError"})

    asyncio.run(exercise())


def test_worker_stops_on_event() -> None:
    async def exercise() -> None:
        stop = asyncio.Event()
        queue = _Queue(stop)
        queue.request = None  # type: ignore[assignment]
        asyncio.get_running_loop().call_later(0.01, stop.set)
        await run_worker(
            queue,
            _SuccessfulHandler(),
            worker_id="worker-1",
            poll_seconds=0.1,
            stop=stop,
        )  # type: ignore[arg-type]
        assert queue.completed is None

    asyncio.run(exercise())


def test_noop_handler_reports_not_configured() -> None:
    async def exercise() -> None:
        status, result = await _make_handler("noop").handle(_request())
        assert status == "failed"
        assert result == {"reason": "handler_not_configured"}

    asyncio.run(exercise())
