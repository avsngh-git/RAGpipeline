"""Safe API error types and exception handlers."""

import logging
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from research_platform.observability.request_context import get_request_id

logger = logging.getLogger("research_platform.errors")


class ErrorBody(BaseModel):
    """Public details for one API error."""

    code: str
    message: str
    request_id: str | None


class ErrorResponse(BaseModel):
    """Envelope used for all handled API errors."""

    error: ErrorBody


class AppError(Exception):
    """An expected application failure safe to expose to the client."""

    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        if not 400 <= status_code <= 599:
            raise ValueError("status_code must be between 400 and 599")
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def _request_id(request: Request) -> str | None:
    return get_request_id() or request.headers.get("x-request-id")


async def handle_app_error(_request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, AppError):
        raise RuntimeError("handle_app_error received an unexpected exception")

    response = ErrorResponse(
        error=ErrorBody(
            code=exc.code,
            message=exc.message,
            request_id=get_request_id(),
        )
    )
    return JSONResponse(status_code=exc.status_code, content=response.model_dump())


async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    logger.exception(
        "unhandled_exception",
        extra={"path": request.url.path},
    )
    response = ErrorResponse(
        error=ErrorBody(
            code="internal_error",
            message="An unexpected error occurred.",
            request_id=_request_id(request),
        )
    )
    content: dict[str, Any] = response.model_dump()
    return JSONResponse(status_code=500, content=content)
