"""FastAPI application construction and health endpoint."""

from typing import Literal

from fastapi import FastAPI, Response
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
) -> FastAPI:
    """Create the HTTP application with its core routes."""

    settings = settings or Settings()
    configure_logging(settings.log_level)
    dependency_checker = dependency_checker or LiveDependencyChecker(settings)
    app = FastAPI(
        title="Scientific Research Platform",
        version="0.1.0",
    )
    app.add_middleware(RequestLoggingMiddleware)
    app.add_middleware(RequestIDMiddleware)
    app.add_exception_handler(AppError, handle_app_error)
    app.add_exception_handler(Exception, handle_unexpected_error)

    @app.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse(status="ok")

    @app.get("/ready", response_model=ReadyResponse)
    async def ready(response: Response) -> ReadyResponse:
        report: ReadinessReport = await dependency_checker.check()
        if not report.ready:
            response.status_code = 503
        return ReadyResponse(
            status="ready" if report.ready else "not_ready",
            dependencies={
                name: "ok" if available else "unavailable"
                for name, available in report.dependencies.items()
            },
        )

    return app
