"""Execute validated research actions through bounded application services."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import asdict
from time import perf_counter
from typing import Any, Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from research_platform.agents.actions import (
    Action,
    FindRelatedPapersAction,
    GetCitationsAction,
    GetPaperAction,
    GetReferencesAction,
    SearchEvidenceAction,
    SearchPapersAction,
    action_key,
)
from research_platform.runs.contracts import ResearchFilters, RunBudgets
from research_platform.search.access import EvidenceAccessDenied
from research_platform.search.application_errors import (
    IncompatibleRetrievalProfile,
    RetrievalExecutionFailure,
    SearchDependencyUnavailable,
)
from research_platform.search.contracts import (
    DEFAULT_SEARCH_LIMITS,
    EvidenceHit,
    PaperHit,
    RetrievalMode,
    SearchFilters,
    SearchOperation,
    SearchRequest,
    SearchResponse,
)
from research_platform.search.paper_graph import (
    CitationDirection,
    CitationEndpointStatus,
    CitationGraphCursor,
    CitationGraphPage,
)
from research_platform.search.paper_reads import (
    PaperIdentityConflict,
    SnapshotNotFound,
    SnapshotPaperRead,
)
from research_platform.search.paper_related import RelatedPapersPage


class SearchService(Protocol):
    """Framework-independent ranked search service."""

    async def execute(
        self, request: SearchRequest, *, request_id: str
    ) -> SearchResponse[Any]: ...


class PaperService(Protocol):
    """Snapshot-aware paper metadata reader."""

    async def read_paper(
        self, snapshot_id: UUID, paper_id: str
    ) -> SnapshotPaperRead: ...


class CitationService(Protocol):
    """Snapshot-aware one-hop citation reader."""

    async def read_one_hop(
        self,
        snapshot_id: UUID,
        paper_id: str,
        direction: CitationDirection,
        *,
        limit: int = 20,
        cursor: CitationGraphCursor | None = None,
    ) -> CitationGraphPage: ...


class RelatedService(Protocol):
    """Snapshot-aware related-paper reader."""

    async def find_related(
        self, snapshot_id: UUID, paper_id: str, *, limit: int = 10
    ) -> RelatedPapersPage: ...


class ToolContext(BaseModel):
    """Immutable run-specific inputs required to execute a tool action."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: UUID
    snapshot_id: UUID
    retrieval_profile_id: str
    filters: ResearchFilters
    budgets: RunBudgets


class ToolLedger(BaseModel):
    """Checkpointable counters, duplicate cache and citation depths."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tool_calls_used: int = Field(default=0, ge=0)
    records: int = Field(default=0, ge=0)
    cache: dict[str, dict[str, Any]] = Field(default_factory=dict)
    paper_depths: dict[str, int] = Field(default_factory=dict)


class CollectedEvidence(BaseModel):
    """Evidence text with the minimal source metadata needed by later graph nodes."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    chunk_id: str
    paper_id: str
    text: str
    title: str | None
    publication_year: int | None
    kind: str
    source_location: dict[str, Any]
    reranker_score: float | None


class ToolObservation(BaseModel):
    """Compact outcome of one attempted, cached or rejected tool action."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ordinal: int = Field(ge=0)
    tool: str
    arguments: dict[str, Any]
    status: Literal["succeeded", "failed", "rejected", "cached"]
    summary: dict[str, Any]
    evidence: tuple[CollectedEvidence, ...] = ()
    error_category: str | None = None
    retryable: bool = False
    duration_ms: float = Field(default=0.0, ge=0)


class ResearchTools:
    """Apply budgets and dispatch actions to existing search and graph services."""

    def __init__(
        self,
        *,
        search: SearchService,
        papers: PaperService,
        citations: CitationService,
        related: RelatedService,
    ) -> None:
        self._search = search
        self._papers = papers
        self._citations = citations
        self._related = related

    async def execute(
        self,
        action: Action,
        *,
        context: ToolContext,
        ledger: ToolLedger,
    ) -> tuple[ToolObservation, ToolLedger]:
        """Return one deterministic observation and its updated checkpoint ledger."""
        ordinal = ledger.records
        arguments = action.model_dump(mode="json")
        key = action_key(action)

        if key in ledger.cache:
            return self._record(
                ledger,
                ToolObservation(
                    ordinal=ordinal,
                    tool=action.tool,
                    arguments=arguments,
                    status="cached",
                    summary=ledger.cache[key],
                ),
            )
        if ledger.tool_calls_used >= context.budgets.max_tool_calls:
            return self._record(
                ledger,
                ToolObservation(
                    ordinal=ordinal,
                    tool=action.tool,
                    arguments=arguments,
                    status="rejected",
                    summary={},
                    error_category="budget_exhausted",
                ),
            )
        if isinstance(
            action, (GetCitationsAction, GetReferencesAction, FindRelatedPapersAction)
        ) and ledger.paper_depths.get(action.paper_id, 0) >= (
            context.budgets.max_citation_depth
        ):
            return self._record(
                ledger,
                ToolObservation(
                    ordinal=ordinal,
                    tool=action.tool,
                    arguments=arguments,
                    status="rejected",
                    summary={},
                    error_category="citation_depth_exceeded",
                ),
            )

        effective_years = _intersect_years(
            context.filters.year_from,
            context.filters.year_to,
            action.year_from
            if isinstance(action, (SearchPapersAction, SearchEvidenceAction))
            else None,
            action.year_to
            if isinstance(action, (SearchPapersAction, SearchEvidenceAction))
            else None,
        )
        if effective_years is None:
            return self._record(
                ledger,
                ToolObservation(
                    ordinal=ordinal,
                    tool=action.tool,
                    arguments=arguments,
                    status="rejected",
                    summary={},
                    error_category="empty_filter",
                ),
            )

        request_id = f"{context.run_id}:{ordinal}"
        started = perf_counter()
        updated = ledger.model_copy(
            update={
                "records": ledger.records + 1,
                "tool_calls_used": ledger.tool_calls_used + 1,
            }
        )
        try:
            async with asyncio.timeout(DEFAULT_SEARCH_LIMITS.request_timeout_seconds):
                summary, evidence, paper_depths = await self._dispatch(
                    action,
                    context=context,
                    request_id=request_id,
                    effective_years=effective_years,
                    ledger=ledger,
                )
        except (SearchDependencyUnavailable, RetrievalExecutionFailure, TimeoutError):
            observation = ToolObservation(
                ordinal=ordinal,
                tool=action.tool,
                arguments=arguments,
                status="failed",
                summary={},
                error_category="retrieval_error",
                retryable=True,
                duration_ms=_duration_ms(started),
            )
            return observation, updated
        except (
            SnapshotNotFound,
            PaperIdentityConflict,
            IncompatibleRetrievalProfile,
            ValueError,
        ):
            observation = ToolObservation(
                ordinal=ordinal,
                tool=action.tool,
                arguments=arguments,
                status="failed",
                summary={},
                error_category="invalid_argument",
                retryable=False,
                duration_ms=_duration_ms(started),
            )
            return observation, updated
        except EvidenceAccessDenied:
            observation = ToolObservation(
                ordinal=ordinal,
                tool=action.tool,
                arguments=arguments,
                status="failed",
                summary={},
                error_category="access_denied",
                retryable=False,
                duration_ms=_duration_ms(started),
            )
            return observation, updated

        observation = ToolObservation(
            ordinal=ordinal,
            tool=action.tool,
            arguments=arguments,
            status="succeeded",
            summary=summary,
            evidence=evidence,
            duration_ms=_duration_ms(started),
        )
        depths = dict(ledger.paper_depths)
        for paper_id, depth in paper_depths.items():
            if isinstance(action, (SearchPapersAction, SearchEvidenceAction)):
                depths.setdefault(paper_id, 0)
            else:
                depths[paper_id] = min(depths.get(paper_id, depth), depth)
        updated = updated.model_copy(
            update={"cache": {**ledger.cache, key: summary}, "paper_depths": depths}
        )
        return observation, updated

    async def _dispatch(
        self,
        action: Action,
        *,
        context: ToolContext,
        request_id: str,
        effective_years: tuple[int | None, int | None],
        ledger: ToolLedger,
    ) -> tuple[dict[str, Any], tuple[CollectedEvidence, ...], dict[str, int]]:
        if isinstance(action, (SearchPapersAction, SearchEvidenceAction)):
            operation = (
                SearchOperation.PAPER_SEARCH
                if isinstance(action, SearchPapersAction)
                else SearchOperation.EVIDENCE_SEARCH
            )
            filters = SearchFilters(
                year_from=effective_years[0],
                year_to=effective_years[1],
                paper_ids=(
                    action.paper_ids
                    if isinstance(action, SearchEvidenceAction) and action.paper_ids
                    else None
                ),
            )
            request = SearchRequest(
                query=action.query,
                snapshot_id=context.snapshot_id,
                retrieval_profile_id=context.retrieval_profile_id,
                mode=RetrievalMode.RERANKED,
                operation=operation,
                filters=filters,
                limit=action.limit,
            )
            response = await self._search.execute(request, request_id=request_id)
            depths: dict[str, int] = {}
            if isinstance(action, SearchPapersAction):
                assert all(isinstance(hit, PaperHit) for hit in response.hits)
                papers = tuple(
                    hit for hit in response.hits if isinstance(hit, PaperHit)
                )
                evidence = tuple(
                    _collected_evidence(
                        item, title=paper.title, year=paper.publication_year
                    )
                    for paper in papers
                    for item in paper.supporting_evidence
                )
                for paper in papers:
                    depths.setdefault(paper.paper_id, 0)
                summary = {
                    "papers": [
                        {
                            "paper_id": paper.paper_id,
                            "title": paper.title,
                            "year": paper.publication_year,
                            "rank": paper.rank,
                        }
                        for paper in papers
                    ],
                    "eligible_count": response.eligible_count,
                    "result_status": response.result_status.value,
                }
            else:
                assert all(isinstance(hit, EvidenceHit) for hit in response.hits)
                hits = tuple(
                    hit for hit in response.hits if isinstance(hit, EvidenceHit)
                )
                evidence = tuple(
                    _collected_evidence(hit, title=None, year=None) for hit in hits
                )
                for hit in hits:
                    depths.setdefault(hit.paper_id, 0)
                summary = {
                    "chunks": [
                        {
                            "chunk_id": hit.chunk_id,
                            "paper_id": hit.paper_id,
                            "rank": hit.rank,
                        }
                        for hit in hits
                    ],
                    "eligible_count": response.eligible_count,
                    "result_status": response.result_status.value,
                }
            return summary, evidence, depths

        if isinstance(action, GetPaperAction):
            paper_read = await self._papers.read_paper(
                context.snapshot_id, action.paper_id
            )
            return (
                {
                    "paper_id": paper_read.paper_id,
                    "title": paper_read.title,
                    "year": paper_read.publication_year,
                    "status": paper_read.status.value,
                },
                (),
                {},
            )

        if isinstance(action, (GetCitationsAction, GetReferencesAction)):
            direction = (
                CitationDirection.CITATIONS
                if isinstance(action, GetCitationsAction)
                else CitationDirection.REFERENCES
            )
            citation_page = await self._citations.read_one_hop(
                context.snapshot_id,
                action.paper_id,
                direction,
                limit=action.limit,
            )
            source_depth = ledger.paper_depths.get(action.paper_id, 0)
            depths = {
                edge.endpoint.paper_id: min(
                    ledger.paper_depths.get(edge.endpoint.paper_id, source_depth + 1),
                    source_depth + 1,
                )
                for edge in citation_page.edges
                if edge.endpoint.status is CitationEndpointStatus.IN_SNAPSHOT
                and edge.endpoint.paper_id is not None
            }
            return (
                {
                    "edges": [
                        {
                            "paper_id": edge.endpoint.paper_id or "external",
                            "title": edge.endpoint.title,
                            "year": edge.endpoint.publication_year,
                            "status": edge.endpoint.status.value,
                        }
                        for edge in citation_page.edges
                    ],
                    "coverage_note": citation_page.coverage_note,
                },
                (),
                depths,
            )

        if isinstance(action, FindRelatedPapersAction):
            related_page = await self._related.find_related(
                context.snapshot_id, action.paper_id, limit=action.limit
            )
            source_depth = ledger.paper_depths.get(action.paper_id, 0)
            depths = {
                paper.paper_id: min(
                    ledger.paper_depths.get(paper.paper_id, source_depth + 1),
                    source_depth + 1,
                )
                for paper in related_page.papers
            }
            return (
                {
                    "papers": [
                        {
                            "paper_id": paper.paper_id,
                            "title": paper.title,
                            "year": paper.publication_year,
                            "score": paper.score,
                            "relations": [
                                relation.value for relation in paper.relations
                            ],
                        }
                        for paper in related_page.papers
                    ],
                    "coverage_note": related_page.coverage_note,
                },
                (),
                depths,
            )
        raise TypeError(f"unsupported research action: {type(action).__name__}")

    @staticmethod
    def _record(
        ledger: ToolLedger, observation: ToolObservation
    ) -> tuple[ToolObservation, ToolLedger]:
        return observation, ledger.model_copy(update={"records": ledger.records + 1})


def _intersect_years(
    run_from: int | None,
    run_to: int | None,
    action_from: int | None,
    action_to: int | None,
) -> tuple[int | None, int | None] | None:
    starts = [value for value in (run_from, action_from) if value is not None]
    ends = [value for value in (run_to, action_to) if value is not None]
    year_from = max(starts) if starts else None
    year_to = min(ends) if ends else None
    if year_from is not None and year_to is not None and year_from > year_to:
        return None
    return year_from, year_to


def _collected_evidence(
    hit: EvidenceHit, *, title: str | None, year: int | None
) -> CollectedEvidence:
    score = hit.component_scores.reranker
    location: Mapping[str, Any] = asdict(hit.source_location)
    return CollectedEvidence(
        chunk_id=hit.chunk_id,
        paper_id=hit.paper_id,
        text=hit.text,
        title=title,
        publication_year=year,
        kind=hit.kind,
        source_location=dict(location),
        reranker_score=score.score if score is not None else None,
    )


def _duration_ms(started: float) -> float:
    return max(0.0, (perf_counter() - started) * 1000)
