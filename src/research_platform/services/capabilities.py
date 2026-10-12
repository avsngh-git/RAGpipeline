"""Research use cases shared by the HTTP API and the MCP server."""

from __future__ import annotations

from asyncio import CancelledError, timeout
from asyncio import TimeoutError as AsyncTimeoutError
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol, cast
from uuid import UUID

from pydantic import ValidationError

from research_platform.auth.keys import Principal, Scope
from research_platform.config import Settings
from research_platform.ingestion.indexing import SnapshotIndexMismatch
from research_platform.runs.contracts import (
    FailureCategory,
    ResearchRequest,
    ResearchRunView,
    RunUsage,
)
from research_platform.runs.executor import ResearchQueueFull, RunExecutor
from research_platform.runs.repository import RunNotFound
from research_platform.runs.runner import ServingIdentity
from research_platform.runs.store import RunStore
from research_platform.search.application_errors import (
    IncompatibleRetrievalProfile,
    RetrievalExecutionFailure,
    SearchDependencyUnavailable,
)
from research_platform.search.contracts import (
    DEFAULT_SEARCH_LIMITS,
    EvidenceHit,
    PaperHit,
    SearchOperation,
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
from research_platform.search.paper_related import RelatedPapersPage
from research_platform.services.citation_cursor import decode_cursor, encode_cursor
from research_platform.services.errors import AppError


@dataclass(frozen=True)
class ResearchAPIServices:
    """Services used by the research HTTP transport."""

    store: RunStore
    executor: RunExecutor
    serving: ServingIdentity


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


class RelatedReader(Protocol):
    async def find_related(
        self, snapshot_id: UUID, paper_id: str, *, limit: int = 10
    ) -> RelatedPapersPage: ...


class Phase2APIServices:
    """Injected application services for retrieval, metadata and graph reads."""

    def __init__(
        self,
        *,
        search: SearchExecutor | None = None,
        papers: PaperReader | None = None,
        citations: CitationReader | None = None,
        related: RelatedReader | None = None,
    ) -> None:
        self.search = search
        self.papers = papers
        self.citations = citations
        self.related = related


def service_unavailable(name: str) -> AppError:
    return AppError(
        "service_unavailable",
        f"The {name} service is not configured.",
        status_code=503,
    )


def safe_call_error(error: Exception) -> AppError:
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


async def bounded_call(operation: Callable[[], Awaitable[Any]]) -> Any:
    try:
        async with timeout(DEFAULT_SEARCH_LIMITS.request_timeout_seconds):
            return await operation()
    except (CancelledError, KeyboardInterrupt, SystemExit):
        raise
    except Exception as error:
        raise safe_call_error(error) from None


def require_private_evidence(settings: Settings) -> None:
    if settings.evidence_access_profile != "trusted_private_local":
        raise AppError(
            "permission_denied",
            "Source-linked evidence is disabled for this server profile.",
            status_code=403,
        )


@dataclass(frozen=True)
class ResearchCapabilities:
    """The research use cases; transports map their inputs and outputs."""

    settings: Settings
    phase2: Phase2APIServices | None
    research: ResearchAPIServices | None = None
    max_active_runs_per_principal: int = 2

    @classmethod
    def from_app_state(cls, state: Any) -> ResearchCapabilities:
        phase2 = getattr(state, "phase2_services", None)
        research = getattr(state, "research_services", None)
        return cls(
            settings=state.settings,
            phase2=phase2 if isinstance(phase2, Phase2APIServices) else None,
            research=research if isinstance(research, ResearchAPIServices) else None,
            max_active_runs_per_principal=(
                state.rate_limit_settings.max_active_runs_per_principal
                if hasattr(state, "rate_limit_settings")
                else 2
            ),
        )

    def serving(self) -> ServingIdentity:
        if self.research is None:
            raise AppError(
                "service_unavailable",
                "The research service is not configured.",
                status_code=503,
            )
        return self.research.serving

    def resolve_snapshot(self, snapshot_id: UUID | None) -> ServingIdentity:
        serving = self.serving()
        if snapshot_id is not None and snapshot_id != serving.snapshot_id:
            raise AppError(
                "incompatible_snapshot",
                "The requested snapshot is not served by this server.",
                status_code=409,
            )
        return serving

    async def start_run(
        self,
        request: ResearchRequest,
        *,
        principal: Principal,
        request_id: str | None,
    ) -> ResearchRunView:
        research = self.research
        if research is None:
            raise AppError(
                "service_unavailable",
                "The research service is not configured.",
                status_code=503,
            )
        if (
            await research.store.count_active_runs(principal.name)
            >= self.max_active_runs_per_principal
        ):
            raise AppError(
                "too_many_active_runs",
                "Too many research runs are active for this key.",
                429,
                headers={"Retry-After": "30"},
            )
        if (
            request.snapshot_id is not None
            and request.snapshot_id != research.serving.snapshot_id
        ):
            raise AppError(
                "incompatible_snapshot",
                "The requested snapshot is not served by this server.",
                status_code=409,
            )

        run_id = await research.store.create_run(
            request,
            generation=research.serving.generation,
            principal=principal.name,
            ingestion_permitted=principal.has(Scope.INGEST),
        )
        queued_view = await research.store.get_run_view(run_id)
        try:
            await research.executor.submit(run_id, request_id=request_id)
        except ResearchQueueFull:
            await research.store.fail_run(
                run_id,
                category=FailureCategory.INTERNAL,
                message="queue_full",
                usage=RunUsage.model_construct(),
            )
            raise AppError(
                "research_queue_full",
                "The research run queue is full.",
                status_code=503,
            ) from None
        return queued_view

    async def get_run(self, run_id: UUID, *, principal: Principal) -> ResearchRunView:
        research = self.research
        if research is None:
            raise AppError(
                "service_unavailable",
                "The research service is not configured.",
                status_code=503,
            )
        try:
            stored = await research.store.get_run(run_id)
        except RunNotFound:
            raise AppError(
                "run_not_found", "The requested research run does not exist.", 404
            ) from None
        if stored.principal != principal.name and not principal.has(Scope.ADMIN):
            raise AppError(
                "run_not_found", "The requested research run does not exist.", 404
            )
        return await research.store.get_run_view(run_id)

    async def search_papers(
        self, request: SearchRequest, *, request_id: str
    ) -> SearchResponse[PaperHit]:
        require_private_evidence(self.settings)
        if self.phase2 is None or self.phase2.search is None:
            raise service_unavailable("search")
        if request.operation is not SearchOperation.PAPER_SEARCH:
            raise AppError("invalid_request", "The request is invalid.", 422)
        search = self.phase2.search
        result = await bounded_call(
            lambda: search.execute(request, request_id=request_id)
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
            result.snapshot_id != request.snapshot_id
            or result.retrieval_profile_id != request.retrieval_profile_id
            or result.requested_mode is not request.mode
        ):
            raise AppError(
                "invalid_service_response",
                "The search service returned a mismatched response.",
                500,
            )
        return result

    async def search_evidence(
        self, request: SearchRequest, *, request_id: str
    ) -> SearchResponse[EvidenceHit]:
        require_private_evidence(self.settings)
        if self.phase2 is None or self.phase2.search is None:
            raise service_unavailable("search")
        if request.operation is not SearchOperation.EVIDENCE_SEARCH:
            raise AppError("invalid_request", "The request is invalid.", 422)
        search = self.phase2.search
        result = await bounded_call(
            lambda: search.execute(request, request_id=request_id)
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
            result.snapshot_id != request.snapshot_id
            or result.retrieval_profile_id != request.retrieval_profile_id
            or result.requested_mode is not request.mode
        ):
            raise AppError(
                "invalid_service_response",
                "The search service returned a mismatched response.",
                500,
            )
        return result

    async def read_paper(self, snapshot_id: UUID, paper_id: str) -> SnapshotPaperRead:
        if self.phase2 is None or self.phase2.papers is None:
            raise service_unavailable("paper metadata")
        papers = self.phase2.papers
        return cast(
            SnapshotPaperRead,
            await bounded_call(lambda: papers.read_paper(snapshot_id, paper_id)),
        )

    async def citation_page(
        self,
        snapshot_id: UUID,
        paper_id: str,
        direction: CitationDirection,
        *,
        limit: int,
        cursor: str | None,
    ) -> tuple[CitationGraphPage, str | None]:
        if self.phase2 is None or self.phase2.citations is None:
            raise service_unavailable("citation graph")
        citations = self.phase2.citations
        decoded = decode_cursor(
            cursor,
            snapshot_id=snapshot_id,
            paper_id=paper_id,
            direction=direction,
        )
        page = await bounded_call(
            lambda: citations.read_one_hop(
                snapshot_id, paper_id, direction, limit=limit, cursor=decoded
            )
        )
        if not isinstance(page, CitationGraphPage):
            raise AppError(
                "invalid_service_response",
                "The citation service returned an invalid response.",
                500,
            )
        return page, encode_cursor(page.next_cursor)

    async def related_papers(
        self, snapshot_id: UUID, paper_id: str, *, limit: int
    ) -> RelatedPapersPage:
        if self.phase2 is None or self.phase2.related is None:
            raise service_unavailable("related papers")
        related = self.phase2.related
        page = await bounded_call(
            lambda: related.find_related(snapshot_id, paper_id, limit=limit)
        )
        if not isinstance(page, RelatedPapersPage):
            raise AppError(
                "invalid_service_response",
                "The related-paper service returned an invalid response.",
                500,
            )
        return page
