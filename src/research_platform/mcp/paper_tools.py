"""Paper and citation tool registrations for the MCP server."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Annotated, Any
from uuid import UUID

from mcp.server import MCPServer
from mcp.types import ToolAnnotations
from pydantic import BaseModel, ConfigDict, Field

from research_platform.search.paper_graph import CitationDirection
from research_platform.search.paper_related import RelatedPapersPage

if TYPE_CHECKING:
    from research_platform.api.schemas.papers import (
        CitationGraphResponse,
        PaperReadResponse,
    )
    from research_platform.mcp.runtime import McpCall


class RelatedPaperItem(BaseModel):
    """A compact related-paper result without passage text."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    paper_id: str
    title: str | None
    publication_year: int | None
    shared_reference_count: int
    co_citation_count: int
    score: int
    relations: tuple[str, ...]


class RelatedPapersResult(BaseModel):
    """Related papers found in one served corpus snapshot."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    snapshot_id: UUID
    paper_id: str
    source_status: str
    papers: tuple[RelatedPaperItem, ...]
    coverage_note: str


def related_result(page: RelatedPapersPage) -> RelatedPapersResult:
    """Map the related-paper contract to its MCP output model."""
    return RelatedPapersResult(
        snapshot_id=page.snapshot_id,
        paper_id=page.paper_id,
        source_status=page.source_status.value,
        papers=tuple(
            RelatedPaperItem(
                paper_id=paper.paper_id,
                title=paper.title,
                publication_year=paper.publication_year,
                shared_reference_count=paper.shared_reference_count,
                co_citation_count=paper.co_citation_count,
                score=paper.score,
                relations=tuple(relation.value for relation in paper.relations),
            )
            for paper in page.papers
        ),
        coverage_note=page.coverage_note,
    )


PaperId = Annotated[
    str,
    Field(
        pattern=r"^W[0-9]+$",
        description="OpenAlex work ID, for example W2741809807.",
    ),
]
SnapshotArg = Annotated[
    UUID | None, Field(description="Corpus snapshot; omit to use the served snapshot.")
]


def register_paper_tools(server: MCPServer, state: Any) -> None:
    """Register the paper and citation tools and paper:// (card P5-11)."""
    from research_platform.api.errors import AppError
    from research_platform.api.schemas.papers import (
        CitationGraphResponse,
        PaperReadResponse,
    )
    from research_platform.mcp.runtime import McpCall, run_call

    globals()["CitationGraphResponse"] = CitationGraphResponse
    globals()["PaperReadResponse"] = PaperReadResponse
    globals()["McpCall"] = McpCall

    @server.tool(
        name="get_paper",
        description="Read one paper's metadata in the corpus snapshot: title, publication year, metadata availability and the document version used as evidence. Takes an OpenAlex work ID such as W2741809807. Returns no passage text.",
        annotations=ToolAnnotations(read_only_hint=True),
        structured_output=True,
    )
    async def get_paper(
        paper_id: PaperId, snapshot_id: SnapshotArg = None
    ) -> PaperReadResponse:
        async def operation(call: McpCall) -> PaperReadResponse:
            serving = call.capabilities.resolve_snapshot(snapshot_id)
            paper = await call.capabilities.read_paper(serving.snapshot_id, paper_id)
            return PaperReadResponse.from_contract(paper)

        return await run_call(state, "get_paper", operation)

    @server.tool(
        name="get_citations",
        description="List papers that cite this paper, from citation links stored for the corpus. Citing papers outside the corpus are marked as such. Pass next_cursor back as cursor to read the next page.",
        annotations=ToolAnnotations(read_only_hint=True),
        structured_output=True,
    )
    async def get_citations(
        paper_id: PaperId,
        limit: Annotated[
            int, Field(ge=1, le=100, description="Maximum citing papers (default 20).")
        ] = 20,
        cursor: Annotated[
            str | None,
            Field(max_length=2048, description="next_cursor from the previous page."),
        ] = None,
        snapshot_id: SnapshotArg = None,
    ) -> CitationGraphResponse:
        async def operation(call: McpCall) -> CitationGraphResponse:
            serving = call.capabilities.resolve_snapshot(snapshot_id)
            page, next_cursor = await call.capabilities.citation_page(
                serving.snapshot_id,
                paper_id,
                CitationDirection.CITATIONS,
                limit=limit,
                cursor=cursor,
            )
            return CitationGraphResponse.from_contract(page, next_cursor=next_cursor)

        return await run_call(state, "get_citations", operation)

    @server.tool(
        name="get_references",
        description="List papers this paper cites, from citation links stored for the corpus. Referenced papers outside the corpus are marked as such. Pass next_cursor back as cursor to read the next page.",
        annotations=ToolAnnotations(read_only_hint=True),
        structured_output=True,
    )
    async def get_references(
        paper_id: PaperId,
        limit: Annotated[
            int, Field(ge=1, le=100, description="Maximum citing papers (default 20).")
        ] = 20,
        cursor: Annotated[
            str | None,
            Field(max_length=2048, description="next_cursor from the previous page."),
        ] = None,
        snapshot_id: SnapshotArg = None,
    ) -> CitationGraphResponse:
        async def operation(call: McpCall) -> CitationGraphResponse:
            serving = call.capabilities.resolve_snapshot(snapshot_id)
            page, next_cursor = await call.capabilities.citation_page(
                serving.snapshot_id,
                paper_id,
                CitationDirection.REFERENCES,
                limit=limit,
                cursor=cursor,
            )
            return CitationGraphResponse.from_contract(page, next_cursor=next_cursor)

        return await run_call(state, "get_references", operation)

    @server.tool(
        name="find_related_papers",
        description="Find corpus papers related to this paper through shared references and co-citations, strongest first, with their relation counts.",
        annotations=ToolAnnotations(read_only_hint=True),
        structured_output=True,
    )
    async def find_related_papers(
        paper_id: PaperId,
        limit: Annotated[
            int, Field(ge=1, le=20, description="Maximum related papers (default 10).")
        ] = 10,
        snapshot_id: SnapshotArg = None,
    ) -> RelatedPapersResult:
        async def operation(call: McpCall) -> RelatedPapersResult:
            serving = call.capabilities.resolve_snapshot(snapshot_id)
            page = await call.capabilities.related_papers(
                serving.snapshot_id, paper_id, limit=limit
            )
            return related_result(page)

        return await run_call(state, "find_related_papers", operation)

    @server.resource(
        "paper://{paper_id}",
        name="paper",
        description="Metadata of one corpus paper by OpenAlex work ID, as JSON.",
        mime_type="application/json",
    )
    async def paper_resource(paper_id: str) -> str:
        async def operation(call: McpCall) -> str:
            if re.fullmatch(r"W[0-9]+", paper_id) is None:
                raise AppError(
                    "invalid_request",
                    "paper_id must be an OpenAlex work ID such as W2741809807.",
                    422,
                )
            serving = call.capabilities.serving()
            paper = await call.capabilities.read_paper(serving.snapshot_id, paper_id)
            return PaperReadResponse.from_contract(paper).model_dump_json()

        return await run_call(state, "paper_resource", operation, resource=True)
