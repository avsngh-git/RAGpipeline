"""HTTP routes for starting and reading collection ingestion (P35-28, spec 7.2)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal, Protocol
from uuid import UUID

import asyncpg  # type: ignore[import-untyped]
from fastapi import APIRouter, Request, status
from pydantic import BaseModel, ConfigDict, Field

from research_platform.config import DiscoverySettings
from research_platform.ingestion.generation_index import GenerationQdrantCollection
from research_platform.ingestion.generation_registry import GenerationRegistry
from research_platform.ingestion.membership_policy import (
    MembershipPolicy,
    PolicyResult,
)
from research_platform.worker.queue import IngestionQueue, IngestionRequest

from .errors import AppError

API_MAX_PAPERS = 20
CollectionState = Literal["missing", "unpublished", "ready"]


class IngestRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    paper_ids: tuple[str, ...] = Field(min_length=1, max_length=API_MAX_PAPERS)


class IngestDecisionView(BaseModel):
    paper_id: str
    decision: Literal["accepted", "refused"]
    reason: str


class IngestOutcomeView(BaseModel):
    paper_id: str
    status: str
    reason: str


class IngestResponse(BaseModel):
    collection_id: UUID
    request_id: UUID | None
    status: str | None
    decisions: tuple[IngestDecisionView, ...] = ()
    outcomes: tuple[IngestOutcomeView, ...] = ()
    generation: int | None = None


class IngestionAPIService(Protocol):
    """Collection state, membership decisions and request reads for the API."""

    async def collection_state(self, collection_id: UUID) -> CollectionState: ...

    async def submit(
        self, collection_id: UUID, paper_ids: Sequence[str]
    ) -> PolicyResult: ...

    async def get_request(self, request_id: UUID) -> IngestionRequest | None: ...


class CollectionIngestionService:
    """The membership policy and queue for collections of one configuration."""

    def __init__(self, pool: asyncpg.Pool, papers: GenerationQdrantCollection) -> None:
        self._pool = pool
        self._papers = papers
        self._registry = GenerationRegistry(pool)

    async def collection_state(self, collection_id: UUID) -> CollectionState:
        async with self._pool.acquire() as connection:
            exists = await connection.fetchval(
                "SELECT EXISTS (SELECT 1 FROM collections WHERE id = $1)",
                collection_id,
            )
        if not exists:
            return "missing"
        published = await self._registry.published(
            collection_id, self._papers.configuration.configuration_id
        )
        return "unpublished" if published is None else "ready"

    async def submit(
        self, collection_id: UUID, paper_ids: Sequence[str]
    ) -> PolicyResult:
        policy = MembershipPolicy(
            self._pool, self._papers, DiscoverySettings(), collection_id=collection_id
        )
        return await policy.submit(
            run_id=None,
            requested_by="api",
            paper_ids=paper_ids,
            max_papers=API_MAX_PAPERS,
        )

    async def get_request(self, request_id: UUID) -> IngestionRequest | None:
        try:
            return await IngestionQueue(self._pool).get(request_id)
        except KeyError:
            return None


def _active(
    request: Request, injected: IngestionAPIService | None
) -> IngestionAPIService:
    service = injected or getattr(request.app.state, "ingestion_service", None)
    if service is None:
        raise AppError(
            "service_unavailable",
            "The ingestion service is not configured.",
            status_code=503,
        )
    return service


def _outcomes(result: object) -> tuple[IngestOutcomeView, ...]:
    if not isinstance(result, dict):
        return ()
    rows = result.get("outcomes")
    if not isinstance(rows, list):
        return ()
    return tuple(
        IngestOutcomeView(
            paper_id=str(row.get("paper_id")),
            status=str(row.get("status")),
            reason=str(row.get("reason")),
        )
        for row in rows
        if isinstance(row, dict)
    )


def create_ingestion_router(service: IngestionAPIService | None) -> APIRouter:
    """Build the HTTP adapter for API-started ingestion."""
    router = APIRouter()

    @router.post(
        "/v1/collections/{collection_id}/ingest",
        response_model=IngestResponse,
        status_code=status.HTTP_202_ACCEPTED,
        summary="Start ingestion of papers into a collection",
    )
    async def start_ingestion(
        collection_id: UUID, body: IngestRequestBody, request: Request
    ) -> IngestResponse:
        active = _active(request, service)
        state = await active.collection_state(collection_id)
        if state == "missing":
            raise AppError(
                "collection_not_found", "The collection does not exist.", 404
            )
        if state == "unpublished":
            raise AppError(
                "collection_not_ready",
                "The collection has no published generation.",
                409,
            )
        result = await active.submit(collection_id, body.paper_ids)
        queued = (
            None
            if result.request_id is None
            else await active.get_request(result.request_id)
        )
        return IngestResponse(
            collection_id=collection_id,
            request_id=result.request_id,
            status=None if queued is None else queued.status,
            decisions=tuple(
                IngestDecisionView(
                    paper_id=decision.paper_id,
                    decision=decision.decision,
                    reason=decision.reason,
                )
                for decision in result.decisions
            ),
        )

    @router.get(
        "/v1/collections/{collection_id}/ingest/{request_id}",
        response_model=IngestResponse,
        summary="Get an ingestion request",
    )
    async def get_ingestion(
        collection_id: UUID, request_id: UUID, request: Request
    ) -> IngestResponse:
        active = _active(request, service)
        stored = await active.get_request(request_id)
        if stored is None or stored.collection_id != collection_id:
            raise AppError(
                "ingestion_request_not_found",
                "The ingestion request does not exist in this collection.",
                404,
            )
        generation = stored.result.get("generation")
        return IngestResponse(
            collection_id=collection_id,
            request_id=stored.id,
            status=stored.status,
            outcomes=_outcomes(dict(stored.result)),
            generation=generation if isinstance(generation, int) else None,
        )

    return router
