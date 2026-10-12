"""HTTP adapters for Phase 2 search, paper metadata and citation reads."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query, Request
from pydantic import ValidationError

from research_platform.auth.keys import Principal, Scope
from research_platform.config import Settings
from research_platform.search.paper_graph import CitationDirection
from research_platform.services.capabilities import (
    CitationReader,
    PaperReader,
    Phase2APIServices,
    ResearchCapabilities,
    SearchExecutor,
)
from research_platform.services.citation_cursor import MAX_CURSOR_CHARS

from .errors import AppError
from .rate_limits import RouteClass, rate_limited
from .schemas.papers import CitationGraphResponse, PaperReadResponse
from .schemas.search import (
    EvidenceSearchRequest,
    EvidenceSearchResponse,
    PaperSearchRequest,
    PaperSearchResponse,
)

__all__ = [
    "CitationReader",
    "PaperReader",
    "Phase2APIServices",
    "SearchExecutor",
    "create_phase2_router",
]


def _services_for_request(
    request: Request, injected: Phase2APIServices | None
) -> Phase2APIServices | None:
    if injected is not None:
        return injected
    value = getattr(request.app.state, "phase2_services", None)
    return value if isinstance(value, Phase2APIServices) else None


def create_phase2_router(
    settings: Settings, services: Phase2APIServices | None
) -> APIRouter:
    """Create the transport adapter for the approved Phase 2 service contracts."""
    router = APIRouter()

    def capabilities(request: Request) -> ResearchCapabilities:
        return ResearchCapabilities(
            settings=settings, phase2=_services_for_request(request, services)
        )

    @router.post(
        "/v1/search",
        response_model=PaperSearchResponse,
        summary="Search for distinct papers",
        description="Returns ranked papers and bounded source-linked support. Scores are ranking signals, not probabilities.",
    )
    async def search_papers(
        body: PaperSearchRequest,
        request: Request,
        _principal: Annotated[
            Principal, Depends(rate_limited(Scope.READ, RouteClass.SEARCH))
        ],
    ) -> PaperSearchResponse:
        request_contract = body.to_contract()
        request_id = str(request.scope.get("state", {}).get("request_id", ""))
        result = await capabilities(request).search_papers(
            request_contract, request_id=request_id
        )
        try:
            return PaperSearchResponse.from_contract(result)
        except ValidationError:
            raise AppError(
                "invalid_service_response",
                "The search service returned an invalid response.",
                500,
            ) from None

    @router.post(
        "/v1/evidence/search",
        response_model=EvidenceSearchResponse,
        summary="Search source-linked evidence",
        description="Returns bounded prose or table evidence only when trusted private-local access is enabled.",
    )
    async def search_evidence(
        body: EvidenceSearchRequest,
        request: Request,
        _principal: Annotated[
            Principal, Depends(rate_limited(Scope.READ, RouteClass.SEARCH))
        ],
    ) -> EvidenceSearchResponse:
        request_contract = body.to_contract()
        request_id = str(request.scope.get("state", {}).get("request_id", ""))
        result = await capabilities(request).search_evidence(
            request_contract, request_id=request_id
        )
        try:
            return EvidenceSearchResponse.from_contract(result)
        except ValidationError:
            raise AppError(
                "invalid_service_response",
                "The search service returned an invalid response.",
                500,
            ) from None

    @router.get(
        "/v1/papers/{paper_id}",
        response_model=PaperReadResponse,
        summary="Read paper metadata and selected version",
        description="Metadata-only representation; no source passage or abstract text is returned.",
    )
    async def read_paper(
        request: Request,
        _principal: Annotated[
            Principal, Depends(rate_limited(Scope.READ, RouteClass.PAPER_READ))
        ],
        paper_id: str = Path(pattern=r"^W[0-9]+$"),
        snapshot_id: UUID = Query(),
    ) -> PaperReadResponse:
        result = await capabilities(request).read_paper(snapshot_id, paper_id)
        try:
            return PaperReadResponse.from_contract(result)
        except ValidationError:
            raise AppError(
                "invalid_service_response",
                "The paper service returned an invalid response.",
                500,
            ) from None

    async def graph_page(
        request: Request,
        paper_id: str,
        snapshot_id: UUID,
        direction: CitationDirection,
        limit: int,
        cursor_value: str | None,
    ) -> CitationGraphResponse:
        result, next_cursor = await capabilities(request).citation_page(
            snapshot_id,
            paper_id,
            direction,
            limit=limit,
            cursor=cursor_value,
        )
        return CitationGraphResponse.from_contract(result, next_cursor=next_cursor)

    @router.get(
        "/v1/papers/{paper_id}/references",
        response_model=CitationGraphResponse,
        summary="Read stored one-hop references",
    )
    async def read_references(
        request: Request,
        _principal: Annotated[
            Principal, Depends(rate_limited(Scope.READ, RouteClass.PAPER_READ))
        ],
        paper_id: str = Path(pattern=r"^W[0-9]+$"),
        snapshot_id: UUID = Query(),
        limit: int = Query(default=20, ge=1, le=100),
        cursor: str | None = Query(default=None, max_length=MAX_CURSOR_CHARS),
    ) -> CitationGraphResponse:
        return await graph_page(
            request, paper_id, snapshot_id, CitationDirection.REFERENCES, limit, cursor
        )

    @router.get(
        "/v1/papers/{paper_id}/citations",
        response_model=CitationGraphResponse,
        summary="Read stored one-hop citations",
        description="Returns locally observed incoming edges; it does not discover global citations.",
    )
    async def read_citations(
        request: Request,
        _principal: Annotated[
            Principal, Depends(rate_limited(Scope.READ, RouteClass.PAPER_READ))
        ],
        paper_id: str = Path(pattern=r"^W[0-9]+$"),
        snapshot_id: UUID = Query(),
        limit: int = Query(default=20, ge=1, le=100),
        cursor: str | None = Query(default=None, max_length=MAX_CURSOR_CHARS),
    ) -> CitationGraphResponse:
        return await graph_page(
            request, paper_id, snapshot_id, CitationDirection.CITATIONS, limit, cursor
        )

    return router
