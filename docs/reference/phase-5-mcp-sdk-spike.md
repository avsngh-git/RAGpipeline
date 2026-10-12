# Phase 5 MCP SDK spike

**Date:** 2026-10-12. **By:** the planning session, in a throwaway virtual environment over
the `sci_research_agent` Conda environment (Python 3.12). Nothing here was committed as code.
It records the SDK facts the Phase 5 cards rely on.

## Versions

- `mcp` 2.3.0 (PyPI and conda-forge, released 2026-10-02). It pulls in `mcp-types` 2.3.0,
  `sse-starlette`, `pyjwt` and `httpx2`. `httpx2` 2.13.1 is already installed in the local Conda
  environment.
- Specification revision 2026-07-28 ([changelog](https://modelcontextprotocol.io/specification/2026-07-28/changelog)).
  A client in `auto` mode negotiated `2026-07-28`; a client in `legacy` mode negotiated
  `2025-11-25` against the same server.
- The local Conda environment has FastAPI 0.138.0 and Starlette 1.3.1, behind the lock's
  0.141.1 and 1.6.0. The prototype worked on the local versions; CI uses the lock.

## Verified API

| Need | Verified form |
| --- | --- |
| Server class | `from mcp.server import MCPServer`; `MCPServer(name, instructions=..., version=...)`. `FastMCP` is the v1 name |
| Tool | `@server.tool(name=..., description=..., annotations=ToolAnnotations(read_only_hint=True), structured_output=True)` on an `async def`. Without `description=`, the description is empty |
| Annotations | `from mcp.types import ToolAnnotations`; fields are snake_case (`read_only_hint`) |
| Argument schema | `Annotated[str, Field(pattern=..., description=...)]` parameters become the input schema |
| Structured output | a Pydantic model return type becomes `output_schema`; results carry `structured_content` |
| Tool error | `from mcp.server.mcpserver.exceptions import ToolError`; the client sees `is_error=True` and text `Error executing tool <name>: <message>` |
| Invalid arguments | a tool error (`is_error=True`) naming the validation failure, not a JSON-RPC error |
| Unexpected exception | a tool error with text `Error executing tool <name>`; the exception text is not sent |
| Resource template | `@server.resource("paper://{paper_id}", mime_type="application/json")` returning a JSON string |
| Resource error | `ResourceError` from the same module; the client raises `MCPError` with the message |
| HTTP app | `server.streamable_http_app(streamable_http_path="/", stateless_http=True, json_response=True, transport_security=TransportSecuritySettings(allowed_hosts=[...], allowed_origins=[...]))` |
| Host check | `from mcp.server.transport_security import TransportSecuritySettings`; a request with another `Host` gets 421 before any tool code runs |
| Lifespan | the host app must run `async with server.session_manager.run():`; mounting skips the sub-app's own lifespan. `session_manager` exists only after `streamable_http_app()` has been called |
| Mount | `app.mount("/mcp", wrapped_app)`; `POST /mcp` answers 307 to `/mcp/`, which the SDK client follows |
| Model attributes | snake_case: `tool.input_schema`, `tool.output_schema`, `result.is_error`, `result.structured_content`, `templates.resource_templates`, `template.uri_template` |
| In-memory client | `from mcp import Client`; `async with Client(server) as client:` with no transport |
| HTTP client in tests | `httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="http://127.0.0.1:8001", headers=...)` and `Client(streamable_http_client("http://127.0.0.1:8001/mcp/", http_client=http), mode="auto")`, from `mcp.client.streamable_http`, inside `async with app.router.lifespan_context(app):` |

## Authentication

- An ASGI wrapper around the mounted app that sets a `contextvars.ContextVar` before calling the
  SDK app made the principal visible inside tool code, for both `auto` and `legacy` clients, over
  uvicorn and over the in-process ASGI transport. A missing key got the wrapper's 401 JSON body.
- The SDK alternative, `MCPServer(token_verifier=..., auth=AuthSettings(...))`, requires
  `issuer_url` and `resource_server_url`, warns that `validate_token_resource` is unset, and
  answers 401 with a `resource_metadata` URL for OAuth discovery. With the app mounted at `/mcp`,
  that metadata route was not at the root, so it returned 404. It was set aside (ADR-0030).

## Not checked

- Claude Code, Claude Desktop and MCP Inspector against the real API: that is gate item 4
  (card P5-16).
- Behaviour with the lock's FastAPI and Starlette versions: CI checks it once P5-03 adds the
  dependency.
