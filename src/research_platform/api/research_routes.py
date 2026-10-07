"""HTTP routes for starting and inspecting research runs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status

from research_platform.auth.keys import Principal, Scope
from research_platform.observability.request_context import get_request_id
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

from .errors import AppError
from .rate_limits import RouteClass, rate_limited


@dataclass(frozen=True)
class ResearchAPIServices:
    """Services used by the research HTTP transport."""

    store: RunStore
    executor: RunExecutor
    serving: ServingIdentity


def _active_services(
    request: Request, injected: ResearchAPIServices | None
) -> ResearchAPIServices | None:
    if injected is not None:
        return injected
    state = request.app.state
    value = getattr(state, "research_services", None)
    return value if isinstance(value, ResearchAPIServices) else None


def _service_unavailable() -> AppError:
    return AppError(
        "service_unavailable",
        "The research service is not configured.",
        status_code=503,
    )


def create_research_router(
    services: ResearchAPIServices | None,
) -> APIRouter:
    """Build the HTTP adapter for persisted research runs."""
    router = APIRouter()

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
        active = _active_services(request, services)
        if active is None:
            raise _service_unavailable()
        if (
            await active.store.count_active_runs(principal.name)
            >= request.app.state.rate_limit_settings.max_active_runs_per_principal
        ):
            raise AppError(
                "too_many_active_runs",
                "Too many research runs are active for this key.",
                429,
                headers={"Retry-After": "30"},
            )
        if (
            body.snapshot_id is not None
            and body.snapshot_id != active.serving.snapshot_id
        ):
            raise AppError(
                "incompatible_snapshot",
                "The requested snapshot is not served by this server.",
                status_code=409,
            )

        run_id = await active.store.create_run(
            body, generation=active.serving.generation, principal=principal.name
        )
        queued_view = await active.store.get_run_view(run_id)
        try:
            await active.executor.submit(run_id, request_id=get_request_id())
        except ResearchQueueFull:
            await active.store.fail_run(
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
        active = _active_services(request, services)
        if active is None:
            raise _service_unavailable()
        try:
            stored = await active.store.get_run(run_id)
        except RunNotFound:
            raise AppError(
                "run_not_found", "The requested research run does not exist.", 404
            ) from None
        if stored.principal != principal.name and not principal.has(Scope.ADMIN):
            raise AppError(
                "run_not_found", "The requested research run does not exist.", 404
            )
        return await active.store.get_run_view(run_id)

    return router
