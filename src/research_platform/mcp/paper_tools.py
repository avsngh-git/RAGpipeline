"""Paper and citation tool registrations for the MCP server."""

from __future__ import annotations

from typing import Any

from mcp.server import MCPServer


def register_paper_tools(server: MCPServer, state: Any) -> None:
    """Register the paper and citation tools and paper:// (card P5-11)."""
