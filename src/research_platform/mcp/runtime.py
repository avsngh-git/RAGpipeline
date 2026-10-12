"""Access, limits, telemetry and errors for every MCP call (ADR-0030)."""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from time import perf_counter
from types import MappingProxyType
from typing import Any, Final, TypeVar
from uuid import uuid4

from mcp.server.mcpserver.exceptions import ResourceError, ToolError

from research_platform.api.auth import require_principal_scope
from research_platform.api.errors import AppError
from research_platform.api.rate_limits import RouteClass, enforce_rate_limit
from research_platform.auth.keys import Principal, Scope
from research_platform.config import Settings
from research_platform.mcp.principal import current_principal
from research_platform.observability.metrics import MCP_CALLS, MCP_LATENCY
from research_platform.observability.request_context import get_request_id
from research_platform.observability.tracing import (
    ATTR_MCP_PRINCIPAL,
    ATTR_MCP_STATUS,
    ATTR_MCP_TOOL,
    get_tracer,
    mark_span_error,
    set_id_attribute,
)
from research_platform.services.capabilities import ResearchCapabilities

T = TypeVar("T")

logger = logging.getLogger("research_platform.mcp")


@dataclass(frozen=True)
class CallAccess:
    scope: Scope
    route_class: RouteClass


CALL_ACCESS: Final[Mapping[str, CallAccess]] = MappingProxyType(
    {
        "search_papers": CallAccess(Scope.READ, RouteClass.SEARCH),
        "search_evidence": CallAccess(Scope.READ, RouteClass.SEARCH),
        "get_paper": CallAccess(Scope.READ, RouteClass.PAPER_READ),
        "get_citations": CallAccess(Scope.READ, RouteClass.PAPER_READ),
        "get_references": CallAccess(Scope.READ, RouteClass.PAPER_READ),
        "find_related_papers": CallAccess(Scope.READ, RouteClass.PAPER_READ),
        "paper_resource": CallAccess(Scope.READ, RouteClass.PAPER_READ),
        "start_research_run": CallAccess(Scope.RESEARCH, RouteClass.RESEARCH_CREATE),
        "get_research_run": CallAccess(Scope.READ, RouteClass.RUN_READ),
        "research_run_resource": CallAccess(Scope.READ, RouteClass.RUN_READ),
    }
)


@dataclass(frozen=True)
class McpCall:
    """What a tool body receives: the caller and the shared capabilities."""

    principal: Principal
    capabilities: ResearchCapabilities
    settings: Settings
    request_id: str


async def run_call(
    state: Any,
    name: str,
    operation: Callable[[McpCall], Awaitable[T]],
    *,
    resource: bool = False,
) -> T:
    access = CALL_ACCESS[name]
    started = perf_counter()
    metric_status = "server_error"
    span_status = "internal_error"
    error_type = ResourceError if resource else ToolError
    with get_tracer().start_as_current_span(
        f"mcp.{name}", set_status_on_exception=False
    ) as span:
        span.set_attribute(ATTR_MCP_TOOL, name)
        try:
            principal = current_principal()
            set_id_attribute(span, ATTR_MCP_PRINCIPAL, principal.name)
            require_principal_scope(principal, access.scope)
            enforce_rate_limit(state.rate_limiter, principal, access.route_class)
            call = McpCall(
                principal=principal,
                capabilities=ResearchCapabilities.from_app_state(state),
                settings=state.settings,
                request_id=get_request_id() or uuid4().hex,
            )
            result = await operation(call)
            metric_status = "ok"
            span_status = "ok"
            return result
        except AppError as error:
            span_status = error.code
            metric_status = (
                "client_error" if error.status_code < 500 else "server_error"
            )
            if error.status_code >= 500:
                mark_span_error(span, error)
            raise error_type(f"{error.code}: {error.message}") from None
        except Exception as error:
            logger.error(
                "mcp_call_failed",
                extra={"tool": name, "error_type": type(error).__qualname__},
            )
            mark_span_error(span, error)
            raise error_type(
                "internal_error: The request could not be completed."
            ) from None
        finally:
            span.set_attribute(ATTR_MCP_STATUS, span_status)
            MCP_CALLS.labels(name, metric_status).inc()
            MCP_LATENCY.labels(name).observe(time.perf_counter() - started)
