"""Request body size limit middleware."""

from __future__ import annotations

import json

from starlette.exceptions import HTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class _BodyTooLarge(HTTPException):
    """Raised while reading a streamed body over the limit.

    FastAPI re-raises HTTPException from its body parsing but turns any other
    exception into a 400, so this must be an HTTPException to stay a 413.
    """

    def __init__(self) -> None:
        super().__init__(status_code=413)


class BodySizeLimitMiddleware:
    """Reject request bodies that exceed the configured byte limit."""

    def __init__(self, app: ASGIApp, *, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method") not in {
            "POST",
            "PUT",
            "PATCH",
        }:
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        raw_length = headers.get(b"content-length")
        if raw_length is not None:
            try:
                content_length = int(raw_length)
            except ValueError:
                content_length = 0
            if content_length > self.max_bytes:
                await self._send_error(scope, send)
                return

        received = 0
        response_started = False

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise _BodyTooLarge
            return message

        async def tracking_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except _BodyTooLarge:
            if not response_started:
                await self._send_error(scope, send)

    async def _send_error(self, scope: Scope, send: Send) -> None:
        request_id = scope.get("state", {}).get("request_id")
        body = json.dumps(
            {
                "error": {
                    "code": "request_too_large",
                    "message": "The request body is too large.",
                    "request_id": request_id,
                }
            },
            separators=(",", ":"),
        ).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("ascii")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
