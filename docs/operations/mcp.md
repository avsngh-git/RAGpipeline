# MCP server

The API process serves one MCP server at <http://127.0.0.1:8001/mcp/>. Keep the trailing slash;
`/mcp` redirects with status 307. Start the local stack as described in the
[Phase 3 operations guide](phase-3-generator.md).

The server uses Streamable HTTP. It has no stdio transport because a second process would load
the retrieval models again on the 4 GiB GPU. It targets protocol revision `2026-07-28`; clients
using `2025-11-25` also work. The Python SDK version is `mcp` 2.3.0.

## Tools and resources

All rate limits are per principal and use the defaults in the
[authentication guide](authentication.md).

| Name | What it does | Scope | Rate-limit class |
| --- | --- | --- | --- |
| `search_papers` | Find ranked papers with their strongest supporting passages. | `read` | search |
| `search_evidence` | Find ranked passages and table excerpts. | `read` | search |
| `get_paper` | Read paper metadata from the served snapshot. | `read` | paper read |
| `get_citations` | List papers that cite a paper. | `read` | paper read |
| `get_references` | List papers cited by a paper. | `read` | paper read |
| `find_related_papers` | Find papers connected through shared references and co-citations. | `read` | paper read |
| `start_research_run` | Queue a research run. | `research` | research run creation |
| `get_research_run` | Read a run you started. | `read` | run read |
| `paper://{paper_id}` | Read paper metadata as JSON. | `read` | paper read |
| `research-run://{run_id}` | Read a run as JSON. | `read` | run read |

## Keys

Create API keys with `research-keys` as described in the
[authentication guide](authentication.md). Use these scopes:

| Client | Scopes |
| --- | --- |
| Read-only search and paper access | `read` |
| Search and research runs | `read`, `research` |
| Research runs that may add papers | `read`, `research`, `ingest` |

A deep research run started without `ingest` cannot add papers. The run records the caller's
ingestion permission when it starts. Send the key only in the `Authorization: Bearer` header;
never put it in a URL.

## Passage text

The default `RESEARCH_PLATFORM_MCP_TEXT_POLICY=public_display_only` withholds passage text and
claim quotes. `trusted_private_client` returns them only when
`RESEARCH_PLATFORM_EVIDENCE_ACCESS_PROFILE=trusted_private_local`; startup refuses this policy
in production. This is the owner's private-use decision. A client such as Claude Code sends tool
results to its model provider.

## Hosts and origins

`RESEARCH_PLATFORM_MCP_ALLOWED_HOSTS` defaults to
`127.0.0.1:*,localhost:*,[::1]:*`. `RESEARCH_PLATFORM_MCP_ALLOWED_ORIGINS` defaults to empty,
so requests with an `Origin` header are refused. A request with a host outside the allowed list
gets status 421.

## Claude Code

Add the server with the Claude Code CLI:

```bash
claude mcp add --transport http scientific-research http://127.0.0.1:8001/mcp/ \
  --header "Authorization: Bearer $RESEARCH_MCP_KEY"
```

Or add this to `.mcp.json`:

```json
{
  "mcpServers": {
    "scientific-research": {
      "type": "http",
      "url": "http://127.0.0.1:8001/mcp/",
      "headers": { "Authorization": "Bearer ${RESEARCH_MCP_KEY}" }
    }
  }
}
```

Never commit `.mcp.json` with a real key. The `${RESEARCH_MCP_KEY}` form reads the key from the
environment.

## MCP Inspector CLI

Use Node 22.19 or later. List tools with Inspector 2.8.0:

```bash
npx -y @modelcontextprotocol/inspector@2.8.0 --cli --transport http \
  --server-url http://127.0.0.1:8001/mcp/ \
  --header "Authorization: Bearer $RESEARCH_MCP_KEY" \
  --method tools/list --format json
```

Call `search_papers` with a query:

```bash
npx -y @modelcontextprotocol/inspector@2.8.0 --cli --transport http \
  --server-url http://127.0.0.1:8001/mcp/ \
  --header "Authorization: Bearer $RESEARCH_MCP_KEY" \
  --method tools/call --tool-name search_papers \
  --tool-args-json '{"query": "reranking"}' --format json
```

The [Inspector check script](../../scripts/mcp_inspector_check.sh) saves the tool and resource
lists, a paper search and read, and a research run start and read under `local-reference/`.

## A research run from a client

Call `start_research_run` with a question. It returns a queued run and `poll_after_seconds`. Call
`get_research_run` again after that interval until the status is `completed` or `failed`. Runs
take minutes on the laptop.

## Troubleshooting

| Result | Cause |
| --- | --- |
| HTTP 401 | The bearer key is missing, invalid or revoked. |
| HTTP 403 | The key lacks the required scope, or the request has a disallowed `Origin` header. |
| HTTP 421 | The request host is not in `RESEARCH_PLATFORM_MCP_ALLOWED_HOSTS`. |
| HTTP 413 | The request body exceeds 64 KiB. |
| `rate_limited` | The principal exceeded the rate limit for this tool. |
| `too_many_active_runs` | The principal already has the maximum number of active runs. |
| `permission_denied` | The evidence access profile does not allow the requested text policy. |
| `incompatible_snapshot` | The requested snapshot is not the one served by this API. |
