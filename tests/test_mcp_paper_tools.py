"""Paper and citation capabilities exposed by the MCP server."""

from __future__ import annotations

import asyncio
import json
from contextlib import AbstractContextManager
from uuid import uuid4

import pytest
from mcp import Client, MCPError

from research_platform.mcp.server import build_mcp_server
from research_platform.mcp.testing import fake_state, sample_corpus


def _reader_context() -> AbstractContextManager[None]:
    from research_platform.auth.keys import Principal, Scope
    from research_platform.mcp.principal import principal_context

    return principal_context(Principal("tester", frozenset({Scope.READ})))


def test_tools_are_listed_read_only() -> None:
    state = fake_state()
    expected = {
        "get_paper": "Read one paper's metadata in the corpus snapshot: title, publication year, metadata availability and the document version used as evidence. Takes an OpenAlex work ID such as W2741809807. Returns no passage text.",
        "get_citations": "List papers that cite this paper, from citation links stored for the corpus. Citing papers outside the corpus are marked as such. Pass next_cursor back as cursor to read the next page.",
        "get_references": "List papers this paper cites, from citation links stored for the corpus. Referenced papers outside the corpus are marked as such. Pass next_cursor back as cursor to read the next page.",
        "find_related_papers": "Find corpus papers related to this paper through shared references and co-citations, strongest first, with their relation counts.",
    }

    async def inspect() -> None:
        with _reader_context():
            async with Client(build_mcp_server(state)) as client:
                tools = await client.list_tools()

        by_name = {tool.name: tool for tool in tools.tools}
        for name, description in expected.items():
            assert by_name[name].description == description
            assert by_name[name].annotations.read_only_hint is True

    asyncio.run(inspect())


def test_get_paper_matches_the_fake_paper() -> None:
    state = fake_state()

    async def inspect() -> None:
        with _reader_context():
            async with Client(build_mcp_server(state)) as client:
                result = await client.call_tool("get_paper", {"paper_id": "W100"})

        assert result.is_error is False
        assert result.structured_content["title"] == "Retrieval paper A"
        assert result.structured_content["publication_year"] == 2021

    asyncio.run(inspect())


def test_get_citations_lists_citing_papers() -> None:
    state = fake_state()

    async def inspect() -> None:
        with _reader_context():
            async with Client(build_mcp_server(state)) as client:
                result = await client.call_tool("get_citations", {"paper_id": "W200"})

        assert result.is_error is False
        endpoints = result.structured_content["edges"]
        assert {edge["endpoint"]["paper_id"] for edge in endpoints} == {
            "W100",
            "W300",
        }

    asyncio.run(inspect())


def test_get_references_lists_cited_papers() -> None:
    state = fake_state()

    async def inspect() -> None:
        with _reader_context():
            async with Client(build_mcp_server(state)) as client:
                result = await client.call_tool("get_references", {"paper_id": "W300"})

        assert result.is_error is False
        endpoints = result.structured_content["edges"]
        assert {edge["endpoint"]["paper_id"] for edge in endpoints} == {
            "W100",
            "W200",
        }

    asyncio.run(inspect())


def test_find_related_papers_returns_related_items() -> None:
    state = fake_state()

    async def inspect() -> None:
        with _reader_context():
            async with Client(build_mcp_server(state)) as client:
                result = await client.call_tool(
                    "find_related_papers", {"paper_id": "W100"}
                )

        assert result.is_error is False
        payload = result.structured_content
        assert payload["paper_id"] == "W100"
        assert payload["snapshot_id"] == str(
            state.research_services.serving.snapshot_id
        )
        assert payload["papers"]
        assert all("relations" in paper for paper in payload["papers"])

    asyncio.run(inspect())


def test_bad_paper_id_is_a_tool_error() -> None:
    state = fake_state()

    async def inspect() -> None:
        with _reader_context():
            async with Client(build_mcp_server(state)) as client:
                result = await client.call_tool("get_paper", {"paper_id": "123"})

        assert result.is_error is True

    asyncio.run(inspect())


def test_foreign_snapshot_is_rejected() -> None:
    state = fake_state()

    async def inspect() -> None:
        with _reader_context():
            async with Client(build_mcp_server(state)) as client:
                result = await client.call_tool(
                    "get_paper",
                    {"paper_id": "W100", "snapshot_id": str(uuid4())},
                )

        assert result.is_error is True
        assert "incompatible_snapshot" in result.content[0].text

    asyncio.run(inspect())


def test_paper_resource_template_is_listed() -> None:
    state = fake_state()

    async def inspect() -> None:
        with _reader_context():
            async with Client(build_mcp_server(state)) as client:
                templates = await client.list_resource_templates()

        assert any(
            template.uri_template == "paper://{paper_id}"
            for template in templates.resource_templates
        )

    asyncio.run(inspect())


def test_paper_resource_reads_json() -> None:
    state = fake_state()

    async def inspect() -> None:
        with _reader_context():
            async with Client(build_mcp_server(state)) as client:
                resource = await client.read_resource("paper://W100")

        payload = json.loads(resource.contents[0].text)
        assert payload["paper_id"] == "W100"

    asyncio.run(inspect())


def test_paper_resource_rejects_a_bad_id() -> None:
    state = fake_state()

    async def inspect() -> None:
        with _reader_context():
            async with Client(build_mcp_server(state)) as client:
                with pytest.raises(MCPError, match="invalid_request"):
                    await client.read_resource("paper://bad")

    asyncio.run(inspect())


def test_outputs_contain_no_passage_text() -> None:
    state = fake_state()
    passages = {passage.text for passage in sample_corpus().passages}

    async def inspect() -> None:
        with _reader_context():
            async with Client(build_mcp_server(state)) as client:
                results = [
                    await client.call_tool("get_paper", {"paper_id": "W100"}),
                    await client.call_tool("get_citations", {"paper_id": "W200"}),
                    await client.call_tool("get_references", {"paper_id": "W300"}),
                    await client.call_tool("find_related_papers", {"paper_id": "W100"}),
                ]

        serialized = " ".join(str(result.structured_content) for result in results)
        assert all(passage not in serialized for passage in passages)

    asyncio.run(inspect())
