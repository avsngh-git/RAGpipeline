"""HTTP API-key authentication and scope dependencies."""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Final, Literal

from fastapi import Request

from research_platform.auth.keys import (
    LOCAL_PRINCIPAL,
    ApiKeyStore,
    Principal,
    Scope,
)
from research_platform.observability.metrics import AUTH_FAILURES

from .errors import AppError

AuthMode = Literal["api_key", "disabled"]
_LOOPBACK: Final = frozenset({"127.0.0.1", "localhost", "::1"})


@dataclass(frozen=True)
class AuthSettings:
    """Authentication mode and API listener binding."""

    mode: AuthMode
    bind_host: str

    @classmethod
    def from_env(
        cls, environment: str, environ: Mapping[str, str] | None = None
    ) -> AuthSettings:
        values = environ if environ is not None else os.environ
        default_mode: AuthMode = "disabled" if environment == "test" else "api_key"
        mode = values.get("RESEARCH_PLATFORM_AUTH_MODE", default_mode)
        if mode not in ("api_key", "disabled"):
            raise ValueError("RESEARCH_PLATFORM_AUTH_MODE must be api_key or disabled")
        return cls(
            mode=mode,  # type: ignore[arg-type]
            bind_host=values.get("RESEARCH_PLATFORM_API_BIND_HOST", "127.0.0.1"),
        )

    def validate(self, environment: str) -> None:
        if self.mode == "disabled" and (
            environment == "production" or self.bind_host not in _LOOPBACK
        ):
            raise ValueError(
                "auth mode disabled is allowed only for loopback development or tests"
            )


def require_scope(scope: Scope) -> Callable[[Request], Awaitable[Principal]]:
    """Return a dependency that authenticates a request for one scope."""

    async def dependency(request: Request) -> Principal:
        settings: AuthSettings = request.app.state.auth_settings
        if settings.mode == "disabled":
            return LOCAL_PRINCIPAL

        authorization = request.headers.get("authorization")
        if authorization is None or not authorization.lower().startswith("bearer "):
            AUTH_FAILURES.labels("missing").inc()
            raise AppError(
                "authentication_required",
                "An API key is required.",
                401,
                headers={"WWW-Authenticate": "Bearer"},
            )

        store: ApiKeyStore | None = getattr(request.app.state, "api_key_store", None)
        if store is None:
            raise AppError(
                "authentication_unavailable",
                "Authentication is not available.",
                503,
            )

        token = authorization[7:].strip()
        principal = await store.authenticate(token)
        if principal is None:
            AUTH_FAILURES.labels("invalid").inc()
            raise AppError(
                "invalid_api_key",
                "The API key is not valid.",
                401,
                headers={"WWW-Authenticate": "Bearer"},
            )
        if not principal.has(scope):
            AUTH_FAILURES.labels("scope").inc()
            raise AppError(
                "insufficient_scope",
                "The API key lacks the required scope.",
                403,
            )
        request.state.principal = principal
        return principal

    return dependency
