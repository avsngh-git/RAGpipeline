"""Run the separate online-ingestion worker process."""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import socket
from collections.abc import Callable, Mapping
from contextlib import AsyncExitStack, suppress
from pathlib import Path
from typing import Any, Protocol, cast
from uuid import UUID

import asyncpg  # type: ignore[import-untyped]
import httpx
import prometheus_client

from research_platform.config import Settings
from research_platform.observability.logging_config import configure_logging
from research_platform.observability.metrics import (
    INGESTION_BACKLOG,
    INGESTION_REQUESTS,
    REGISTRY,
)
from research_platform.observability.tracing import (
    ATTR_INGESTION_PAPER_COUNT,
    ATTR_INGESTION_REQUEST_ID,
    ATTR_INGESTION_STATUS,
    ATTR_RUN_ID,
    LF_LEVEL,
    SPAN_INGESTION_REQUEST,
    TracingSettings,
    configure_tracing,
    get_tracer,
    shutdown_tracing,
)
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
        INGESTION_BACKLOG.set(await queue.pending_count())
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
    with get_tracer().start_as_current_span(SPAN_INGESTION_REQUEST) as span:
        span.set_attribute(ATTR_INGESTION_REQUEST_ID, str(request.id))
        span.set_attribute(ATTR_INGESTION_PAPER_COUNT, len(request.paper_ids))
        if request.run_id is not None:
            span.set_attribute(ATTR_RUN_ID, str(request.run_id))
        await _process_request_traced(queue, handler, request, worker_id, span)


async def _process_request_traced(
    queue: IngestionQueue,
    handler: IngestionHandler,
    request: IngestionRequest,
    worker_id: str,
    span: Any,
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
                span.set_attribute(ATTR_INGESTION_STATUS, "failed")
                logger.warning(
                    "ingestion request heartbeat failed",
                    extra={
                        "request_id": str(request.id),
                        "error_type": type(error).__name__,
                    },
                )
            elif lease_lost.is_set():
                span.set_attribute(LF_LEVEL, "WARNING")
                span.set_attribute(ATTR_INGESTION_STATUS, "lease_lost")
                logger.warning(
                    "ingestion request lease was lost",
                    extra={"request_id": str(request.id)},
                )
            else:
                span.set_attribute(ATTR_INGESTION_STATUS, "failed")
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
        span.set_attribute(ATTR_INGESTION_STATUS, status)
        await queue.complete(request.id, worker_id, status=status, result=result)
        INGESTION_REQUESTS.labels(status).inc()
    finally:
        heartbeat_task.cancel()
        if not handler_task.done():
            handler_task.cancel()
        with suppress(asyncio.CancelledError):
            await heartbeat_task
        with suppress(asyncio.CancelledError, Exception):
            await handler_task


def _make_handler(
    name: str,
    *,
    pool: asyncpg.Pool | None = None,
    settings: Settings | None = None,
    stack: AsyncExitStack | None = None,
) -> IngestionHandler:
    if name == "noop":
        return _NoopHandler()
    if name == "online":
        if pool is None or settings is None or stack is None:
            raise ValueError("the online handler needs a pool, settings and a stack")
        return _online_handler(pool, settings, stack)
    raise ValueError(f"unsupported ingestion handler: {name}")


def _online_handler(
    pool: asyncpg.Pool, settings: Settings, stack: AsyncExitStack
) -> IngestionHandler:
    from research_platform.config import DiscoverySettings
    from research_platform.discovery.online import SpendLedger
    from research_platform.ingestion.embeddings import (
        create_embedder_for_configuration,
    )
    from research_platform.ingestion.generation_append import GenerationAppender
    from research_platform.ingestion.generation_cli import (
        load_generation_configuration,
    )
    from research_platform.ingestion.generation_index import (
        GenerationQdrantCollection,
    )
    from research_platform.ingestion.generation_registry import GenerationRegistry
    from research_platform.ingestion.online_ingestion import OnlineIngestionService
    from research_platform.ingestion.snapshots import SnapshotRepository
    from research_platform.ingestion.sparse_build import SparseEncoder
    from research_platform.search.sparse_lexical import VocabularyRepository
    from research_platform.worker.handlers import (
        OnlineIngestionHandler,
        closing_appender,
        published_chunking_configuration,
        unload_ollama_model,
    )

    configuration = load_generation_configuration(settings.generation_configuration)
    artifact_root = Path(
        os.environ.get("RESEARCH_PLATFORM_ARTIFACT_ROOT", "data/artifacts")
    )
    device = cast(Any, settings.model_device)
    downloads = httpx.AsyncClient(timeout=120, follow_redirects=False)
    qdrant = httpx.AsyncClient(base_url=settings.qdrant_url.rstrip("/"), timeout=120)
    stack.push_async_callback(downloads.aclose)
    stack.push_async_callback(qdrant.aclose)

    async def chunking_for(collection_id: UUID) -> Mapping[str, object]:
        return await published_chunking_configuration(
            pool, collection_id, configuration.configuration_id
        )

    def ingester(chunking: Mapping[str, object]) -> OnlineIngestionService:
        return OnlineIngestionService(
            pool=pool,
            http=downloads,
            ledger=SpendLedger(pool),
            settings=DiscoverySettings(),
            artifact_root=artifact_root,
            chunking_configuration=chunking,
            device=settings.model_device,
        )

    async def build() -> tuple[GenerationAppender, Callable[[], None]]:
        sparse = None
        if configuration.lexical is not None:
            sparse = SparseEncoder(VocabularyRepository(pool), configuration.lexical)
            await sparse.prepare()
        embedder = create_embedder_for_configuration(
            configuration.dense_configuration(), device=device
        )
        appender = GenerationAppender(
            pool=pool,
            registry=GenerationRegistry(pool),
            snapshots=SnapshotRepository(pool),
            configuration=configuration,
            passages=GenerationQdrantCollection(configuration, "passages", qdrant),
            papers=GenerationQdrantCollection(configuration, "papers", qdrant),
            embedder=embedder,
            sparse_encoder=sparse,
        )
        return appender, embedder.close

    async def release_gpu() -> None:
        await unload_ollama_model(settings.llm_base_url, settings.llm_model)

    return OnlineIngestionHandler(
        pool=pool,
        chunking_for=chunking_for,
        ingester=ingester,
        appender=lambda: closing_appender(build),
        release_gpu=release_gpu,
    )


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

    port = int(os.environ.get("RESEARCH_PLATFORM_WORKER_METRICS_PORT", "9101"))
    if port > 0:
        prometheus_client.start_http_server(port, addr="127.0.0.1", registry=REGISTRY)

    # The GPU lock, the append lock and the build lock each hold a session.
    pool = await asyncpg.create_pool(settings.database_url, min_size=1, max_size=8)
    try:
        async with AsyncExitStack() as stack:
            await run_worker(
                IngestionQueue(pool),
                _make_handler(handler_name, pool=pool, settings=settings, stack=stack),
                worker_id=worker_id,
                poll_seconds=poll_seconds,
                stop=stop,
            )
    finally:
        await pool.close()


def main() -> None:
    """Start the worker and stop cleanly on SIGINT or SIGTERM."""
    configure_logging(Settings().log_level)
    settings = Settings()
    configure_tracing(
        TracingSettings.from_env(settings.environment), service_name="research-worker"
    )
    try:
        asyncio.run(_run_main())
    finally:
        shutdown_tracing()


if __name__ == "__main__":
    main()
