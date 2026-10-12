"""Mount the MCP Streamable HTTP server in FastAPI."""

from __future__ import annotations

from fastapi import FastAPI
from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

from research_platform.config import Settings

from .auth_gate import McpAuthGate
from .server import build_mcp_server


def mount_mcp(app: FastAPI, settings: Settings) -> MCPServer:
    """Mount the MCP Streamable HTTP endpoint at /mcp behind API-key authentication."""
    server = build_mcp_server(app.state)
    sub_app = server.streamable_http_app(
        streamable_http_path="/",
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(
            allowed_hosts=list(settings.mcp_allowed_hosts),
            allowed_origins=list(settings.mcp_allowed_origins),
        ),
    )
    app.mount("/mcp", McpAuthGate(sub_app, state=app.state))
    return server
