#!/usr/bin/env python3
"""Check the local small-mode demo stack without exposing response content."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Mapping, Protocol, Sequence

EXPECTED_MCP_TOOLS: Final = frozenset(
    {
        "search_papers",
        "search_evidence",
        "get_paper",
        "get_citations",
        "get_references",
        "find_related_papers",
        "start_research_run",
        "get_research_run",
    }
)
SMOKE_QUERY: Final = "reranking for retrieval-augmented generation"
README_SECTION: Final = 'the README "Try it" section'


@dataclass(frozen=True)
class Reply:
    status: int
    content_type: str
    body: bytes


class Transport(Protocol):
    def request(
        self, method: str, path: str, body: bytes | None, headers: Mapping[str, str]
    ) -> Reply: ...


class UrllibTransport:
    """Send HTTP requests to the configured API base URL."""

    def __init__(self, base_url: str, timeout: float) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    def request(
        self, method: str, path: str, body: bytes | None, headers: Mapping[str, str]
    ) -> Reply:
        request = urllib.request.Request(
            f"{self._base_url}{path}",
            data=body,
            headers=dict(headers),
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                return Reply(
                    status=response.status,
                    content_type=response.headers.get("Content-Type", ""),
                    body=response.read(),
                )
        except urllib.error.HTTPError as error:
            return Reply(
                status=error.code,
                content_type=error.headers.get("Content-Type", ""),
                body=error.read(),
            )


@dataclass(frozen=True)
class CheckResult:
    name: str
    passed: bool
    detail: str


def _json_body(reply: Reply) -> Any:
    return json.loads(reply.body.decode("utf-8"))


def _request(
    transport: Transport,
    method: str,
    path: str,
    *,
    key: str | None = None,
    payload: Mapping[str, Any] | None = None,
    mcp: bool = False,
) -> Reply:
    headers: dict[str, str] = {}
    if path != "/ready" and key is not None:
        headers["Authorization"] = f"Bearer {key}"
    body: bytes | None = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(payload).encode("utf-8")
    if mcp:
        headers["Accept"] = "application/json, text/event-stream"
        headers["Content-Type"] = "application/json"
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).encode(
            "utf-8"
        )
    try:
        return transport.request(method, path, body, headers)
    except Exception:
        return Reply(status=0, content_type="", body=b"")


def _search_payload(manifest: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "query": SMOKE_QUERY,
        "snapshot_id": manifest.get("snapshot_id"),
        "retrieval_profile_id": manifest.get("retrieval_profile_id"),
        "mode": "reranked",
        "limit": 5,
    }


def _mcp_json(reply: Reply) -> Any:
    content_type = reply.content_type.lower()
    if "text/event-stream" not in content_type:
        return _json_body(reply)
    for line in reply.body.decode("utf-8").splitlines():
        if line.startswith("data:"):
            return json.loads(line[5:].strip())
    raise ValueError("missing event data")


def _tool_names(payload: Any) -> set[str]:
    if not isinstance(payload, dict):
        return set()
    result = payload.get("result")
    if not isinstance(result, dict):
        return set()
    tools = result.get("tools")
    if not isinstance(tools, list):
        return set()
    return {
        tool["name"]
        for tool in tools
        if isinstance(tool, dict) and isinstance(tool.get("name"), str)
    }


def _run_integrity(run: Any, papers_with_claim: list[bool]) -> bool:
    if not isinstance(run, dict) or run.get("status") not in {"completed", "failed"}:
        return False
    if run.get("status") == "failed":
        return True
    claims = run.get("claims")
    papers = run.get("papers")
    if not isinstance(claims, list) or not isinstance(papers, list):
        return False
    paper_ids = {paper.get("paper_id") for paper in papers if isinstance(paper, dict)}
    valid = True
    for claim in claims:
        papers_with_claim.append(True)
        if not isinstance(claim, dict) or claim.get("quote") is None:
            valid = False
            continue
        evidence = claim.get("evidence")
        if not isinstance(evidence, list):
            valid = False
            continue
        if any(
            not isinstance(item, dict) or item.get("paper_id") not in paper_ids
            for item in evidence
        ):
            valid = False
    return valid


def run_checks(
    transport: Transport, key: str, manifest: Mapping[str, Any]
) -> list[CheckResult]:
    results: list[CheckResult] = []

    ready = _request(transport, "GET", "/ready")
    ready_data: Any = None
    try:
        ready_data = _json_body(ready)
    except (UnicodeDecodeError, json.JSONDecodeError):
        pass
    ready_ok = (
        ready.status == 200
        and isinstance(ready_data, dict)
        and ready_data.get("status") == "ready"
    )
    results.append(
        CheckResult("ready", ready_ok, f"HTTP {ready.status}; readiness status checked")
    )

    serving = _request(transport, "GET", "/v1/serving", key=key)
    serving_ok = False
    try:
        serving_data = _json_body(serving)
        serving_ok = (
            serving.status == 200
            and isinstance(serving_data, dict)
            and serving_data.get("snapshot_id") == manifest.get("snapshot_id")
            and serving_data.get("retrieval_profile_id")
            == manifest.get("retrieval_profile_id")
        )
    except (UnicodeDecodeError, json.JSONDecodeError):
        pass
    results.append(
        CheckResult(
            "serving",
            serving_ok,
            f"HTTP {serving.status}; identity {'matched' if serving_ok else 'mismatched'}",
        )
    )

    search_body = _search_payload(manifest)
    paper_search = _request(
        transport, "POST", "/v1/search", key=key, payload=search_body
    )
    paper_ok = False
    paper_hits = 0
    try:
        paper_data = _json_body(paper_search)
        hits = paper_data.get("hits") if isinstance(paper_data, dict) else None
        paper_hits = len(hits) if isinstance(hits, list) else 0
        paper_ok = (
            paper_search.status == 200
            and isinstance(paper_data, dict)
            and paper_data.get("result_status") == "ranked_candidates"
            and paper_hits > 0
        )
    except (UnicodeDecodeError, json.JSONDecodeError):
        pass
    results.append(
        CheckResult(
            "paper_search",
            paper_ok,
            f"HTTP {paper_search.status}; hits {paper_hits}",
        )
    )

    evidence_search = _request(
        transport, "POST", "/v1/evidence/search", key=key, payload=search_body
    )
    evidence_ok = False
    evidence_hits = 0
    try:
        evidence_data = _json_body(evidence_search)
        hits = evidence_data.get("hits") if isinstance(evidence_data, dict) else None
        evidence_hits = len(hits) if isinstance(hits, list) else 0
        first_text = (
            hits[0].get("text")
            if evidence_hits > 0 and isinstance(hits[0], dict)
            else None
        )
        evidence_ok = (
            evidence_search.status == 200
            and isinstance(evidence_data, dict)
            and evidence_hits > 0
            and isinstance(first_text, str)
            and bool(first_text.strip())
        )
    except (UnicodeDecodeError, json.JSONDecodeError):
        pass
    results.append(
        CheckResult(
            "evidence_search",
            evidence_ok,
            f"HTTP {evidence_search.status}; hits {evidence_hits}",
        )
    )

    runs = manifest.get("runs")
    run_count = len(runs) if isinstance(runs, list) else 0
    run_failures = 0
    claims_found: list[bool] = []
    if not isinstance(runs, list):
        run_failures += 1
    else:
        for item in runs:
            run_id = item.get("run_id") if isinstance(item, dict) else None
            if not isinstance(run_id, str) or not run_id:
                run_failures += 1
                continue
            run_path = "/v1/research/" + urllib.parse.quote(run_id, safe="")
            reply = _request(transport, "GET", run_path, key=key)
            try:
                run_data = _json_body(reply)
                if reply.status != 200 or not _run_integrity(run_data, claims_found):
                    run_failures += 1
            except (UnicodeDecodeError, json.JSONDecodeError):
                run_failures += 1
    runs_ok = run_failures == 0 and any(claims_found)
    results.append(
        CheckResult(
            "runs",
            runs_ok,
            f"runs {run_count}; failed {run_failures}; claims {len(claims_found)}",
        )
    )

    mcp_reply = _request(transport, "POST", "/mcp/", key=key, mcp=True)
    mcp_names: set[str] = set()
    try:
        mcp_names = _tool_names(_mcp_json(mcp_reply))
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        pass
    missing_tools = len(EXPECTED_MCP_TOOLS - mcp_names)
    mcp_ok = mcp_reply.status == 200 and missing_tools == 0
    results.append(
        CheckResult(
            "mcp_tools",
            mcp_ok,
            f"HTTP {mcp_reply.status}; tools {len(mcp_names)}; missing {missing_tools}",
        )
    )
    return results


def _arguments(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check a running small-mode demo.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--key-file", default="demo-data/api-key")
    parser.add_argument(
        "--manifest", default="demo-data/research-demo-v1/manifest.json"
    )
    parser.add_argument("--timeout", type=float, default=180)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _arguments(argv)
    key_path = Path(args.key_file)
    manifest_path = Path(args.manifest)
    try:
        key = key_path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        print(f"Unable to read {key_path}; follow {README_SECTION}.")
        return 2
    try:
        manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        print(f"Unable to read {manifest_path}; follow {README_SECTION}.")
        return 2
    if not isinstance(manifest_data, dict):
        print(f"Unable to read {manifest_path}; follow {README_SECTION}.")
        return 2

    checks = run_checks(
        UrllibTransport(args.base_url, args.timeout), key, manifest_data
    )
    for check in checks:
        state = "PASS" if check.passed else "FAIL"
        print(f"{state} {check.name}: {check.detail}")
    return 0 if all(check.passed for check in checks) else 1


if __name__ == "__main__":
    sys.exit(main())
