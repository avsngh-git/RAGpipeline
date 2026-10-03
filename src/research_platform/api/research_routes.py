"""HTTP routes for starting and inspecting research runs."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from fastapi import APIRouter, Request, status

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
        body: ResearchRequest, request: Request
    ) -> ResearchRunView:
        active = _active_services(request, services)
        if active is None:
            raise _service_unavailable()
        if (
            body.snapshot_id is not None
            and body.snapshot_id != active.serving.snapshot_id
        ):
            raise AppError(
                "incompatible_snapshot",
                "The requested snapshot is not served by this server.",
                status_code=409,
            )

        run_id = await active.store.create_run(body)
        queued_view = await active.store.get_run_view(run_id)
        try:
            await active.executor.submit(run_id)
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
    async def get_research(run_id: UUID, request: Request) -> ResearchRunView:
        active = _active_services(request, services)
        if active is None:
            raise _service_unavailable()
        try:
            return await active.store.get_run_view(run_id)
        except RunNotFound:
            raise AppError(
                "run_not_found", "The requested research run does not exist.", 404
            ) from None

    return router
