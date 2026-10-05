"""Run the separate online-ingestion worker process."""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import socket
from collections.abc import Mapping
from contextlib import suppress
from typing import Protocol

import asyncpg  # type: ignore[import-untyped]

from research_platform.config import Settings
from research_platform.worker.queue import (
    IngestionQueue,
    IngestionRequest,
    IngestionTerminalStatus,
)

logger = logging.getLogger(__name__)
_DEFAULT_LEASE_SECONDS = 300.0


class IngestionHandler(Protocol):
    """One implementation of the ingestion request execution contract."""

    async def handle(
        self, request: IngestionRequest
    ) -> tuple[IngestionTerminalStatus, Mapping[str, object]]: ...


class _NoopHandler:
    async def handle(
        self, request: IngestionRequest
    ) -> tuple[IngestionTerminalStatus, Mapping[str, object]]:
        del request
        return "failed", {"reason": "handler_not_configured"}


async def run_worker(
    queue: IngestionQueue,
    handler: IngestionHandler,
    *,
    worker_id: str,
    poll_seconds: float = 5.0,
    stop: asyncio.Event,
) -> None:
    """Claim, heartbeat and complete requests until the stop event is set."""
    if not worker_id.strip():
        raise ValueError("worker_id must be non-empty")
    if poll_seconds <= 0:
        raise ValueError("poll_seconds must be positive")

    while not stop.is_set():
        request = await queue.claim_next(
            worker_id, lease_seconds=_DEFAULT_LEASE_SECONDS
        )
        if request is None:
            try:
                await asyncio.wait_for(stop.wait(), timeout=poll_seconds)
            except TimeoutError:
                continue
            return
        await _process_request(queue, handler, request, worker_id)


async def _process_request(
    queue: IngestionQueue,
    handler: IngestionHandler,
    request: IngestionRequest,
    worker_id: str,
) -> None:
    lease_lost = asyncio.Event()
    interval = _DEFAULT_LEASE_SECONDS / 3

    async def maintain_lease() -> None:
        while True:
            await asyncio.sleep(interval)
            if not await queue.heartbeat(
                request.id,
                worker_id,
                lease_seconds=_DEFAULT_LEASE_SECONDS,
            ):
                lease_lost.set()
                return

    heartbeat_task = asyncio.create_task(maintain_lease())
    handler_task = asyncio.create_task(handler.handle(request))
    try:
        done, _pending = await asyncio.wait(
            {handler_task, heartbeat_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        if heartbeat_task in done:
            error = heartbeat_task.exception()
            if error is not None:
                logger.warning(
                    "ingestion request heartbeat failed",
                    extra={
                        "request_id": str(request.id),
                        "error_type": type(error).__name__,
                    },
                )
            elif lease_lost.is_set():
                logger.warning(
                    "ingestion request lease was lost",
                    extra={"request_id": str(request.id)},
                )
            handler_task.cancel()
            with suppress(asyncio.CancelledError):
                await handler_task
            return

        try:
            status, result = handler_task.result()
            if status not in ("succeeded", "partially_succeeded", "failed"):
                raise ValueError("handler returned an invalid terminal status")
        except Exception as error:
            status = "failed"
            result = {"error_type": type(error).__name__}
        await queue.complete(request.id, worker_id, status=status, result=result)
    finally:
        heartbeat_task.cancel()
        if not handler_task.done():
            handler_task.cancel()
        with suppress(asyncio.CancelledError):
            await heartbeat_task
        with suppress(asyncio.CancelledError, Exception):
            await handler_task


def _make_handler(name: str) -> IngestionHandler:
    if name == "noop":
        return _NoopHandler()
    raise ValueError(f"unsupported ingestion handler: {name}")


async def _run_main() -> None:
    settings = Settings()
    worker_id = os.environ.get(
        "RESEARCH_PLATFORM_WORKER_ID", f"{socket.gethostname()}:{os.getpid()}"
    )
    poll_seconds = float(os.environ.get("RESEARCH_PLATFORM_WORKER_POLL_SECONDS", "5"))
    handler_name = os.environ.get("RESEARCH_PLATFORM_INGESTION_HANDLER", "noop")
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signal_number in (signal.SIGINT, signal.SIGTERM):
        with suppress(NotImplementedError, RuntimeError):
            loop.add_signal_handler(signal_number, stop.set)

    pool = await asyncpg.create_pool(settings.database_url, min_size=1, max_size=4)
    try:
        await run_worker(
            IngestionQueue(pool),
            _make_handler(handler_name),
            worker_id=worker_id,
            poll_seconds=poll_seconds,
            stop=stop,
        )
    finally:
        await pool.close()


def main() -> None:
    """Start the worker and stop cleanly on SIGINT or SIGTERM."""
    logging.basicConfig(level=logging.INFO)
    asyncio.run(_run_main())


if __name__ == "__main__":
    main()
