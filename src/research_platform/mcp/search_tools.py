"""Search tool registrations for the MCP server."""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from mcp.server import MCPServer
from mcp.types import ToolAnnotations
from pydantic import BaseModel, ConfigDict, Field

from research_platform.mcp.runtime import McpCall, run_call
from research_platform.search.contracts import (
    ComponentScores,
    EvidenceHit,
    PaperHit,
    RetrievalMode,
    SearchFilters,
    SearchOperation,
    SearchRequest,
)
from research_platform.services.errors import AppError
from research_platform.services.text_exposure import external_text_allowed


class EvidenceItem(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    chunk_id: str
    paper_id: str
    kind: str
    rank: int
    reranker_score: float | None
    page: int | None
    section: str | None
    text: str | None
    text_withheld: bool


class PaperItem(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    paper_id: str
    title: str | None
    publication_year: int | None
    rank: int
    reranker_score: float | None
    evidence: tuple[EvidenceItem, ...]


class PaperSearchResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    snapshot_id: UUID
    result_status: str
    eligible_count: int
    papers: tuple[PaperItem, ...]
    note: str


class EvidenceSearchResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    snapshot_id: UUID
    result_status: str
    eligible_count: int
    evidence: tuple[EvidenceItem, ...]
    note: str


def _reranker_score(scores: ComponentScores) -> float | None:
    reranker = scores.reranker
    return reranker.score if reranker is not None else None


def evidence_item(hit: EvidenceHit, *, text_allowed: bool) -> EvidenceItem:
    """Map a passage to the compact MCP search result."""
    heading_path = hit.source_spans[0].heading_path if hit.source_spans else ()
    return EvidenceItem(
        chunk_id=hit.chunk_id,
        paper_id=hit.paper_id,
        kind=hit.kind,
        rank=hit.rank,
        reranker_score=_reranker_score(hit.component_scores),
        page=(
            hit.source_location.page_index_zero_based + 1
            if hit.source_location.page_index_zero_based is not None
            else None
        ),
        section=" > ".join(heading_path) if heading_path else None,
        text=hit.text if text_allowed else None,
        text_withheld=not text_allowed,
    )


def paper_item(hit: PaperHit, *, text_allowed: bool) -> PaperItem:
    """Map a paper and its strongest passages to the compact MCP result."""
    return PaperItem(
        paper_id=hit.paper_id,
        title=hit.title,
        publication_year=hit.publication_year,
        rank=hit.rank,
        reranker_score=_reranker_score(hit.component_scores),
        evidence=tuple(
            evidence_item(evidence, text_allowed=text_allowed)
            for evidence in hit.supporting_evidence
        ),
    )


def result_note(*, text_allowed: bool) -> str:
    """Explain result ordering and any passage text policy."""
    note = (
        "Results are ranked best first; scores rank results and are not probabilities."
    )
    if not text_allowed:
        note += " Passage text is withheld by this server's policy."
    return note


def register_search_tools(server: MCPServer, state: Any) -> None:
    """Register search_papers and search_evidence (card P5-10)."""

    @server.tool(
        name="search_papers",
        description=(
            "Find papers in the research corpus that match a query. Returns up to "
            "limit distinct papers, best first, each with its OpenAlex work ID, "
            "title, year and its strongest supporting passages. Use the paper IDs "
            "with get_paper, get_citations, get_references and find_related_papers, "
            "or pass them to search_evidence to read more passages from those papers."
        ),
        annotations=ToolAnnotations(read_only_hint=True),
        structured_output=True,
    )
    async def search_papers(
        query: Annotated[
            str,
            Field(
                min_length=1,
                max_length=2000,
                description="Natural-language research query.",
            ),
        ],
        year_from: Annotated[
            int | None,
            Field(
                ge=1900,
                le=2100,
                description="Only papers published in or after this year.",
            ),
        ] = None,
        year_to: Annotated[
            int | None,
            Field(
                ge=1900,
                le=2100,
                description="Only papers published in or before this year.",
            ),
        ] = None,
        limit: Annotated[
            int,
            Field(ge=1, le=20, description="Maximum number of papers (default 10)."),
        ] = 10,
        snapshot_id: Annotated[
            UUID | None,
            Field(description="Corpus snapshot; omit to use the served snapshot."),
        ] = None,
    ) -> PaperSearchResult:
        async def operation(call: McpCall) -> PaperSearchResult:
            request = _search_request(
                query=query,
                year_from=year_from,
                year_to=year_to,
                paper_ids=None,
                limit=limit,
                snapshot_id=snapshot_id,
                call=call,
                operation=SearchOperation.PAPER_SEARCH,
            )
            response = await call.capabilities.search_papers(
                request, request_id=call.request_id
            )
            text_allowed = external_text_allowed(call.settings)
            return PaperSearchResult(
                snapshot_id=response.snapshot_id,
                result_status=response.result_status.value,
                eligible_count=response.eligible_count,
                papers=tuple(
                    paper_item(hit, text_allowed=text_allowed) for hit in response.hits
                ),
                note=result_note(text_allowed=text_allowed),
            )

        return await run_call(state, "search_papers", operation)

    @server.tool(
        name="search_evidence",
        description=(
            "Find passages and table excerpts that match a query, best first. "
            "Optionally restrict the search to papers by OpenAlex work ID "
            "(paper_ids). Each result gives its chunk ID, paper ID, page and "
            "section, and its text when this server allows passage text."
        ),
        annotations=ToolAnnotations(read_only_hint=True),
        structured_output=True,
    )
    async def search_evidence(
        query: Annotated[
            str,
            Field(
                min_length=1,
                max_length=2000,
                description="Natural-language research query.",
            ),
        ],
        paper_ids: Annotated[
            list[Annotated[str, Field(pattern=r"^W[0-9]+$")]] | None,
            Field(
                min_length=1,
                max_length=20,
                description=(
                    "Only passages from these OpenAlex work IDs, for example "
                    "from search_papers."
                ),
            ),
        ] = None,
        year_from: Annotated[
            int | None,
            Field(
                ge=1900,
                le=2100,
                description="Only papers published in or after this year.",
            ),
        ] = None,
        year_to: Annotated[
            int | None,
            Field(
                ge=1900,
                le=2100,
                description="Only papers published in or before this year.",
            ),
        ] = None,
        limit: Annotated[
            int,
            Field(
                ge=1,
                le=20,
                description="Maximum number of passages (default 10).",
            ),
        ] = 10,
        snapshot_id: Annotated[
            UUID | None,
            Field(description="Corpus snapshot; omit to use the served snapshot."),
        ] = None,
    ) -> EvidenceSearchResult:
        async def operation(call: McpCall) -> EvidenceSearchResult:
            request = _search_request(
                query=query,
                year_from=year_from,
                year_to=year_to,
                paper_ids=paper_ids,
                limit=limit,
                snapshot_id=snapshot_id,
                call=call,
                operation=SearchOperation.EVIDENCE_SEARCH,
            )
            response = await call.capabilities.search_evidence(
                request, request_id=call.request_id
            )
            text_allowed = external_text_allowed(call.settings)
            return EvidenceSearchResult(
                snapshot_id=response.snapshot_id,
                result_status=response.result_status.value,
                eligible_count=response.eligible_count,
                evidence=tuple(
                    evidence_item(hit, text_allowed=text_allowed)
                    for hit in response.hits
                ),
                note=result_note(text_allowed=text_allowed),
            )

        return await run_call(state, "search_evidence", operation)


def _search_request(
    *,
    query: str,
    year_from: int | None,
    year_to: int | None,
    paper_ids: list[str] | None,
    limit: int,
    snapshot_id: UUID | None,
    call: McpCall,
    operation: SearchOperation,
) -> SearchRequest:
    if year_from is not None and year_to is not None and year_from > year_to:
        raise AppError("invalid_request", "year_from must not be after year_to.", 422)
    serving = call.capabilities.resolve_snapshot(snapshot_id)
    try:
        return SearchRequest(
            query=query.strip(),
            snapshot_id=serving.snapshot_id,
            retrieval_profile_id=serving.retrieval_profile_id,
            mode=RetrievalMode.RERANKED,
            operation=operation,
            filters=SearchFilters(
                year_from=year_from,
                year_to=year_to,
                paper_ids=tuple(paper_ids) if paper_ids else None,
            ),
            limit=limit,
        )
    except ValueError:
        raise AppError(
            "invalid_request", "The search request is invalid.", 422
        ) from None
