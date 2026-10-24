from __future__ import annotations

import ast
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import yaml

SCRIPT_PATH = Path("scripts/demo_smoke.py")
SPEC = importlib.util.spec_from_file_location("demo_smoke", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
demo_smoke = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = demo_smoke
SPEC.loader.exec_module(demo_smoke)

_KEY = "rsk_" + "a" * 43
_RUN_ID = "run-001"
_PAPER_ID = "W100"
_TOOLS = sorted(demo_smoke.EXPECTED_MCP_TOOLS)
_RECORD_PATH = f"/v1/research/{_RUN_ID}/record"
_TEXT_PATH = f"/v1/research/{_RUN_ID}/model-calls/1"


class FakeTransport:
    def __init__(self, replies: dict[tuple[str, str], demo_smoke.Reply]) -> None:
        self.replies = replies
        self.requests: list[tuple[str, str, bytes | None, dict[str, str]]] = []

    def request(
        self,
        method: str,
        path: str,
        body: bytes | None,
        headers: dict[str, str],
    ) -> demo_smoke.Reply:
        self.requests.append((method, path, body, headers))
        return self.replies[(method, path)]


def _reply(
    payload: Any, *, status: int = 200, content_type: str = "application/json"
) -> demo_smoke.Reply:
    return demo_smoke.Reply(status, content_type, json.dumps(payload).encode("utf-8"))


def _healthy_replies() -> dict[tuple[str, str], demo_smoke.Reply]:
    mcp_payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {"tools": [{"name": name} for name in _TOOLS]},
    }
    event_body = f"event: message\ndata: {json.dumps(mcp_payload)}\n\n".encode()
    return {
        ("GET", "/ready"): _reply({"status": "ready"}),
        ("GET", "/v1/serving"): _reply(
            {"snapshot_id": "snapshot-001", "retrieval_profile_id": "profile-001"}
        ),
        ("POST", "/v1/search"): _reply(
            {"result_status": "ranked_candidates", "hits": [{"paper_id": _PAPER_ID}]}
        ),
        ("POST", "/v1/evidence/search"): _reply(
            {"result_status": "ranked_candidates", "hits": [{"text": "evidence"}]}
        ),
        ("GET", f"/v1/research/{_RUN_ID}"): _reply(
            {
                "status": "completed",
                "claims": [
                    {
                        "quote": "a quote",
                        "evidence": [{"paper_id": _PAPER_ID}],
                    }
                ],
                "papers": [{"paper_id": _PAPER_ID}],
            }
        ),
        ("POST", "/mcp/"): demo_smoke.Reply(200, "text/event-stream", event_body),
        ("GET", "/"): demo_smoke.Reply(
            200, "text/html; charset=utf-8", b"<html></html>"
        ),
        ("GET", "/ui/app.js"): demo_smoke.Reply(200, "text/javascript", b""),
        ("GET", "/v1/me"): _reply(
            {"principal": "demo", "research_runs": "model_unreachable"}
        ),
        ("GET", "/v1/research?limit=50"): _reply({"runs": [{"run_id": _RUN_ID}]}),
        ("GET", _RECORD_PATH): _reply(
            {
                "tool_calls": [{"tool_name": "search_papers"}],
                "model_calls": [{"ordinal": 1, "text_recorded": True}],
                "drafted_claims": [{"verdict": "kept"}],
                "diagnosis": {"stage": "none"},
            }
        ),
        ("GET", _TEXT_PATH): _reply(
            {"state": "available", "messages": [{"role": "user", "content": "text"}]}
        ),
    }


def _manifest() -> dict[str, Any]:
    return {
        "snapshot_id": "snapshot-001",
        "retrieval_profile_id": "profile-001",
        "runs": [{"run_id": _RUN_ID, "mode": "quick"}],
    }


def test_all_checks_pass_on_a_healthy_stack() -> None:
    results = demo_smoke.run_checks(
        FakeTransport(_healthy_replies()), _KEY, _manifest()
    )

    assert len(results) == 11
    assert all(result.passed for result in results)


def test_mcp_json_reply_is_accepted() -> None:
    replies = _healthy_replies()
    replies[("POST", "/mcp/")] = _reply(
        {"result": {"tools": [{"name": name} for name in _TOOLS]}}
    )

    results = demo_smoke.run_checks(FakeTransport(replies), _KEY, _manifest())

    mcp_result = next(result for result in results if result.name == "mcp_tools")
    assert mcp_result.passed


def test_missing_tool_fails_only_mcp_check() -> None:
    replies = _healthy_replies()
    missing_one = _TOOLS[:-1]
    mcp_payload = {"result": {"tools": [{"name": name} for name in missing_one]}}
    replies[("POST", "/mcp/")] = _reply(mcp_payload)

    results = demo_smoke.run_checks(FakeTransport(replies), _KEY, _manifest())

    assert [result.name for result in results if not result.passed] == ["mcp_tools"]


def test_run_claim_without_quote_fails_runs() -> None:
    replies = _healthy_replies()
    replies[("GET", f"/v1/research/{_RUN_ID}")] = _reply(
        {
            "status": "completed",
            "claims": [{"quote": None, "evidence": [{"paper_id": _PAPER_ID}]}],
            "papers": [{"paper_id": _PAPER_ID}],
        }
    )

    results = demo_smoke.run_checks(FakeTransport(replies), _KEY, _manifest())

    assert [result.name for result in results if not result.passed] == ["runs"]


def test_every_request_sends_the_key() -> None:
    transport = FakeTransport(_healthy_replies())

    demo_smoke.run_checks(transport, _KEY, _manifest())

    assert all(
        headers.get("Authorization") == f"Bearer {_KEY}"
        for _, path, _, headers in transport.requests
        if path not in {"/ready", "/", "/ui/app.js"}
    )
    assert (
        next(headers for _, path, _, headers in transport.requests if path == "/ready")
        == {}
    )
    assert all(
        headers == {}
        for _, path, _, headers in transport.requests
        if path in {"/", "/ui/app.js"}
    )


def test_output_never_contains_text(
    tmp_path: Path, monkeypatch: Any, capsys: Any
) -> None:
    marker = "zq7731"
    replies = _healthy_replies()
    replies[("POST", "/v1/search")] = _reply(
        {"result_status": "ranked_candidates", "hits": [{"question": marker}]}
    )
    replies[("POST", "/v1/evidence/search")] = _reply(
        {"hits": [{"text": marker, "question": marker}]}
    )
    replies[("GET", f"/v1/research/{_RUN_ID}")] = _reply(
        {
            "status": "completed",
            "answer": marker,
            "claims": [{"quote": marker, "evidence": [{"paper_id": _PAPER_ID}]}],
            "papers": [{"paper_id": _PAPER_ID}],
        }
    )
    key_path = tmp_path / "api-key"
    manifest_path = tmp_path / "manifest.json"
    key_path.write_text(_KEY, encoding="utf-8")
    manifest_path.write_text(json.dumps(_manifest()), encoding="utf-8")
    monkeypatch.setattr(
        demo_smoke, "UrllibTransport", lambda *_: FakeTransport(replies)
    )

    status = demo_smoke.main(
        ["--key-file", str(key_path), "--manifest", str(manifest_path)]
    )

    assert status == 0
    assert marker not in capsys.readouterr().out


def test_script_uses_only_the_standard_library() -> None:
    tree = ast.parse(SCRIPT_PATH.read_text(encoding="utf-8"))
    modules = {
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    modules.update(
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    )

    assert modules <= sys.stdlib_module_names


def test_workflow_is_not_run_on_pull_requests() -> None:
    workflow = yaml.safe_load(Path(".github/workflows/demo-smoke.yml").read_text())

    assert set(workflow[True]) == {"workflow_dispatch", "workflow_run"}


def test_new_checks_pass_on_a_complete_stack() -> None:
    results = demo_smoke.run_checks(
        FakeTransport(_healthy_replies()), _KEY, _manifest()
    )

    assert [result.name for result in results[-5:]] == [
        "ui",
        "me",
        "run_list",
        "run_records",
        "model_text",
    ]
    assert all(result.passed for result in results[-5:])


def test_model_text_check_fails_without_recorded_text() -> None:
    replies = _healthy_replies()
    replies[("GET", _RECORD_PATH)] = _reply(
        {
            "tool_calls": [{"tool_name": "search_papers"}],
            "model_calls": [{"ordinal": 1, "text_recorded": False}],
            "drafted_claims": [{"verdict": "kept"}],
            "diagnosis": {"stage": "none"},
        }
    )

    results = demo_smoke.run_checks(FakeTransport(replies), _KEY, _manifest())

    assert results[-1].name == "model_text"
    assert not results[-1].passed


def test_run_list_check_fails_when_a_showcase_run_is_missing() -> None:
    replies = _healthy_replies()
    replies[("GET", "/v1/research?limit=50")] = _reply({"runs": []})

    results = demo_smoke.run_checks(FakeTransport(replies), _KEY, _manifest())

    assert results[-3].name == "run_list"
    assert not results[-3].passed


def test_me_check_fails_when_runs_are_available() -> None:
    replies = _healthy_replies()
    replies[("GET", "/v1/me")] = _reply(
        {"principal": "demo", "research_runs": "available"}
    )

    results = demo_smoke.run_checks(FakeTransport(replies), _KEY, _manifest())

    assert results[-4].name == "me"
    assert not results[-4].passed


def test_ui_check_fails_without_the_page() -> None:
    replies = _healthy_replies()
    replies[("GET", "/")] = _reply({}, status=404, content_type="application/json")

    results = demo_smoke.run_checks(FakeTransport(replies), _KEY, _manifest())

    assert results[-5].name == "ui"
    assert not results[-5].passed


def test_details_hold_no_text() -> None:
    marker = "private question quote message"
    replies = _healthy_replies()
    replies[("GET", _RECORD_PATH)] = _reply(
        {
            "tool_calls": [{"arguments": {"question": marker}}],
            "model_calls": [{"ordinal": 1, "text_recorded": True}],
            "drafted_claims": [{"text": marker}],
            "diagnosis": {"stage": "none", "detail": marker},
        }
    )
    replies[("GET", _TEXT_PATH)] = _reply(
        {"state": "available", "messages": [{"content": marker}]}
    )

    results = demo_smoke.run_checks(FakeTransport(replies), _KEY, _manifest())

    assert all(marker not in result.detail for result in results)
