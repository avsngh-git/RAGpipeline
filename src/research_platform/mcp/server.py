"""MCP server construction for the Scientific Research Platform."""

from __future__ import annotations

from typing import Any, Final

from mcp.server import MCPServer

from .paper_tools import register_paper_tools
from .run_tools import register_run_tools
from .search_tools import register_search_tools

SERVER_NAME: Final = "scientific-research"
SERVER_VERSION: Final = "0.1.0"
SERVER_INSTRUCTIONS: Final = (
    "Searches a private, versioned corpus of scholarly papers on retrieval, reranking "
    "and retrieval-augmented generation. Use search_papers to find papers and "
    "search_evidence for passages; scores rank results and are not probabilities. "
    "Paper and citation tools take OpenAlex work IDs such as W2741809807. A research "
    "run takes several minutes: start it with start_research_run, then call "
    "get_research_run after poll_after_seconds until its status is completed or "
    "failed. The server may withhold passage text by policy."
)


def build_mcp_server(state: Any) -> MCPServer:
    """Create the server and register every tool and resource."""
    server = MCPServer(
        SERVER_NAME,
        title="Scientific Research Platform",
        instructions=SERVER_INSTRUCTIONS,
        version=SERVER_VERSION,
    )
    register_search_tools(server, state)
    register_paper_tools(server, state)
    register_run_tools(server, state)
    return server
