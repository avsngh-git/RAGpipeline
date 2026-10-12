"""Search tool registrations for the MCP server."""

from __future__ import annotations

from typing import Any

from mcp.server import MCPServer


def register_search_tools(server: MCPServer, state: Any) -> None:
    """Register search_papers and search_evidence (card P5-10)."""
