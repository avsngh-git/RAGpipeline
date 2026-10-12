"""Context for the authenticated caller of an MCP request."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Final

from research_platform.auth.keys import Principal
from research_platform.services.errors import AppError

_CURRENT: Final[ContextVar[Principal | None]] = ContextVar(
    "research_mcp_principal", default=None
)


def current_principal() -> Principal:
    """The authenticated caller of the MCP request being handled."""
    principal = _CURRENT.get()
    if principal is None:
        raise AppError("authentication_required", "An API key is required.", 401)
    return principal


@contextmanager
def principal_context(principal: Principal) -> Iterator[None]:
    """Make ``principal`` the current caller until the block ends."""
    token: Token[Principal | None] = _CURRENT.set(principal)
    try:
        yield
    finally:
        _CURRENT.reset(token)
