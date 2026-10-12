"""Parity checks for HTTP, MCP, and LangGraph research tools."""

from __future__ import annotations

import json
from contextvars import ContextVar
from typing import Any
from uuid import UUID

import httpx2
import pytest
from fastapi import FastAPI
from mcp import Client

from research_platform.agents.actions import (
    FindRelatedPapersAction,
    GetCitationsAction,
    GetReferencesAction,
    SearchEvidenceAction,
    SearchPapersAction,
)
from research_platform.api import create_app
from research_platform.auth.keys import LOCAL_PRINCIPAL
from research_platform.mcp.principal import principal_context
from research_platform.mcp.server import build_mcp_server
from research_platform.mcp.testing import (
    SAMPLE_PAPER_A,
    SAMPLE_PAPER_B,
    SAMPLE_PAPER_C,
    SAMPLE_PROFILE_ID,
    SAMPLE_SNAPSHOT_ID,
    fake_state,
)
from research_platform.runs.contracts import ResearchFilters, RunBudgets
from research_platform.services.capabilities import ResearchCapabilities
from research_platform.services.readiness import ReadinessReport
from research_platform.tools.research_tools import (
    ResearchTools,
    ToolContext,
    ToolLedger,
)

_TRANSPORT: ContextVar[str] = ContextVar("phase5_parity_transport", default="")


class StubReadinessChecker:
    async def check(self) -> ReadinessReport:
        return ReadinessReport(dependencies={"postgres": True, "qdrant": True})


def _app(state: Any) -> FastAPI:
    return create_app(
        settings=state.settings,
        dependency_checker=StubReadinessChecker(),
        api_services=state.phase2_services,
        research_services=state.research_services,
    )


def _agent_tools(state: Any) -> ResearchTools:
    services = state.phase2_services
    return ResearchTools(
        search=services.search,
        papers=services.papers,
        citations=services.citations,
        related=services.related,
    )


def _agent_context() -> ToolContext:
    return ToolContext(
        run_id=UUID("00000000-0000-0000-0000-000000000002"),
        snapshot_id=SAMPLE_SNAPSHOT_ID,
        generation=1,
        retrieval_profile_id=SAMPLE_PROFILE_ID,
        filters=ResearchFilters(),
        budgets=RunBudgets(),
    )


async def _agent_observation(state: Any, action: Any) -> Any:
    observation, _ = await _agent_tools(state).execute(
        action, context=_agent_context(), ledger=ToolLedger()
    )
    assert observation.status == "succeeded"
    return observation


async def _mcp_call(state: Any, name: str, arguments: dict[str, Any]) -> Any:
    token = _TRANSPORT.set("mcp")
    try:
        with principal_context(LOCAL_PRINCIPAL):
            async with Client(build_mcp_server(state)) as client:
                return await client.call_tool(name, arguments)
    finally:
        _TRANSPORT.reset(token)


async def _http_request(
    app: FastAPI, method: str, path: str, *, json_body: dict[str, Any] | None = None
) -> httpx2.Response:
    token = _TRANSPORT.set("http")
    try:
        async with httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app), base_url="http://test"
        ) as http:
            return await http.request(method, path, json=json_body)
    finally:
        _TRANSPORT.reset(token)


@pytest.mark.anyio
async def test_search_papers_parity() -> None:
    state = fake_state()
    app = _app(state)
    body = {
        "query": "hybrid retrieval",
        "snapshot_id": str(SAMPLE_SNAPSHOT_ID),
        "retrieval_profile_id": SAMPLE_PROFILE_ID,
        "mode": "reranked",
        "limit": 5,
    }
    async with app.router.lifespan_context(app):
        mcp = await _mcp_call(
            state, "search_papers", {"query": "hybrid retrieval", "limit": 5}
        )
        response = await _http_request(app, "POST", "/v1/search", json_body=body)
    http = response.json()
    agent = await _agent_observation(
        state,
        SearchPapersAction(tool="search_papers", query="hybrid retrieval", limit=5),
    )
    papers = mcp.structured_content["papers"]
    assert [(item["paper_id"], item["rank"]) for item in papers] == [
        (hit["paper_id"], hit["rank"]) for hit in http["hits"]
    ]
    assert [(item["paper_id"], item["rank"]) for item in papers] == [
        (item["paper_id"], item["rank"]) for item in agent.summary["papers"]
    ]
    assert mcp.structured_content["result_status"] == http["result_status"]
    assert mcp.structured_content["eligible_count"] == http["eligible_count"]
    assert mcp.structured_content["result_status"] == agent.summary["result_status"]
    assert mcp.structured_content["eligible_count"] == agent.summary["eligible_count"]


@pytest.mark.anyio
async def test_search_evidence_parity() -> None:
    state = fake_state()
    app = _app(state)
    body = {
        "query": "hybrid retrieval",
        "snapshot_id": str(SAMPLE_SNAPSHOT_ID),
        "retrieval_profile_id": SAMPLE_PROFILE_ID,
        "mode": "reranked",
        "limit": 5,
    }
    async with app.router.lifespan_context(app):
        mcp = await _mcp_call(
            state, "search_evidence", {"query": "hybrid retrieval", "limit": 5}
        )
        response = await _http_request(
            app, "POST", "/v1/evidence/search", json_body=body
        )
    http = response.json()
    agent = await _agent_observation(
        state,
        SearchEvidenceAction(tool="search_evidence", query="hybrid retrieval", limit=5),
    )
    evidence = mcp.structured_content["evidence"]
    assert [
        (item["chunk_id"], item["paper_id"], item["rank"]) for item in evidence
    ] == [(hit["chunk_id"], hit["paper_id"], hit["rank"]) for hit in http["hits"]]
    assert [
        (item["chunk_id"], item["paper_id"], item["rank"]) for item in evidence
    ] == [
        (item["chunk_id"], item["paper_id"], item["rank"])
        for item in agent.summary["chunks"]
    ]


@pytest.mark.anyio
async def test_get_paper_parity() -> None:
    state = fake_state()
    app = _app(state)
    async with app.router.lifespan_context(app):
        mcp = await _mcp_call(state, "get_paper", {"paper_id": SAMPLE_PAPER_A})
        response = await _http_request(
            app,
            "GET",
            f"/v1/papers/{SAMPLE_PAPER_A}?snapshot_id={SAMPLE_SNAPSHOT_ID}",
        )
    assert mcp.structured_content == response.json()


@pytest.mark.anyio
async def test_citation_parity() -> None:
    state = fake_state()
    app = _app(state)
    async with app.router.lifespan_context(app):
        for name, paper_id, action, path in (
            (
                "get_citations",
                SAMPLE_PAPER_B,
                GetCitationsAction(
                    tool="get_citations", paper_id=SAMPLE_PAPER_B, limit=5
                ),
                "citations",
            ),
            (
                "get_references",
                SAMPLE_PAPER_C,
                GetReferencesAction(
                    tool="get_references", paper_id=SAMPLE_PAPER_C, limit=5
                ),
                "references",
            ),
        ):
            mcp = await _mcp_call(state, name, {"paper_id": paper_id, "limit": 5})
            response = await _http_request(
                app,
                "GET",
                f"/v1/papers/{paper_id}/{path}?snapshot_id={SAMPLE_SNAPSHOT_ID}&limit=5",
            )
            agent = await _agent_observation(state, action)
            assert mcp.structured_content == response.json()
            assert [
                edge["endpoint"]["paper_id"] for edge in response.json()["edges"]
            ] == [edge["paper_id"] for edge in agent.summary["edges"]]


@pytest.mark.anyio
async def test_related_papers_parity() -> None:
    state = fake_state()
    mcp = await _mcp_call(
        state, "find_related_papers", {"paper_id": SAMPLE_PAPER_A, "limit": 5}
    )
    agent = await _agent_observation(
        state,
        FindRelatedPapersAction(
            tool="find_related_papers",
            paper_id=SAMPLE_PAPER_A,
            limit=5,
            basis="citations",
        ),
    )
    assert [item["paper_id"] for item in mcp.structured_content["papers"]] == [
        item["paper_id"] for item in agent.summary["papers"]
    ]


@pytest.mark.anyio
async def test_research_run_parity() -> None:
    state = fake_state()
    app = _app(state)
    async with app.router.lifespan_context(app):
        started = await _mcp_call(
            state,
            "start_research_run",
            {"question": "A synthetic research question"},
        )
        run = started.structured_content["run"]
        response = await _http_request(app, "GET", f"/v1/research/{run['run_id']}")
    assert response.status_code == 200
    assert json.loads(json.dumps(run)) == json.loads(json.dumps(response.json()))


@pytest.mark.anyio
async def test_http_and_mcp_reach_the_same_capability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = fake_state()
    app = _app(state)
    reached: dict[str, set[str]] = {
        name: set()
        for name in (
            "search_papers",
            "search_evidence",
            "read_paper",
            "citation_page",
            "related_papers",
            "start_run",
            "get_run",
        )
    }
    for name in reached:
        original = getattr(ResearchCapabilities, name)

        async def spy(
            self: Any,
            *args: Any,
            _name: str = name,
            _original: Any = original,
            **kwargs: Any,
        ) -> Any:
            reached[_name].add(_TRANSPORT.get())
            return await _original(self, *args, **kwargs)

        monkeypatch.setattr(ResearchCapabilities, name, spy)

    search_body = {
        "query": "hybrid retrieval",
        "snapshot_id": str(SAMPLE_SNAPSHOT_ID),
        "retrieval_profile_id": SAMPLE_PROFILE_ID,
        "mode": "reranked",
        "limit": 5,
    }
    evidence_body = {**search_body}
    async with app.router.lifespan_context(app):
        assert (
            await _http_request(app, "POST", "/v1/search", json_body=search_body)
        ).status_code == 200
        assert (
            await _http_request(
                app, "POST", "/v1/evidence/search", json_body=evidence_body
            )
        ).status_code == 200
        http_paper = await _http_request(
            app,
            "GET",
            f"/v1/papers/{SAMPLE_PAPER_A}?snapshot_id={SAMPLE_SNAPSHOT_ID}",
        )
        assert http_paper.status_code == 200
        http_citations = await _http_request(
            app,
            "GET",
            f"/v1/papers/{SAMPLE_PAPER_B}/citations?snapshot_id={SAMPLE_SNAPSHOT_ID}",
        )
        assert http_citations.status_code == 200
        http_run = await _http_request(
            app,
            "POST",
            "/v1/research",
            json_body={"question": "A synthetic research question", "mode": "quick"},
        )
        assert http_run.status_code == 202
        http_run_id = http_run.json()["run_id"]
        assert (
            await _http_request(app, "GET", f"/v1/research/{http_run_id}")
        ).status_code == 200

        for name, arguments in (
            ("search_papers", {"query": "hybrid retrieval", "limit": 5}),
            ("search_evidence", {"query": "hybrid retrieval", "limit": 5}),
            ("get_paper", {"paper_id": SAMPLE_PAPER_A}),
            ("get_citations", {"paper_id": SAMPLE_PAPER_B}),
            ("find_related_papers", {"paper_id": SAMPLE_PAPER_A}),
        ):
            result = await _mcp_call(state, name, arguments)
            assert not result.is_error
        mcp_run = await _mcp_call(
            state,
            "start_research_run",
            {"question": "A synthetic research question"},
        )
        assert not mcp_run.is_error
        mcp_run_id = mcp_run.structured_content["run"]["run_id"]
        mcp_read = await _mcp_call(state, "get_research_run", {"run_id": mcp_run_id})
        assert not mcp_read.is_error

    assert reached["search_papers"] == {"http", "mcp"}
    assert reached["search_evidence"] == {"http", "mcp"}
    assert reached["read_paper"] == {"http", "mcp"}
    assert reached["citation_page"] == {"http", "mcp"}
    assert reached["related_papers"] == {"mcp"}
    assert reached["start_run"] == {"http", "mcp"}
    assert reached["get_run"] == {"http", "mcp"}
