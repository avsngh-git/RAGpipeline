"""Access control and telemetry for MCP calls."""

from __future__ import annotations

import asyncio

import pytest
from mcp.server.mcpserver.exceptions import ResourceError, ToolError

from research_platform.api.errors import AppError
from research_platform.auth.keys import Principal, Scope
from research_platform.mcp.principal import principal_context
from research_platform.mcp.runtime import McpCall, run_call
from research_platform.mcp.testing import fake_state
from research_platform.observability.metrics import REGISTRY
from research_platform.observability.tracing import (
    ATTR_MCP_PRINCIPAL,
    ATTR_MCP_STATUS,
    ATTR_MCP_TOOL,
    capture_spans,
)
from research_platform.services.capabilities import ResearchCapabilities


def test_run_call_passes_the_principal_and_capabilities() -> None:
    state = fake_state()

    async def operation(call: McpCall) -> tuple[str, bool]:
        return call.principal.name, isinstance(call.capabilities, ResearchCapabilities)

    with principal_context(Principal("tester", frozenset({Scope.READ}))):
        result = asyncio.run(run_call(state, "search_papers", operation))

    assert result == ("tester", True)


def test_missing_scope_is_a_tool_error() -> None:
    async def operation(_call: McpCall) -> None:
        return None

    with principal_context(Principal("tester", frozenset({Scope.READ}))):
        with pytest.raises(ToolError, match="^insufficient_scope:"):
            asyncio.run(run_call(fake_state(), "start_research_run", operation))


def test_rate_limit_is_a_tool_error() -> None:
    state = fake_state(rate_limits={"RESEARCH_PLATFORM_RATE_LIMIT_SEARCH": "1/60"})

    async def operation(_call: McpCall) -> None:
        return None

    with principal_context(Principal("tester", frozenset({Scope.READ}))):
        asyncio.run(run_call(state, "search_papers", operation))
        with pytest.raises(ToolError, match="^rate_limited:"):
            asyncio.run(run_call(state, "search_papers", operation))


def test_app_error_keeps_its_code() -> None:
    async def operation(_call: McpCall) -> None:
        raise AppError("run_not_found", "x", 404)

    with principal_context(Principal("tester", frozenset({Scope.READ}))):
        with pytest.raises(ToolError, match="^run_not_found: x$"):
            asyncio.run(run_call(fake_state(), "get_research_run", operation))


def test_unexpected_error_text_is_hidden() -> None:
    async def operation(_call: McpCall) -> None:
        raise RuntimeError("zq7731")

    with principal_context(Principal("tester", frozenset({Scope.READ}))):
        with pytest.raises(ToolError, match="^internal_error:") as raised:
            asyncio.run(run_call(fake_state(), "get_research_run", operation))

    assert "zq7731" not in str(raised.value)


def test_resource_calls_raise_resource_error() -> None:
    async def operation(_call: McpCall) -> None:
        raise AppError("run_not_found", "x", 404)

    with principal_context(Principal("tester", frozenset({Scope.READ}))):
        with pytest.raises(ResourceError, match="^run_not_found: x$"):
            asyncio.run(
                run_call(
                    fake_state(),
                    "research_run_resource",
                    operation,
                    resource=True,
                )
            )


def test_no_principal_is_401() -> None:
    async def operation(_call: McpCall) -> None:
        return None

    with pytest.raises(ToolError, match="^authentication_required:"):
        asyncio.run(run_call(fake_state(), "search_papers", operation))


def test_span_and_metrics_are_recorded() -> None:
    async def operation(_call: McpCall) -> None:
        return None

    labels = {"tool": "search_papers", "status": "ok"}
    before = REGISTRY.get_sample_value("research_mcp_calls_total", labels) or 0
    with capture_spans() as exporter:
        with principal_context(Principal("tester", frozenset({Scope.READ}))):
            asyncio.run(run_call(fake_state(), "search_papers", operation))

    [span] = exporter.get_finished_spans()
    assert span.name == "mcp.search_papers"
    assert span.attributes[ATTR_MCP_TOOL] == "search_papers"
    assert span.attributes[ATTR_MCP_STATUS] == "ok"
    assert span.attributes[ATTR_MCP_PRINCIPAL] == "tester"
    assert (REGISTRY.get_sample_value("research_mcp_calls_total", labels) or 0) == (
        before + 1
    )
