"""Authentication and principal context for the MCP ASGI gate."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import httpx
import pytest
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from research_platform.api.auth import AuthMode, AuthSettings, require_principal_scope
from research_platform.api.errors import AppError
from research_platform.api.rate_limits import (
    Limit,
    RateLimitSettings,
    RouteClass,
    TokenBucketLimiter,
    enforce_rate_limit,
)
from research_platform.auth.keys import InMemoryApiKeyStore, Principal
from research_platform.auth.keys import Scope as ApiScope
from research_platform.mcp.auth_gate import McpAuthGate
from research_platform.mcp.principal import current_principal


def _state(
    *, store: InMemoryApiKeyStore | None = None, mode: AuthMode = "api_key"
) -> SimpleNamespace:
    return SimpleNamespace(
        auth_settings=AuthSettings(mode=mode, bind_host="127.0.0.1"),
        api_key_store=store,
    )


def _inner_app() -> ASGIApp:
    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan":
            while True:
                message = await receive()
                if message["type"] == "lifespan.startup":
                    await send({"type": "lifespan.startup.complete"})
                elif message["type"] == "lifespan.shutdown":
                    await send({"type": "lifespan.shutdown.complete"})
                    return

        body = current_principal().name.encode()
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": body})

    return app


async def _request(gate: McpAuthGate, *, key: str | None = None) -> httpx.Response:
    transport = httpx.ASGITransport(app=gate)
    headers = {} if key is None else {"Authorization": f"Bearer {key}"}
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get("/mcp", headers=headers)


def test_missing_key_is_401_with_the_api_envelope() -> None:
    response = asyncio.run(_request(McpAuthGate(_inner_app(), state=_state())))

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_required"
    assert response.headers["www-authenticate"] == "Bearer"


def test_invalid_key_is_401() -> None:
    store = InMemoryApiKeyStore()
    response = asyncio.run(
        _request(
            McpAuthGate(_inner_app(), state=_state(store=store)), key="rsk_invalid"
        )
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_api_key"


def test_valid_key_reaches_the_app_as_its_principal() -> None:
    store = InMemoryApiKeyStore()
    _, key = asyncio.run(store.create("mcp-client", (ApiScope.READ,)))
    response = asyncio.run(
        _request(McpAuthGate(_inner_app(), state=_state(store=store)), key=key)
    )

    assert response.status_code == 200
    assert response.text == "mcp-client"


def test_disabled_mode_is_the_local_principal() -> None:
    response = asyncio.run(
        _request(McpAuthGate(_inner_app(), state=_state(mode="disabled")))
    )

    assert response.status_code == 200
    assert response.text == "local"


def test_missing_store_is_503() -> None:
    state = _state()
    del state.api_key_store
    response = asyncio.run(
        _request(McpAuthGate(_inner_app(), state=state), key="rsk_invalid")
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "authentication_unavailable"


def test_store_is_read_per_request() -> None:
    state = _state()
    gate = McpAuthGate(_inner_app(), state=state)
    store = InMemoryApiKeyStore()
    _, key = asyncio.run(store.create("late-store", (ApiScope.READ,)))
    state.api_key_store = store

    response = asyncio.run(_request(gate, key=key))

    assert response.status_code == 200
    assert response.text == "late-store"


def test_principal_is_reset_after_the_request() -> None:
    store = InMemoryApiKeyStore()
    _, key = asyncio.run(store.create("temporary", (ApiScope.READ,)))
    asyncio.run(_request(McpAuthGate(_inner_app(), state=_state(store=store)), key=key))

    with pytest.raises(AppError) as caught:
        current_principal()
    assert caught.value.status_code == 401


def test_non_http_scopes_pass_through() -> None:
    seen: list[str] = []

    async def inner(scope: Scope, receive: Receive, send: Send) -> None:
        seen.append(scope["type"])
        message = await receive()
        assert message["type"] == "lifespan.startup"
        await send({"type": "lifespan.startup.complete"})

    async def run() -> None:
        async def receive() -> Message:
            return {"type": "lifespan.startup"}

        async def send(_message: Message) -> None:
            return None

        await McpAuthGate(inner, state=_state())(
            {"type": "lifespan", "asgi": {"version": "3.0"}}, receive, send
        )

    asyncio.run(run())
    assert seen == ["lifespan"]


def test_require_principal_scope_is_403_without_the_scope() -> None:
    with pytest.raises(AppError) as caught:
        require_principal_scope(Principal("reader", frozenset()), ApiScope.RESEARCH)
    assert caught.value.status_code == 403


def test_enforce_rate_limit_is_429_after_capacity() -> None:
    limiter = TokenBucketLimiter(
        RateLimitSettings({RouteClass.SEARCH: Limit(capacity=1, per_seconds=60)})
    )
    principal = Principal("reader", frozenset((ApiScope.READ,)))
    enforce_rate_limit(limiter, principal, RouteClass.SEARCH)

    with pytest.raises(AppError) as caught:
        enforce_rate_limit(limiter, principal, RouteClass.SEARCH)
    assert caught.value.status_code == 429
    assert "Retry-After" in caught.value.headers
