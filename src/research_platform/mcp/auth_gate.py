"""ASGI authentication gate for MCP requests."""

from __future__ import annotations

from typing import Any

from starlette.datastructures import Headers
from starlette.requests import Request
from starlette.types import ASGIApp, Receive, Scope, Send

from research_platform.api.auth import AuthSettings, authenticate_authorization
from research_platform.api.errors import AppError, handle_app_error
from research_platform.auth.keys import ApiKeyStore

from .principal import principal_context


class McpAuthGate:
    """Authenticate every MCP HTTP request with the API's key check."""

    def __init__(self, app: ASGIApp, *, state: Any) -> None:
        self._app = app
        self._state = state

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        authorization = Headers(scope=scope).get("authorization")
        settings: AuthSettings = self._state.auth_settings
        store: ApiKeyStore | None = getattr(self._state, "api_key_store", None)
        try:
            principal = await authenticate_authorization(authorization, settings, store)
        except AppError as error:
            response = await handle_app_error(Request(scope), error)
            await response(scope, receive, send)
            return

        with principal_context(principal):
            await self._app(scope, receive, send)
