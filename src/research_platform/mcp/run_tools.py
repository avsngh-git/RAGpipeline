"""Research-run tool registrations for the MCP server."""

from __future__ import annotations

from typing import Any

from mcp.server import MCPServer


def register_run_tools(server: MCPServer, state: Any) -> None:
    """Register the research-run tools and research-run:// (card P5-12)."""
