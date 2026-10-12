"""Protocol tests for the MCP search tools."""

from __future__ import annotations

import json
from uuid import UUID

import pytest
from mcp import Client

from research_platform.api import create_app as _create_app  # noqa: F401
from research_platform.auth.keys import Principal, Scope
from research_platform.mcp.principal import principal_context
from research_platform.mcp.server import build_mcp_server
from research_platform.mcp.testing import (
    SAMPLE_PAPER_A,
    SAMPLE_PAPER_B,
    SAMPLE_PROFILE_ID,
    SAMPLE_SNAPSHOT_ID,
    fake_state,
    make_settings,
)
from research_platform.search.contracts import RetrievalMode, SearchRequest

PAPER_DESCRIPTION = (
    "Find papers in the research corpus that match a query. Returns up to limit "
    "distinct papers, best first, each with its OpenAlex work ID, title, year and "
    "its strongest supporting passages. Use the paper IDs with get_paper, "
    "get_citations, get_references and find_related_papers, or pass them to "
    "search_evidence to read more passages from those papers."
)
EVIDENCE_DESCRIPTION = (
    "Find passages and table excerpts that match a query, best first. Optionally "
    "restrict the search to papers by OpenAlex work ID (paper_ids). Each result "
    "gives its chunk ID, paper ID, page and section, and its text when this server "
    "allows passage text."
)


@pytest.mark.anyio
async def test_tools_are_listed_read_only_with_schemas() -> None:
    state = fake_state()
    server = build_mcp_server(state)

    with principal_context(Principal("tester", frozenset({Scope.READ}))):
        async with Client(server) as client:
            tools = {tool.name: tool for tool in (await client.list_tools()).tools}

    assert set(tools) == {"search_papers", "search_evidence"}
    assert tools["search_papers"].annotations.read_only_hint is True
    assert tools["search_evidence"].annotations.read_only_hint is True
    assert tools["search_papers"].output_schema is not None
    assert tools["search_evidence"].output_schema is not None
    assert tools["search_papers"].description == PAPER_DESCRIPTION
    assert tools["search_evidence"].description == EVIDENCE_DESCRIPTION


@pytest.mark.anyio
async def test_search_papers_returns_compact_papers() -> None:
    server = build_mcp_server(fake_state())

    with principal_context(Principal("tester", frozenset({Scope.READ}))):
        async with Client(server) as client:
            result = await client.call_tool(
                "search_papers", {"query": "hybrid retrieval"}
            )

    content = result.structured_content
    assert content is not None
    assert [paper["paper_id"] for paper in content["papers"]] == [
        SAMPLE_PAPER_A,
        SAMPLE_PAPER_B,
    ]
    assert content["result_status"] == "ranked_candidates"
    assert all(
        set(paper)
        == {
            "paper_id",
            "title",
            "publication_year",
            "rank",
            "reranker_score",
            "evidence",
        }
        for paper in content["papers"]
    )


@pytest.mark.anyio
async def test_text_is_withheld_by_default() -> None:
    server = build_mcp_server(fake_state())

    with principal_context(Principal("tester", frozenset({Scope.READ}))):
        async with Client(server) as client:
            result = await client.call_tool(
                "search_evidence", {"query": "hybrid retrieval"}
            )

    content = result.structured_content
    assert content is not None
    assert all(item["text"] is None for item in content["evidence"])
    assert all(item["text_withheld"] is True for item in content["evidence"])
    encoded = json.dumps(content)
    assert "Hybrid retrieval improves recall." not in encoded
    assert "Hybrid retrieval supports evidence." not in encoded
    assert "Passage text is withheld" in content["note"]


@pytest.mark.anyio
async def test_text_is_returned_for_a_trusted_private_client() -> None:
    settings = make_settings(text_policy="trusted_private_client")
    server = build_mcp_server(fake_state(settings=settings))

    with principal_context(Principal("tester", frozenset({Scope.READ}))):
        async with Client(server) as client:
            result = await client.call_tool(
                "search_evidence", {"query": "hybrid retrieval"}
            )

    content = result.structured_content
    assert content is not None
    assert [item["text"] for item in content["evidence"]] == [
        "Hybrid retrieval improves recall.",
        "Hybrid retrieval supports evidence.",
        "Dense retrieval baseline.",
    ]
    assert all(item["text_withheld"] is False for item in content["evidence"])


@pytest.mark.anyio
async def test_search_evidence_filters_by_paper_ids() -> None:
    server = build_mcp_server(fake_state())

    with principal_context(Principal("tester", frozenset({Scope.READ}))):
        async with Client(server) as client:
            result = await client.call_tool(
                "search_evidence",
                {"query": "hybrid retrieval", "paper_ids": [SAMPLE_PAPER_B]},
            )

    content = result.structured_content
    assert content is not None
    assert [item["paper_id"] for item in content["evidence"]] == [SAMPLE_PAPER_B]


@pytest.mark.anyio
async def test_year_range_is_validated() -> None:
    server = build_mcp_server(fake_state())

    with principal_context(Principal("tester", frozenset({Scope.READ}))):
        async with Client(server) as client:
            result = await client.call_tool(
                "search_evidence",
                {"query": "hybrid retrieval", "year_from": 2024, "year_to": 2020},
            )

    assert result.is_error is True
    assert result.content[0].text.startswith(
        "Error executing tool search_evidence: invalid_request:"
    )


@pytest.mark.anyio
async def test_bad_paper_id_is_rejected() -> None:
    server = build_mcp_server(fake_state())

    with principal_context(Principal("tester", frozenset({Scope.READ}))):
        async with Client(server) as client:
            result = await client.call_tool(
                "search_evidence",
                {"query": "hybrid retrieval", "paper_ids": ["not-an-id"]},
            )

    assert result.is_error is True


@pytest.mark.anyio
async def test_foreign_snapshot_is_rejected() -> None:
    server = build_mcp_server(fake_state())
    foreign_snapshot = UUID("00000000-0000-0000-0000-000000000099")

    with principal_context(Principal("tester", frozenset({Scope.READ}))):
        async with Client(server) as client:
            result = await client.call_tool(
                "search_evidence",
                {"query": "hybrid retrieval", "snapshot_id": str(foreign_snapshot)},
            )

    assert result.is_error is True
    assert "incompatible_snapshot" in result.content[0].text


@pytest.mark.anyio
async def test_disabled_evidence_profile_is_permission_denied() -> None:
    settings = make_settings(evidence_access_profile="disabled")
    server = build_mcp_server(fake_state(settings=settings))

    with principal_context(Principal("tester", frozenset({Scope.READ}))):
        async with Client(server) as client:
            result = await client.call_tool(
                "search_evidence", {"query": "hybrid retrieval"}
            )

    assert result.is_error is True
    assert "permission_denied" in result.content[0].text


@pytest.mark.anyio
async def test_search_uses_the_served_profile_in_reranked_mode() -> None:
    state = fake_state()
    search = state.phase2_services.search
    recorded: list[SearchRequest] = []

    class RecordingSearch:
        async def execute(self, request: SearchRequest, *, request_id: str):
            recorded.append(request)
            return await search.execute(request, request_id=request_id)

    state.phase2_services.search = RecordingSearch()
    server = build_mcp_server(state)

    with principal_context(Principal("tester", frozenset({Scope.READ}))):
        async with Client(server) as client:
            await client.call_tool("search_papers", {"query": "hybrid retrieval"})

    assert len(recorded) == 1
    assert recorded[0].snapshot_id == SAMPLE_SNAPSHOT_ID
    assert recorded[0].retrieval_profile_id == SAMPLE_PROFILE_ID
    assert recorded[0].mode is RetrievalMode.RERANKED
