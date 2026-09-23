"""HTTP request logging middleware."""

import logging
from time import perf_counter

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .request_context import get_request_id

logger = logging.getLogger("research_platform.http")


class RequestLoggingMiddleware:
    """Log safe request completion or failure metadata."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        started_at = perf_counter()
        status_code = 500

        async def send_with_status(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await send(message)

        fields = {
            "http_method": scope.get("method", ""),
            "path": scope.get("path", ""),
            "request_id": get_request_id(),
        }

        try:
            await self.app(scope, receive, send_with_status)
        except Exception:
            logger.exception(
                "request_failed",
                extra={
                    **fields,
                    "status_code": status_code,
                    "duration_ms": round((perf_counter() - started_at) * 1000, 2),
                },
            )
            raise
        else:
            logger.info(
                "request_completed",
                extra={
                    **fields,
                    "status_code": status_code,
                    "duration_ms": round((perf_counter() - started_at) * 1000, 2),
                },
            )
