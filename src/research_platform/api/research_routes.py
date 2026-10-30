"""HTTP routes for starting and inspecting research runs."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query, Request, status
from pydantic import BaseModel, ConfigDict

from research_platform.auth.keys import Principal, Scope
from research_platform.observability.request_context import get_request_id
from research_platform.runs.contracts import ResearchRequest, ResearchRunView, RunPage
from research_platform.runs.record_views import ModelCallTextView, RunRecordView
from research_platform.services.capabilities import (
    MeView,
    ResearchAPIServices,
    ResearchCapabilities,
)

from .rate_limits import RouteClass, rate_limited

__all__ = ["ResearchAPIServices", "ServingResponse", "create_research_router"]


class ServingResponse(BaseModel):
    """The snapshot and retrieval profile this server answers from."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    snapshot_id: UUID
    retrieval_profile_id: str
    generation: int | None


def _active_services(
    request: Request, injected: ResearchAPIServices | None
) -> ResearchAPIServices | None:
    if injected is not None:
        return injected
    state = request.app.state
    value = getattr(state, "research_services", None)
    return value if isinstance(value, ResearchAPIServices) else None


def create_research_router(
    services: ResearchAPIServices | None,
) -> APIRouter:
    """Build the HTTP adapter for persisted research runs."""
    router = APIRouter()

    def capabilities(request: Request) -> ResearchCapabilities:
        state = request.app.state
        return ResearchCapabilities(
            settings=state.settings,
            phase2=None,
            research=_active_services(request, services),
            max_active_runs_per_principal=(
                state.rate_limit_settings.max_active_runs_per_principal
            ),
        )

    @router.post(
        "/v1/research",
        response_model=ResearchRunView,
        status_code=status.HTTP_202_ACCEPTED,
        summary="Start a research run",
    )
    async def start_research(
        body: ResearchRequest,
        request: Request,
        principal: Annotated[
            Principal, Depends(rate_limited(Scope.RESEARCH, RouteClass.RESEARCH_CREATE))
        ],
    ) -> ResearchRunView:
        return await capabilities(request).start_run(
            body, principal=principal, request_id=get_request_id()
        )

    @router.get(
        "/v1/research", response_model=RunPage, summary="List your research runs"
    )
    async def list_research(
        request: Request,
        principal: Annotated[
            Principal, Depends(rate_limited(Scope.READ, RouteClass.RUN_READ))
        ],
        limit: Annotated[int, Query(ge=1, le=50)] = 20,
        cursor: Annotated[str | None, Query(max_length=512)] = None,
    ) -> RunPage:
        return await capabilities(request).list_runs(
            principal=principal, limit=limit, cursor=cursor
        )

    @router.get("/v1/me", response_model=MeView, summary="Describe the calling key")
    async def get_me(
        request: Request,
        principal: Annotated[
            Principal, Depends(rate_limited(Scope.READ, RouteClass.RUN_READ))
        ],
    ) -> MeView:
        return await capabilities(request).me(principal=principal)

    @router.get(
        "/v1/research/{run_id}",
        response_model=ResearchRunView,
        summary="Get a research run",
    )
    async def get_research(
        run_id: UUID,
        request: Request,
        principal: Annotated[
            Principal, Depends(rate_limited(Scope.READ, RouteClass.RUN_READ))
        ],
    ) -> ResearchRunView:
        return await capabilities(request).get_run(run_id, principal=principal)

    @router.post(
        "/v1/research/{run_id}/cancel",
        response_model=ResearchRunView,
        summary="Cancel a research run",
    )
    async def cancel_research(
        run_id: UUID,
        request: Request,
        principal: Annotated[
            Principal, Depends(rate_limited(Scope.RESEARCH, RouteClass.RUN_READ))
        ],
    ) -> ResearchRunView:
        return await capabilities(request).cancel_run(run_id, principal=principal)

    @router.get(
        "/v1/research/{run_id}/record",
        response_model=RunRecordView,
        summary="Get a research run's record",
    )
    async def get_research_record(
        run_id: UUID,
        request: Request,
        principal: Annotated[
            Principal, Depends(rate_limited(Scope.READ, RouteClass.RUN_READ))
        ],
    ) -> RunRecordView:
        return await capabilities(request).run_record(run_id, principal=principal)

    @router.get(
        "/v1/research/{run_id}/model-calls/{ordinal}",
        response_model=ModelCallTextView,
        summary="Get one model call's text",
    )
    async def get_model_call_text(
        run_id: UUID,
        ordinal: Annotated[int, Path(ge=1, le=1000)],
        request: Request,
        principal: Annotated[
            Principal, Depends(rate_limited(Scope.READ, RouteClass.RUN_READ))
        ],
    ) -> ModelCallTextView:
        return await capabilities(request).model_call_text(
            run_id, ordinal, principal=principal
        )

    @router.get(
        "/v1/serving",
        response_model=ServingResponse,
        summary="Get the served snapshot and retrieval profile",
    )
    async def get_serving(
        request: Request,
        _principal: Annotated[
            Principal, Depends(rate_limited(Scope.READ, RouteClass.RUN_READ))
        ],
    ) -> ServingResponse:
        serving = capabilities(request).serving()
        return ServingResponse(
            snapshot_id=serving.snapshot_id,
            retrieval_profile_id=serving.retrieval_profile_id,
            generation=serving.generation,
        )

    return router
