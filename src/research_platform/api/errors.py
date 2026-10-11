"""Safe API error types and exception handlers."""

import logging
from collections.abc import Mapping
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from research_platform.observability.request_context import (
    REQUEST_ID_HEADER,
    get_request_id,
)

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

    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 400,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        if not 400 <= status_code <= 599:
            raise ValueError("status_code must be between 400 and 599")
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.headers = dict(headers or {})


def _request_id(request: Request) -> str | None:
    state = request.scope.get("state", {})
    request_id = state.get("request_id")
    return request_id if isinstance(request_id, str) else get_request_id()


async def handle_app_error(_request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, AppError):
        raise RuntimeError("handle_app_error received an unexpected exception")

    request_id = _request_id(_request)
    response = ErrorResponse(
        error=ErrorBody(
            code=exc.code,
            message=exc.message,
            request_id=request_id,
        )
    )
    headers = dict(exc.headers)
    if request_id:
        headers[REQUEST_ID_HEADER] = request_id
    return JSONResponse(
        status_code=exc.status_code,
        content=response.model_dump(),
        headers=headers or None,
    )


# Codes for errors raised by Starlette and FastAPI themselves (unknown routes, wrong
# methods, the body limit), so every handled error uses the same envelope.
_HTTP_ERROR_CODES: dict[int, tuple[str, str]] = {
    400: ("invalid_request", "The request could not be parsed."),
    404: ("not_found", "The requested resource was not found."),
    405: ("method_not_allowed", "The method is not allowed for this resource."),
    413: ("request_too_large", "The request body is too large."),
}


async def handle_http_error(request: Request, exc: Exception) -> JSONResponse:
    """Wrap a Starlette or FastAPI HTTPException in the error envelope.

    Its own detail text is not exposed; its headers (for example ``Allow``) are kept.
    """
    if not isinstance(exc, StarletteHTTPException):
        raise RuntimeError("handle_http_error received an unexpected exception")
    code, message = _HTTP_ERROR_CODES.get(
        exc.status_code, ("http_error", "The request could not be completed.")
    )
    return await handle_app_error(
        request,
        AppError(code, message, exc.status_code, headers=exc.headers or None),
    )


async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    request_id = _request_id(request)
    logger.exception(
        "unhandled_exception",
        extra={"path": request.url.path, "request_id": request_id},
    )
    response = ErrorResponse(
        error=ErrorBody(
            code="internal_error",
            message="An unexpected error occurred.",
            request_id=request_id,
        )
    )
    content: dict[str, Any] = response.model_dump()
    headers = {REQUEST_ID_HEADER: request_id} if request_id else None
    return JSONResponse(status_code=500, content=content, headers=headers)
