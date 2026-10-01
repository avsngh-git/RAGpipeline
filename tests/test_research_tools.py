"""Offline tests for typed research tools and their deterministic service fakes."""

from __future__ import annotations

from uuid import UUID

import pytest

from research_platform.agents.actions import (
    FindRelatedPapersAction,
    GetCitationsAction,
    GetPaperAction,
    GetReferencesAction,
    SearchEvidenceAction,
    SearchPapersAction,
)
from research_platform.runs.contracts import ResearchFilters, RunBudgets
from research_platform.search.access import EvidenceAccessDenied
from research_platform.search.application_errors import (
    IncompatibleRetrievalProfile,
    RetrievalExecutionFailure,
    SearchDependencyUnavailable,
)
from research_platform.search.contracts import (
    RetrievalMode,
    SearchFilters,
    SearchOperation,
    SearchRequest,
)
from research_platform.search.paper_reads import PaperIdentityConflict, SnapshotNotFound
from research_platform.tools.fakes import (
    FakeCorpus,
    FakePaper,
    FakePassage,
    FakeServices,
    fake_services,
)
from research_platform.tools.research_tools import (
    ResearchTools,
    ToolContext,
    ToolLedger,
)

SNAPSHOT_ID = UUID("00000000-0000-0000-0000-000000000001")
RUN_ID = UUID("00000000-0000-0000-0000-000000000002")
PROFILE_ID = "sha256:" + "a" * 64
PAPER_A = "W100"
PAPER_B = "W200"
PAPER_C = "W300"


def _corpus() -> FakeCorpus:
    return FakeCorpus(
        snapshot_id=SNAPSHOT_ID,
        papers=(
            FakePaper(PAPER_A, "Retrieval paper A", 2021),
            FakePaper(PAPER_B, "Retrieval paper B", 2023),
            FakePaper(PAPER_C, "Other paper C", 2024),
        ),
        passages=(
            FakePassage("chunk-a1", PAPER_A, "Hybrid retrieval improves recall."),
            FakePassage("chunk-a2", PAPER_A, "Dense retrieval baseline."),
            FakePassage("chunk-b1", PAPER_B, "Hybrid retrieval supports evidence."),
            FakePassage("chunk-c1", PAPER_C, "Unrelated ranking result."),
        ),
        citations=(
            (PAPER_A, PAPER_B),
            (PAPER_B, PAPER_C),
            (PAPER_C, PAPER_A),
            (PAPER_C, PAPER_B),
        ),
    )


def _context(
    *, filters: ResearchFilters | None = None, budgets: RunBudgets | None = None
) -> ToolContext:
    return ToolContext(
        run_id=RUN_ID,
        snapshot_id=SNAPSHOT_ID,
        retrieval_profile_id=PROFILE_ID,
        filters=filters or ResearchFilters(),
        budgets=budgets or RunBudgets(),
    )


def _tools(corpus: FakeCorpus | None = None) -> tuple[ResearchTools, FakeServices]:
    resolved = corpus or _corpus()
    services = FakeServices(resolved)
    return (
        ResearchTools(
            search=services,
            papers=services,
            citations=services,
            related=services,
        ),
        services,
    )


@pytest.mark.anyio
async def test_search_papers_builds_reranked_request_and_collects_supporting_evidence() -> (
    None
):
    tools, services = _tools()
    requests: list[SearchRequest] = []
    original = services.execute

    async def record(request: SearchRequest, *, request_id: str):
        requests.append(request)
        return await original(request, request_id=request_id)

    services.execute = record  # type: ignore[method-assign]
    observation, ledger = await tools.execute(
        SearchPapersAction(tool="search_papers", query="hybrid retrieval", limit=2),
        context=_context(),
        ledger=ToolLedger(),
    )

    assert observation.status == "succeeded"
    assert requests[0].mode is RetrievalMode.RERANKED
    assert requests[0].operation is SearchOperation.PAPER_SEARCH
    assert requests[0].snapshot_id == SNAPSHOT_ID
    assert requests[0].retrieval_profile_id == PROFILE_ID
    assert observation.summary["papers"][0]["paper_id"] == PAPER_A
    assert observation.evidence[0].text == "Hybrid retrieval improves recall."
    assert observation.evidence[0].title == "Retrieval paper A"
    assert ledger.tool_calls_used == 1


@pytest.mark.anyio
async def test_search_evidence_passes_paper_ids_and_years() -> None:
    tools, services = _tools()
    requests: list[SearchRequest] = []
    original = services.execute

    async def record(request: SearchRequest, *, request_id: str):
        requests.append(request)
        return await original(request, request_id=request_id)

    services.execute = record  # type: ignore[method-assign]
    observation, _ = await tools.execute(
        SearchEvidenceAction(
            tool="search_evidence",
            query="hybrid retrieval",
            paper_ids=(PAPER_B,),
            year_from=2020,
            year_to=2025,
        ),
        context=_context(filters=ResearchFilters(year_from=2022, year_to=2025)),
        ledger=ToolLedger(),
    )

    assert requests[0].operation is SearchOperation.EVIDENCE_SEARCH
    assert requests[0].filters.paper_ids == (PAPER_B,)
    assert (requests[0].filters.year_from, requests[0].filters.year_to) == (2022, 2025)
    assert observation.summary["chunks"][0]["paper_id"] == PAPER_B
    assert all(hit.paper_id == PAPER_B for hit in observation.evidence)


@pytest.mark.anyio
async def test_duplicate_action_is_served_from_cache_without_service_call() -> None:
    tools, services = _tools()
    action = SearchPapersAction(tool="search_papers", query="hybrid retrieval")
    first, ledger = await tools.execute(action, context=_context(), ledger=ToolLedger())
    original = services.execute

    async def unexpected(*args: object, **kwargs: object):
        raise AssertionError("cached calls must not reach search")

    services.execute = unexpected  # type: ignore[method-assign]
    second, ledger = await tools.execute(action, context=_context(), ledger=ledger)

    assert first.status == "succeeded"
    assert second.status == "cached"
    assert second.evidence == ()
    assert second.summary == first.summary
    assert ledger.tool_calls_used == 1
    assert ledger.records == 2
    services.execute = original  # type: ignore[method-assign]


@pytest.mark.anyio
async def test_budget_exhausted_rejects_without_service_call() -> None:
    tools, services = _tools()

    async def unexpected(*args: object, **kwargs: object):
        raise AssertionError("rejected calls must not reach search")

    services.execute = unexpected  # type: ignore[method-assign]
    observation, ledger = await tools.execute(
        SearchPapersAction(tool="search_papers", query="hybrid retrieval"),
        context=_context(budgets=RunBudgets(max_tool_calls=1)),
        ledger=ToolLedger(tool_calls_used=1),
    )

    assert observation.status == "rejected"
    assert observation.error_category == "budget_exhausted"
    assert ledger.tool_calls_used == 1
    assert ledger.records == 1


@pytest.mark.anyio
async def test_citation_depth_is_tracked_and_enforced() -> None:
    tools, _ = _tools()
    observation, ledger = await tools.execute(
        GetCitationsAction(tool="get_citations", paper_id=PAPER_A),
        context=_context(),
        ledger=ToolLedger(),
    )
    assert observation.status == "succeeded"
    assert ledger.paper_depths[PAPER_C] == 1

    _, ledger = await tools.execute(
        GetReferencesAction(tool="get_references", paper_id=PAPER_C),
        context=_context(),
        ledger=ledger,
    )
    assert ledger.paper_depths[PAPER_B] == 2

    rejected, ledger = await tools.execute(
        FindRelatedPapersAction(tool="find_related_papers", paper_id=PAPER_B),
        context=_context(),
        ledger=ledger,
    )
    assert rejected.status == "rejected"
    assert rejected.error_category == "citation_depth_exceeded"
    assert ledger.tool_calls_used == 2


@pytest.mark.anyio
async def test_year_filters_intersect_and_empty_range_is_rejected() -> None:
    tools, services = _tools()
    requests: list[SearchRequest] = []
    original = services.execute

    async def record(request: SearchRequest, *, request_id: str):
        requests.append(request)
        return await original(request, request_id=request_id)

    services.execute = record  # type: ignore[method-assign]
    observation, ledger = await tools.execute(
        SearchPapersAction(
            tool="search_papers", query="hybrid retrieval", year_from=2021, year_to=2025
        ),
        context=_context(filters=ResearchFilters(year_from=2022, year_to=2023)),
        ledger=ToolLedger(),
    )
    assert observation.status == "succeeded"
    assert (requests[0].filters.year_from, requests[0].filters.year_to) == (2022, 2023)

    empty, ledger = await tools.execute(
        SearchEvidenceAction(
            tool="search_evidence",
            query="hybrid retrieval",
            year_from=2019,
            year_to=2021,
        ),
        context=_context(filters=ResearchFilters(year_from=2022)),
        ledger=ledger,
    )
    assert empty.status == "rejected"
    assert empty.error_category == "empty_filter"
    assert len(requests) == 1
    assert ledger.tool_calls_used == 1


@pytest.mark.anyio
async def test_get_paper_citations_references_and_related_summaries() -> None:
    tools, _ = _tools()
    paper, ledger = await tools.execute(
        GetPaperAction(tool="get_paper", paper_id=PAPER_A),
        context=_context(),
        ledger=ToolLedger(),
    )
    assert paper.summary == {
        "paper_id": PAPER_A,
        "title": "Retrieval paper A",
        "year": 2021,
        "status": "in_snapshot",
    }

    citations, ledger = await tools.execute(
        GetCitationsAction(tool="get_citations", paper_id=PAPER_A),
        context=_context(),
        ledger=ledger,
    )
    assert citations.summary["edges"][0]["paper_id"] == PAPER_C
    assert citations.summary["coverage_note"]

    references, ledger = await tools.execute(
        GetReferencesAction(tool="get_references", paper_id=PAPER_A),
        context=_context(),
        ledger=ledger,
    )
    assert references.summary["edges"][0]["paper_id"] == PAPER_B

    related, _ = await tools.execute(
        FindRelatedPapersAction(tool="find_related_papers", paper_id=PAPER_A),
        context=_context(),
        ledger=ledger,
    )
    assert related.summary["papers"]
    assert related.summary["coverage_note"]


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("error", "category", "retryable"),
    [
        (SearchDependencyUnavailable("unavailable"), "retrieval_error", True),
        (RetrievalExecutionFailure("failed"), "retrieval_error", True),
        (TimeoutError("late"), "retrieval_error", True),
        (SnapshotNotFound("missing"), "invalid_argument", False),
        (PaperIdentityConflict("ambiguous"), "invalid_argument", False),
        (IncompatibleRetrievalProfile("mismatch"), "invalid_argument", False),
        (ValueError("invalid"), "invalid_argument", False),
        (EvidenceAccessDenied("forbidden"), "access_denied", False),
    ],
)
async def test_service_errors_map_to_failed_observations(
    error: Exception, category: str, retryable: bool
) -> None:
    tools, services = _tools()

    async def fail(*args: object, **kwargs: object):
        raise error

    services.execute = fail  # type: ignore[method-assign]
    observation, ledger = await tools.execute(
        SearchPapersAction(tool="search_papers", query="hybrid retrieval"),
        context=_context(),
        ledger=ToolLedger(),
    )
    assert observation.status == "failed"
    assert observation.error_category == category
    assert observation.retryable is retryable
    assert ledger.tool_calls_used == 1


@pytest.mark.anyio
async def test_unexpected_exception_propagates() -> None:
    tools, services = _tools()

    async def fail(*args: object, **kwargs: object):
        raise RuntimeError("unexpected")

    services.execute = fail  # type: ignore[method-assign]
    with pytest.raises(RuntimeError, match="unexpected"):
        await tools.execute(
            SearchPapersAction(tool="search_papers", query="hybrid retrieval"),
            context=_context(),
            ledger=ToolLedger(),
        )


@pytest.mark.anyio
async def test_ordinals_increase_for_every_call_including_rejected() -> None:
    tools, _ = _tools()
    first, ledger = await tools.execute(
        SearchPapersAction(tool="search_papers", query="hybrid retrieval"),
        context=_context(budgets=RunBudgets(max_tool_calls=1)),
        ledger=ToolLedger(),
    )
    rejected, ledger = await tools.execute(
        SearchEvidenceAction(tool="search_evidence", query="dense retrieval"),
        context=_context(budgets=RunBudgets(max_tool_calls=1)),
        ledger=ledger,
    )
    cached, ledger = await tools.execute(
        SearchPapersAction(tool="search_papers", query="hybrid retrieval"),
        context=_context(budgets=RunBudgets(max_tool_calls=1)),
        ledger=ledger,
    )
    assert (first.ordinal, rejected.ordinal, cached.ordinal) == (0, 1, 2)
    assert ledger.records == 3
    assert ledger.tool_calls_used == 1


@pytest.mark.anyio
async def test_summary_contains_no_passage_text() -> None:
    tools, _ = _tools()
    observation, _ = await tools.execute(
        SearchEvidenceAction(tool="search_evidence", query="hybrid retrieval"),
        context=_context(),
        ledger=ToolLedger(),
    )
    assert observation.evidence
    summary = str(observation.summary)
    assert all(hit.text not in summary for hit in observation.evidence)


@pytest.mark.anyio
async def test_fake_search_is_deterministic_and_filters_years() -> None:
    search, _, _, _ = fake_services(_corpus())
    request = SearchRequest(
        query="hybrid retrieval",
        snapshot_id=SNAPSHOT_ID,
        retrieval_profile_id=PROFILE_ID,
        mode=RetrievalMode.RERANKED,
        operation=SearchOperation.EVIDENCE_SEARCH,
        filters=SearchFilters(year_from=2022, year_to=2024),
        limit=10,
    )
    first = await search.execute(request, request_id="fake:0")
    second = await search.execute(request, request_id="fake:1")
    assert [hit.chunk_id for hit in first.hits] == [hit.chunk_id for hit in second.hits]
    assert [hit.chunk_id for hit in first.hits] == ["chunk-b1"]
