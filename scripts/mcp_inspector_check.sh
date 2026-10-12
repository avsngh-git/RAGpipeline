#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${RESEARCH_MCP_KEY:-}" ]]; then
  printf '%s\n' 'RESEARCH_MCP_KEY is required.' >&2
  exit 2
fi
if [[ -z "${RESEARCH_MCP_QUERY:-}" ]]; then
  printf '%s\n' 'RESEARCH_MCP_QUERY is required.' >&2
  exit 2
fi
if [[ -z "${RESEARCH_MCP_QUESTION:-}" ]]; then
  printf '%s\n' 'RESEARCH_MCP_QUESTION is required.' >&2
  exit 2
fi

RESEARCH_MCP_URL="${RESEARCH_MCP_URL:-http://127.0.0.1:8001/mcp/}"
INSPECTOR_VERSION="${INSPECTOR_VERSION:-2.8.0}"
export RESEARCH_MCP_QUERY RESEARCH_MCP_QUESTION

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUTPUT_DIR="$REPO_ROOT/local-reference/phase5/inspector/$TIMESTAMP"
mkdir -p -- "$OUTPUT_DIR"

inspector_call() {
  local output_file="$1"
  shift
  npx --yes "@modelcontextprotocol/inspector@$INSPECTOR_VERSION" \
    --cli --transport http --server-url "$RESEARCH_MCP_URL" \
    --header "Authorization: Bearer $RESEARCH_MCP_KEY" \
    "$@" --format json > "$output_file"
}

inspector_call "$OUTPUT_DIR/tools-list.json" --method tools/list
inspector_call "$OUTPUT_DIR/resources-templates.json" --method resources/templates/list

SEARCH_ARGS="$(python -c 'import json, os; print(json.dumps({"query": os.environ["RESEARCH_MCP_QUERY"]}))')"
inspector_call "$OUTPUT_DIR/search-papers.json" \
  --method tools/call --tool-name search_papers --tool-args-json "$SEARCH_ARGS"

PAPER_ID="$(python -c '
import json
import sys

with open(sys.argv[1], encoding="utf-8") as source:
    payload = json.load(source)
result = payload.get("result", payload)
structured = result.get("structuredContent", result.get("structured_content", {}))
papers = structured.get("papers", [])
if not papers:
    raise SystemExit("search_papers returned no paper IDs")
print(papers[0]["paper_id"])
' "$OUTPUT_DIR/search-papers.json")"
PAPER_ARGS="$(python -c 'import json, sys; print(json.dumps({"paper_id": sys.argv[1]}))' "$PAPER_ID")"
inspector_call "$OUTPUT_DIR/get-paper.json" \
  --method tools/call --tool-name get_paper --tool-args-json "$PAPER_ARGS"

RUN_ARGS="$(python -c 'import json, os; print(json.dumps({"question": os.environ["RESEARCH_MCP_QUESTION"]}))')"
inspector_call "$OUTPUT_DIR/start-run.json" \
  --method tools/call --tool-name start_research_run --tool-args-json "$RUN_ARGS"

RUN_ID="$(python -c '
import json
import sys

with open(sys.argv[1], encoding="utf-8") as source:
    payload = json.load(source)
result = payload.get("result", payload)
structured = result.get("structuredContent", result.get("structured_content", {}))
print(structured["run"]["run_id"])
' "$OUTPUT_DIR/start-run.json")"
RUN_READ_ARGS="$(python -c 'import json, sys; print(json.dumps({"run_id": sys.argv[1]}))' "$RUN_ID")"
inspector_call "$OUTPUT_DIR/get-run.json" \
  --method tools/call --tool-name get_research_run --tool-args-json "$RUN_READ_ARGS"

printf 'Inspector results saved to %s\n' "$OUTPUT_DIR"
