"""HTTP adapters for Phase 2 search, paper metadata and citation reads."""

from __future__ import annotations

import base64
import binascii
import json
from asyncio import CancelledError, timeout
from asyncio import TimeoutError as AsyncTimeoutError
from collections.abc import Awaitable, Callable
from typing import Annotated, Any, Protocol
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query, Request
from pydantic import ValidationError

from research_platform.auth.keys import Principal, Scope
from research_platform.config import Settings
from research_platform.ingestion.indexing import SnapshotIndexMismatch
from research_platform.search.application_errors import (
    IncompatibleRetrievalProfile,
    RetrievalExecutionFailure,
    SearchDependencyUnavailable,
)
from research_platform.search.contracts import (
    DEFAULT_SEARCH_LIMITS,
    EvidenceHit,
    PaperHit,
    SearchRequest,
    SearchResponse,
)
from research_platform.search.paper_graph import (
    CitationDirection,
    CitationGraphCursor,
    CitationGraphPage,
)
from research_platform.search.paper_reads import (
    PaperIdentityConflict,
    SnapshotNotFound,
    SnapshotPaperRead,
)

from .auth import require_scope
from .errors import AppError
from .schemas.papers import CitationGraphResponse, PaperReadResponse
from .schemas.search import (
    EvidenceSearchRequest,
    EvidenceSearchResponse,
    PaperSearchRequest,
    PaperSearchResponse,
)

_MAX_CURSOR_CHARS = 2048


class SearchExecutor(Protocol):
    """Reusable framework-independent application service for ranked retrieval."""

    async def execute(
        self, request: SearchRequest, *, request_id: str
    ) -> SearchResponse[Any]: ...


class PaperReader(Protocol):
    async def read_paper(
        self, snapshot_id: UUID, paper_id: str
    ) -> SnapshotPaperRead: ...


class CitationReader(Protocol):
    async def read_one_hop(
        self,
        snapshot_id: UUID,
        paper_id: str,
        direction: CitationDirection,
        *,
        limit: int = 20,
        cursor: CitationGraphCursor | None = None,
    ) -> CitationGraphPage: ...


class Phase2APIServices:
    """Injected application services; routes contain no SQL or ranking logic."""

    def __init__(
        self,
        *,
        search: SearchExecutor | None = None,
        papers: PaperReader | None = None,
        citations: CitationReader | None = None,
    ) -> None:
        self.search = search
        self.papers = papers
        self.citations = citations


def _services_for_request(
    request: Request, injected: Phase2APIServices | None
) -> Phase2APIServices | None:
    if injected is not None:
        return injected
    value = getattr(request.app.state, "phase2_services", None)
    return value if isinstance(value, Phase2APIServices) else None


def _service_unavailable(name: str) -> AppError:
    return AppError(
        "service_unavailable",
        f"The {name} service is not configured.",
        status_code=503,
    )


def _safe_call_error(error: Exception) -> AppError:
    if isinstance(error, AppError):
        return error
    if isinstance(error, SnapshotNotFound):
        return AppError(
            "snapshot_not_found", "The requested snapshot does not exist.", 404
        )
    if isinstance(error, PaperIdentityConflict):
        return AppError(
            "paper_identity_conflict", "The paper identity is ambiguous.", 409
        )
    if isinstance(error, IncompatibleRetrievalProfile):
        return AppError(
            "incompatible_profile",
            "The retrieval profile does not match this request or snapshot.",
            409,
        )
    if isinstance(error, (SearchDependencyUnavailable, RetrievalExecutionFailure)):
        return AppError(
            "dependency_unavailable",
            "A required retrieval component is unavailable.",
            503,
        )
    if isinstance(error, SnapshotIndexMismatch):
        return AppError(
            "incompatible_profile",
            "The retrieval profile does not match the ready snapshot index.",
            409,
        )
    if isinstance(error, PermissionError):
        return AppError(
            "permission_denied", "The requested evidence is not permitted.", 403
        )
    if isinstance(error, AsyncTimeoutError):
        return AppError(
            "request_timeout", "The search request exceeded its deadline.", 504
        )
    if isinstance(error, (ValueError, ValidationError)):
        return AppError("invalid_request", "The request is invalid.", 422)
    return AppError("internal_error", "The request could not be completed.", 500)


async def _bounded(settings: Settings, operation: Callable[[], Awaitable[Any]]) -> Any:
    try:
        async with timeout(DEFAULT_SEARCH_LIMITS.request_timeout_seconds):
            return await operation()
    except (CancelledError, KeyboardInterrupt, SystemExit):
        raise
    except Exception as error:
        raise _safe_call_error(error) from None


def _encode_cursor(cursor: CitationGraphCursor | None) -> str | None:
    if cursor is None:
        return None
    payload = {
        "snapshot_id": str(cursor.snapshot_id),
        "paper_id": cursor.paper_id,
        "direction": cursor.direction.value,
        "endpoint_kind": cursor.endpoint_kind,
        "endpoint_identifier": cursor.endpoint_identifier,
        "edge_source": cursor.edge_source,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(
    value: str | None,
    *,
    snapshot_id: UUID,
    paper_id: str,
    direction: CitationDirection,
) -> CitationGraphCursor | None:
    if value is None:
        return None
    if not value or len(value) > _MAX_CURSOR_CHARS:
        raise AppError("invalid_cursor", "The citation cursor is invalid.", 422)
    try:
        encoded = value.encode("ascii")
        padding = b"=" * (-len(encoded) % 4)
        raw = base64.b64decode(encoded + padding, altchars=b"-_", validate=True)
        payload = json.loads(raw)
        if not isinstance(payload, dict) or set(payload) != {
            "snapshot_id",
            "paper_id",
            "direction",
            "endpoint_kind",
            "endpoint_identifier",
            "edge_source",
        }:
            raise ValueError
        cursor = CitationGraphCursor(
            snapshot_id=UUID(payload["snapshot_id"]),
            paper_id=payload["paper_id"],
            direction=CitationDirection(payload["direction"]),
            endpoint_kind=payload["endpoint_kind"],
            endpoint_identifier=payload["endpoint_identifier"],
            edge_source=payload["edge_source"],
        )
    except (
        UnicodeEncodeError,
        binascii.Error,
        json.JSONDecodeError,
        TypeError,
        ValueError,
        KeyError,
    ):
        raise AppError(
            "invalid_cursor", "The citation cursor is invalid.", 422
        ) from None
    if (
        cursor.snapshot_id != snapshot_id
        or cursor.paper_id != paper_id
        or cursor.direction is not direction
    ):
        raise AppError(
            "invalid_cursor", "The citation cursor does not match this request.", 422
        )
    return cursor


def _require_private_evidence(settings: Settings) -> None:
    if settings.evidence_access_profile != "trusted_private_local":
        raise AppError(
            "permission_denied",
            "Source-linked evidence is disabled for this server profile.",
            status_code=403,
        )


def create_phase2_router(
    settings: Settings, services: Phase2APIServices | None
) -> APIRouter:
    """Create the transport adapter for the approved Phase 2 service contracts."""
    router = APIRouter()

    @router.post(
        "/v1/search",
        response_model=PaperSearchResponse,
        summary="Search for distinct papers",
        description="Returns ranked papers and bounded source-linked support. Scores are ranking signals, not probabilities.",
    )
    async def search_papers(
        body: PaperSearchRequest,
        request: Request,
        _principal: Annotated[Principal, Depends(require_scope(Scope.READ))],
    ) -> PaperSearchResponse:
        _require_private_evidence(settings)
        active_services = _services_for_request(request, services)
        if active_services is None or active_services.search is None:
            raise _service_unavailable("search")
        search_executor = active_services.search
        request_contract = body.to_contract()
        request_id = str(request.scope.get("state", {}).get("request_id", ""))
        result = await _bounded(
            settings,
            lambda: search_executor.execute(request_contract, request_id=request_id),
        )
        if not isinstance(result, SearchResponse) or any(
            not isinstance(hit, PaperHit) for hit in result.hits
        ):
            raise AppError(
                "invalid_service_response",
                "The search service returned an invalid response.",
                500,
            )
        if (
            result.snapshot_id != request_contract.snapshot_id
            or result.retrieval_profile_id != request_contract.retrieval_profile_id
            or result.requested_mode is not request_contract.mode
        ):
            raise AppError(
                "invalid_service_response",
                "The search service returned a mismatched response.",
                500,
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
        _principal: Annotated[Principal, Depends(require_scope(Scope.READ))],
    ) -> EvidenceSearchResponse:
        _require_private_evidence(settings)
        active_services = _services_for_request(request, services)
        if active_services is None or active_services.search is None:
            raise _service_unavailable("search")
        search_executor = active_services.search
        request_contract = body.to_contract()
        request_id = str(request.scope.get("state", {}).get("request_id", ""))
        result = await _bounded(
            settings,
            lambda: search_executor.execute(request_contract, request_id=request_id),
        )
        if not isinstance(result, SearchResponse) or any(
            not isinstance(hit, EvidenceHit) for hit in result.hits
        ):
            raise AppError(
                "invalid_service_response",
                "The search service returned an invalid response.",
                500,
            )
        if (
            result.snapshot_id != request_contract.snapshot_id
            or result.retrieval_profile_id != request_contract.retrieval_profile_id
            or result.requested_mode is not request_contract.mode
        ):
            raise AppError(
                "invalid_service_response",
                "The search service returned a mismatched response.",
                500,
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
        _principal: Annotated[Principal, Depends(require_scope(Scope.READ))],
        paper_id: str = Path(pattern=r"^W[0-9]+$"),
        snapshot_id: UUID = Query(),
    ) -> PaperReadResponse:
        active_services = _services_for_request(request, services)
        if active_services is None or active_services.papers is None:
            raise _service_unavailable("paper metadata")
        paper_reader = active_services.papers
        result = await _bounded(
            settings,
            lambda: paper_reader.read_paper(snapshot_id, paper_id),
        )
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
        active_services = _services_for_request(request, services)
        if active_services is None or active_services.citations is None:
            raise _service_unavailable("citation graph")
        citation_reader = active_services.citations
        cursor = _decode_cursor(
            cursor_value,
            snapshot_id=snapshot_id,
            paper_id=paper_id,
            direction=direction,
        )
        result = await _bounded(
            settings,
            lambda: citation_reader.read_one_hop(
                snapshot_id,
                paper_id,
                direction,
                limit=limit,
                cursor=cursor,
            ),
        )
        if not isinstance(result, CitationGraphPage):
            raise AppError(
                "invalid_service_response",
                "The citation service returned an invalid response.",
                500,
            )
        return CitationGraphResponse.from_contract(
            result, next_cursor=_encode_cursor(result.next_cursor)
        )

    @router.get(
        "/v1/papers/{paper_id}/references",
        response_model=CitationGraphResponse,
        summary="Read stored one-hop references",
    )
    async def read_references(
        request: Request,
        _principal: Annotated[Principal, Depends(require_scope(Scope.READ))],
        paper_id: str = Path(pattern=r"^W[0-9]+$"),
        snapshot_id: UUID = Query(),
        limit: int = Query(default=20, ge=1, le=100),
        cursor: str | None = Query(default=None, max_length=_MAX_CURSOR_CHARS),
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
        _principal: Annotated[Principal, Depends(require_scope(Scope.READ))],
        paper_id: str = Path(pattern=r"^W[0-9]+$"),
        snapshot_id: UUID = Query(),
        limit: int = Query(default=20, ge=1, le=100),
        cursor: str | None = Query(default=None, max_length=_MAX_CURSOR_CHARS),
    ) -> CitationGraphResponse:
        return await graph_page(
            request, paper_id, snapshot_id, CitationDirection.CITATIONS, limit, cursor
        )

    return router
