"""HTTP request metrics middleware."""

from __future__ import annotations

from time import perf_counter

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .metrics import HTTP_LATENCY, HTTP_REQUESTS


class HttpMetricsMiddleware:
    """Record HTTP requests by route template and status."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        started = perf_counter()
        status = 500

        async def send_with_status(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_with_status)
        finally:
            route = scope.get("route")
            template = getattr(route, "path", None)
            if not isinstance(template, str):
                template = "unmatched"
            if template != "/metrics":
                HTTP_REQUESTS.labels(scope["method"], template, str(status)).inc()
                HTTP_LATENCY.labels(scope["method"], template).observe(
                    perf_counter() - started
                )
