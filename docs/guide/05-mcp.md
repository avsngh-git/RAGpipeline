# 5. MCP server

The platform exposes one [Model Context Protocol](https://modelcontextprotocol.io) server so that external AI clients, such as Claude Code or MCP Inspector, can use the same research capabilities as the HTTP API. It is a thin adapter: every tool calls `ResearchCapabilities`, the same service the HTTP routes use. CI checks that MCP results match the HTTP routes and the agent's tools on the same fixtures. See [ADR-0030](../adr/0030-phase5-mcp-adapter.md).

| Property | Value |
| --- | --- |
| URL | `http://127.0.0.1:8000/mcp/` in the demo (keep the trailing slash; `/mcp` redirects with 307) |
| Transport | Streamable HTTP, mounted inside the API process. There is no stdio transport, because a second process would load the retrieval models again. |
| Protocol revision | `2026-07-28`; clients on `2025-11-25` also work |
| SDK | Official Python SDK `mcp` 2.3.0 |
| Authentication | The same API keys, scopes and rate limits as HTTP, sent as `Authorization: Bearer <key>` |

## Tools and resources

| Name | What it does | Scope |
| --- | --- | --- |
| `search_papers` | Ranked papers with their strongest supporting passages | `read` |
| `search_evidence` | Ranked passages and table excerpts | `read` |
| `get_paper` | Paper metadata from the served snapshot | `read` |
| `get_citations` | Papers that cite a paper | `read` |
| `get_references` | Papers a paper cites | `read` |
| `find_related_papers` | Papers connected through shared references and co-citations | `read` |
| `start_research_run` | Queue a research run; returns the run and `poll_after_seconds` | `research` |
| `get_research_run` | Read a run you started | `read` |
| `paper://{paper_id}` (resource) | Paper metadata as JSON | `read` |
| `research-run://{run_id}` (resource) | A run as JSON | `read` |

A `deep_research` run started without the `ingest` scope cannot add papers; the run records the caller's ingestion permission when it starts.

## Passage text

What an external client receives may leave the machine, for example to the client's own model provider. Passage text and claim quotes are therefore controlled by a server-wide policy ([ADR-0031](../adr/0031-phase5-external-passage-exposure.md)):

| `RESEARCH_PLATFORM_MCP_TEXT_POLICY` | Behaviour |
| --- | --- |
| `public_display_only` (default) | Text only for passages whose permission evidence allows public display; others are withheld |
| `trusted_private_client` | The same text as private evidence inspection. Requires `RESEARCH_PLATFORM_EVIDENCE_ACCESS_PROFILE=trusted_private_local`; refused in `production` |

## Hosts and origins

`RESEARCH_PLATFORM_MCP_ALLOWED_HOSTS` defaults to `127.0.0.1:*,localhost:*,[::1]:*`; any other `Host` gets `421`. `RESEARCH_PLATFORM_MCP_ALLOWED_ORIGINS` defaults to empty, so browser requests carrying an `Origin` header get `403`.

## Connecting a client

Claude Code:

```bash
export RESEARCH_MCP_KEY=$(cat demo-data/api-key)
claude mcp add --transport http scientific-research http://127.0.0.1:8000/mcp/ \
  --header "Authorization: Bearer $RESEARCH_MCP_KEY"
```

MCP Inspector (Node 22.19 or later):

```bash
npx -y @modelcontextprotocol/inspector@2.8.0 --cli --transport http \
  --server-url http://127.0.0.1:8000/mcp/ \
  --header "Authorization: Bearer $RESEARCH_MCP_KEY" \
  --method tools/call --tool-name search_papers \
  --tool-args-json '{"query": "reranking"}' --format json
```

Never commit an `.mcp.json` containing a real key; use `${RESEARCH_MCP_KEY}` to read it from the environment.

## Troubleshooting

| Result | Cause |
| --- | --- |
| HTTP 401 | Missing, invalid or revoked key |
| HTTP 403 | Missing scope, or a disallowed `Origin` header |
| HTTP 421 | `Host` not in the allowed list |
| HTTP 413 | Body above 64 KiB |
| `rate_limited`, `too_many_active_runs` | Per-principal limits; see [HTTP API: limits](04-http-api.md#limits) |
| `permission_denied` | The server's evidence access profile does not allow the requested text |
| `incompatible_snapshot` | The request named a snapshot this server does not serve |

The full procedure, including an Inspector check script, is in the [MCP operations guide](../operations/mcp.md). That guide uses the host development port 8001.

Next: [Command-line tools](06-cli.md).
