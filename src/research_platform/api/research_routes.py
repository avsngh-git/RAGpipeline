"""HTTP routes for starting and inspecting research runs."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status

from research_platform.auth.keys import Principal, Scope
from research_platform.observability.request_context import get_request_id
from research_platform.runs.contracts import ResearchRequest, ResearchRunView
from research_platform.services.capabilities import (
    ResearchAPIServices,
    ResearchCapabilities,
)

from .rate_limits import RouteClass, rate_limited

__all__ = ["ResearchAPIServices", "create_research_router"]


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

    return router
