"""HTTP protocol coverage for the MCP mount."""

from __future__ import annotations

import asyncio

import httpx2
from fastapi import FastAPI
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from research_platform.api import create_app
from research_platform.api.auth import AuthSettings
from research_platform.auth.keys import InMemoryApiKeyStore
from research_platform.mcp.runtime import CALL_ACCESS
from research_platform.mcp.testing import fake_state, make_settings
from research_platform.services.readiness import ReadinessReport


class StubReadinessChecker:
    async def check(self) -> ReadinessReport:
        return ReadinessReport(dependencies={"postgres": True, "qdrant": True})


_RESOURCE_CALLS = frozenset({"paper_resource", "research_run_resource"})
_TOOL_NAMES = frozenset(CALL_ACCESS) - _RESOURCE_CALLS


def _assert_listed_tools(names: set[str]) -> None:
    assert names <= _TOOL_NAMES
    assert {"start_research_run", "get_research_run"} <= names


def _app(
    *,
    settings=None,
    auth_settings: AuthSettings | None = None,
    api_key_store: InMemoryApiKeyStore | None = None,
) -> FastAPI:
    state = fake_state(settings=settings)
    return create_app(
        settings=state.settings,
        dependency_checker=StubReadinessChecker(),
        api_services=state.phase2_services,
        auth_settings=auth_settings,
        api_key_store=api_key_store,
    )


def test_tools_are_listed_over_http() -> None:
    """The app has no research services at creation, as in production."""
    app = _app()

    async def run() -> None:
        async with app.router.lifespan_context(app):
            transport = httpx2.ASGITransport(app=app)
            async with httpx2.AsyncClient(
                transport=transport, base_url="http://127.0.0.1:8001"
            ) as http:
                async with Client(
                    streamable_http_client(
                        "http://127.0.0.1:8001/mcp/", http_client=http
                    )
                ) as client:
                    _assert_listed_tools(
                        {tool.name for tool in (await client.list_tools()).tools}
                    )

    asyncio.run(run())


def test_legacy_clients_are_served() -> None:
    app = _app()

    async def run() -> None:
        async with app.router.lifespan_context(app):
            transport = httpx2.ASGITransport(app=app)
            async with httpx2.AsyncClient(
                transport=transport, base_url="http://127.0.0.1:8001"
            ) as http:
                async with Client(
                    streamable_http_client(
                        "http://127.0.0.1:8001/mcp/", http_client=http
                    ),
                    mode="legacy",
                ) as client:
                    _assert_listed_tools(
                        {tool.name for tool in (await client.list_tools()).tools}
                    )

    asyncio.run(run())


def test_missing_key_is_401() -> None:
    app = _app(
        auth_settings=AuthSettings(mode="api_key", bind_host="127.0.0.1"),
        api_key_store=InMemoryApiKeyStore(),
    )

    async def run() -> httpx2.Response:
        async with app.router.lifespan_context(app):
            transport = httpx2.ASGITransport(app=app)
            async with httpx2.AsyncClient(
                transport=transport, base_url="http://127.0.0.1:8001"
            ) as http:
                return await http.post(
                    "/mcp/",
                    headers={
                        "Accept": "application/json, text/event-stream",
                        "Content-Type": "application/json",
                    },
                    content='{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}',
                )

    response = asyncio.run(run())
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_required"


def test_wrong_host_is_421() -> None:
    app = _app()

    async def run() -> httpx2.Response:
        async with app.router.lifespan_context(app):
            transport = httpx2.ASGITransport(app=app)
            async with httpx2.AsyncClient(
                transport=transport, base_url="http://evil.example"
            ) as http:
                return await http.post(
                    "/mcp/",
                    headers={
                        "Accept": "application/json, text/event-stream",
                        "Content-Type": "application/json",
                    },
                    content='{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}',
                )

    assert asyncio.run(run()).status_code == 421


def test_foreign_origin_is_403() -> None:
    app = _app()

    async def run() -> httpx2.Response:
        async with app.router.lifespan_context(app):
            transport = httpx2.ASGITransport(app=app)
            async with httpx2.AsyncClient(
                transport=transport, base_url="http://127.0.0.1:8001"
            ) as http:
                return await http.post(
                    "/mcp/",
                    headers={
                        "Accept": "application/json, text/event-stream",
                        "Content-Type": "application/json",
                        "Origin": "http://evil.example",
                    },
                    content='{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}',
                )

    assert asyncio.run(run()).status_code == 403


def test_body_limit_applies_to_mcp() -> None:
    app = _app()

    async def run() -> httpx2.Response:
        async with app.router.lifespan_context(app):
            transport = httpx2.ASGITransport(app=app)
            async with httpx2.AsyncClient(
                transport=transport, base_url="http://127.0.0.1:8001"
            ) as http:
                return await http.post(
                    "/mcp/",
                    headers={
                        "Accept": "application/json, text/event-stream",
                        "Content-Type": "application/json",
                    },
                    content=" " * 70_000,
                )

    assert asyncio.run(run()).status_code == 413


def test_mcp_settings_parse_lists(monkeypatch) -> None:
    monkeypatch.setenv("RESEARCH_PLATFORM_MCP_ALLOWED_HOSTS", "a:*, b:1")
    monkeypatch.setenv("RESEARCH_PLATFORM_MCP_ALLOWED_ORIGINS", "http://a, http://b")
    settings = make_settings()
    assert settings.mcp_allowed_hosts == ("a:*", "b:1")
    assert settings.mcp_allowed_origins == ("http://a", "http://b")

    monkeypatch.setenv("RESEARCH_PLATFORM_MCP_ALLOWED_HOSTS", " , ")
    try:
        make_settings()
    except ValueError as error:
        assert str(error) == "mcp_allowed_hosts must not be empty"
    else:
        raise AssertionError("empty MCP allowed hosts were accepted")


def test_run_tools_report_unavailable_until_services_exist() -> None:
    app = _app()

    async def run() -> None:
        async with app.router.lifespan_context(app):
            transport = httpx2.ASGITransport(app=app)
            async with httpx2.AsyncClient(
                transport=transport, base_url="http://127.0.0.1:8001"
            ) as http:
                async with Client(
                    streamable_http_client(
                        "http://127.0.0.1:8001/mcp/", http_client=http
                    )
                ) as client:
                    result = await client.call_tool(
                        "get_research_run",
                        {"run_id": "00000000-0000-0000-0000-000000000009"},
                    )
                    assert result.is_error
                    assert "service_unavailable" in result.content[0].text

    asyncio.run(run())
