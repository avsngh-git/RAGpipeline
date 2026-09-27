"""FastAPI application construction and core health/search routes."""

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator, Literal

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel

from research_platform.config import Settings
from research_platform.observability.logging_config import configure_logging
from research_platform.observability.request_context import RequestIDMiddleware
from research_platform.observability.request_logging import RequestLoggingMiddleware
from research_platform.services.readiness import (
    LiveDependencyChecker,
    ReadinessChecker,
    ReadinessReport,
)

from .errors import AppError, handle_app_error, handle_unexpected_error
from .routes import Phase2APIServices, create_phase2_router

logger = logging.getLogger("research_platform.api")


class HealthResponse(BaseModel):
    """Response returned by the process liveness endpoint."""

    status: Literal["ok"]


class ReadyResponse(BaseModel):
    """Response returned by dependency readiness checks."""

    status: Literal["ready", "not_ready"]
    dependencies: dict[str, Literal["ok", "unavailable"]]


def create_app(
    settings: Settings | None = None,
    dependency_checker: ReadinessChecker | None = None,
    api_services: Phase2APIServices | None = None,
) -> FastAPI:
    """Create the HTTP application with health and Phase 2 routes."""
    settings = settings or Settings()
    configure_logging(settings.log_level)
    dependency_checker = dependency_checker or LiveDependencyChecker(settings)

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        runtime = None
        application.state.phase2_runtime_ready = (
            True if api_services is not None else None
        )
        if api_services is None and settings.environment != "test":
            try:
                from research_platform.search.application import create_phase2_runtime

                runtime = await create_phase2_runtime(settings)
                application.state.phase2_services = runtime.api_services
                application.state.phase2_runtime_ready = True
            except Exception as error:
                application.state.phase2_services = None
                application.state.phase2_runtime_ready = False
                logger.error(
                    "phase2_runtime_unavailable",
                    extra={"error_type": type(error).__name__},
                )
        try:
            yield
        finally:
            if runtime is not None:
                await runtime.close()

    app = FastAPI(
        title="Scientific Research Platform",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.phase2_services = api_services
    app.add_middleware(RequestLoggingMiddleware)
    app.add_middleware(RequestIDMiddleware)
    app.add_exception_handler(AppError, handle_app_error)
    app.add_exception_handler(Exception, handle_unexpected_error)

    async def handle_validation_error(request: Request, _exc: Exception) -> Response:
        return await handle_app_error(
            request,
            AppError("invalid_request", "Request validation failed.", 422),
        )

    app.add_exception_handler(RequestValidationError, handle_validation_error)

    @app.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse(status="ok")

    @app.get("/ready", response_model=ReadyResponse)
    async def ready(response: Response) -> ReadyResponse:
        report: ReadinessReport = await dependency_checker.check()
        dependencies: dict[str, Literal["ok", "unavailable"]] = {
            name: "ok" if available else "unavailable"
            for name, available in report.dependencies.items()
        }
        runtime_ready = getattr(app.state, "phase2_runtime_ready", None)
        if runtime_ready is False:
            dependencies["phase2_search"] = "unavailable"
        elif runtime_ready is True and api_services is None:
            dependencies["phase2_search"] = "ok"
        ready_status = all(value == "ok" for value in dependencies.values())
        if not ready_status:
            response.status_code = 503
        return ReadyResponse(
            status="ready" if ready_status else "not_ready",
            dependencies=dependencies,
        )

    app.include_router(create_phase2_router(settings, api_services))
    return app
