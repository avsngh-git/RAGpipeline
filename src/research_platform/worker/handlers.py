"""Online ingestion handler: ingest papers, then append the next generation (P35-25)."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Protocol, cast
from uuid import UUID

import asyncpg  # type: ignore[import-untyped]
import httpx

from research_platform.ingestion.generation_append import AppendReport
from research_platform.ingestion.online_ingestion import PaperIngestOutcome
from research_platform.worker.gpu import gpu_lock
from research_platform.worker.queue import IngestionRequest, IngestionTerminalStatus

_LOG = logging.getLogger(__name__)


class PaperIngester(Protocol):
    async def ingest_paper(
        self, paper_id: str, *, run_id: UUID | None
    ) -> PaperIngestOutcome: ...


class Appender(Protocol):
    async def append(
        self,
        collection_id: UUID,
        outcomes: Sequence[PaperIngestOutcome],
        *,
        request_id: UUID,
    ) -> AppendReport: ...


IngesterFactory = Callable[[Mapping[str, object]], PaperIngester]
AppenderFactory = Callable[[], AbstractAsyncContextManager[Appender]]
LockFactory = Callable[[asyncpg.Pool], AbstractAsyncContextManager[None]]


def handler_status(
    requested: int, outcomes: Sequence[PaperIngestOutcome]
) -> IngestionTerminalStatus:
    """``succeeded`` when every paper is in the corpus, ``failed`` when none is."""
    available = sum(outcome.status == "ingested" for outcome in outcomes)
    if available == 0:
        return "failed"
    return "succeeded" if available == requested else "partially_succeeded"


class OnlineIngestionHandler:
    """Implements the worker ``IngestionHandler`` for online ingestion requests."""

    def __init__(
        self,
        *,
        pool: asyncpg.Pool,
        chunking_for: Callable[[UUID], Awaitable[Mapping[str, object]]],
        ingester: IngesterFactory,
        appender: AppenderFactory,
        release_gpu: Callable[[], Awaitable[None]] | None = None,
        lock: LockFactory = gpu_lock,
    ) -> None:
        self._pool = pool
        self._chunking_for = chunking_for
        self._ingester = ingester
        self._appender = appender
        self._release_gpu = release_gpu
        self._lock = lock

    async def handle(
        self, request: IngestionRequest
    ) -> tuple[IngestionTerminalStatus, Mapping[str, object]]:
        chunking = await self._chunking_for(request.collection_id)
        async with self._lock(self._pool):
            if self._release_gpu is not None:
                await self._release_gpu()
            ingester = self._ingester(chunking)
            outcomes = [
                await ingester.ingest_paper(paper_id, run_id=request.run_id)
                for paper_id in request.paper_ids
            ]
            try:
                async with self._appender() as appender:
                    report = await appender.append(
                        request.collection_id, outcomes, request_id=request.id
                    )
            except Exception as error:
                _LOG.warning(
                    "online generation append failed",
                    extra={
                        "request_id": str(request.id),
                        "error_type": type(error).__name__,
                    },
                )
                return "failed", {
                    "outcomes": [_outcome_json(outcome) for outcome in outcomes],
                    "generation": None,
                    "append_error": type(error).__name__,
                }
        return handler_status(len(request.paper_ids), report.outcomes), {
            "outcomes": [_outcome_json(outcome) for outcome in report.outcomes],
            "generation": report.generation,
            "parent_generation": report.parent_generation,
            "snapshot_id": None
            if report.snapshot_id is None
            else str(report.snapshot_id),
            "added_papers": list(report.added_papers),
            "average_length_drift": report.average_length_drift,
        }


def _outcome_json(outcome: PaperIngestOutcome) -> dict[str, object]:
    return {
        "paper_id": outcome.paper_id,
        "status": outcome.status,
        "reason": outcome.reason,
        "document_id": None
        if outcome.document_id is None
        else str(outcome.document_id),
        "extraction_id": (
            None if outcome.extraction_id is None else str(outcome.extraction_id)
        ),
        "chunking_configuration_id": outcome.chunking_configuration_id,
    }


async def published_chunking_configuration(
    pool: asyncpg.Pool, collection_id: UUID, configuration_id: str
) -> Mapping[str, object]:
    """The chunking configuration of the published generation's original snapshot.

    Child snapshots inherit their parent's chunks, so the configuration comes from
    the ingestion jobs of the first snapshot in the published snapshot's lineage.
    """
    async with pool.acquire() as connection:
        snapshot_id = await connection.fetchval(
            """
            SELECT generation.snapshot_id
            FROM index_generation_pointers pointer
            JOIN index_generations generation
              ON generation.collection_id = pointer.collection_id
             AND generation.configuration_id = pointer.configuration_id
             AND generation.generation = pointer.published_generation
            WHERE pointer.collection_id = $1 AND pointer.configuration_id = $2
            """,
            collection_id,
            configuration_id,
        )
        if not isinstance(snapshot_id, UUID):
            raise ValueError("the collection has no published generation")
        lineage = await connection.fetch(
            """
            WITH RECURSIVE chain(snapshot_id) AS (
                SELECT $1::uuid
                UNION
                SELECT lineage.parent_snapshot_id
                FROM snapshot_variant_lineage lineage
                JOIN chain ON lineage.snapshot_id = chain.snapshot_id
            )
            SELECT DISTINCT job.configuration -> 'chunking_configuration' AS chunking
            FROM chain
            JOIN ingestion_jobs job
              ON job.configuration ->> 'snapshot_id' = chain.snapshot_id::text
            WHERE job.configuration ? 'chunking_configuration'
            """,
            snapshot_id,
        )
    configurations = []
    for row in lineage:
        value = row["chunking"]
        if isinstance(value, str):
            value = json.loads(value)
        configurations.append(value)
    if len(configurations) != 1 or not isinstance(configurations[0], dict):
        raise ValueError(
            "the published snapshot lineage does not record exactly one chunking "
            "configuration"
        )
    return cast(Mapping[str, object], configurations[0])


async def unload_ollama_model(base_url: str, model: str) -> None:
    """Ask Ollama to unload the generator before extraction uses the GPU."""
    try:
        async with httpx.AsyncClient(base_url=base_url, timeout=30) as http:
            response = await http.post(
                "/api/generate", json={"model": model, "keep_alive": 0}
            )
            response.raise_for_status()
    except httpx.HTTPError as error:
        _LOG.warning(
            "could not unload the Ollama model",
            extra={"error_type": type(error).__name__},
        )


@asynccontextmanager
async def closing_appender(
    build: Callable[[], Awaitable[tuple[Appender, Callable[[], None]]]],
) -> AsyncIterator[Appender]:
    """Build an appender with its embedder and close the embedder afterwards."""
    appender, close = await build()
    try:
        yield appender
    finally:
        close()
