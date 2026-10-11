"""The deep planner's first plan starts with whole-question searches, then the
model's actions."""

from __future__ import annotations

from research_platform.agents.actions import (
    Action,
    DiscoverPapersAction,
    GetPaperAction,
    SearchEvidenceAction,
    SearchPapersAction,
)
from research_platform.agents.graph_deep import ensure_first_plan_searches
from research_platform.runs.contracts import ResearchFilters

_QUESTION = "synthetic question about reranking"
_BASE = ["search_papers", "search_evidence", "discover_papers"]


def _search(query: str, limit: int = 10) -> SearchPapersAction:
    return SearchPapersAction(tool="search_papers", query=query, limit=limit)


def _paper(paper_id: str = "W1") -> GetPaperAction:
    return GetPaperAction(tool="get_paper", paper_id=paper_id)


def _ensure(
    planned: tuple[Action, ...],
    *,
    max_actions: int = 4,
    discovery: bool = True,
    question: str = _QUESTION,
    **filters: int | None,
) -> tuple[Action, ...]:
    return ensure_first_plan_searches(
        planned,
        question=question,
        filters=ResearchFilters.model_validate(filters),
        max_actions=max_actions,
        discovery=discovery,
    )


def _tools(actions: tuple[Action, ...]) -> list[str]:
    return [action.tool for action in actions]


def test_base_searches_come_first_then_the_model_action() -> None:
    actions = _ensure((_search("FiQA"),))

    assert _tools(actions) == [*_BASE, "search_papers"]
    papers, evidence, discover, model = actions
    assert isinstance(papers, SearchPapersAction)
    assert (papers.query, papers.limit) == (_QUESTION, 10)
    assert isinstance(evidence, SearchEvidenceAction)
    assert (evidence.query, evidence.limit, evidence.paper_ids) == (_QUESTION, 20, ())
    assert isinstance(discover, DiscoverPapersAction)
    assert (discover.query, discover.limit) == (_QUESTION, 5)
    assert model == _search("FiQA")


def test_model_actions_fill_the_remaining_slots_in_order() -> None:
    actions = _ensure((_paper("W1"), _paper("W2"), _paper("W3")), discovery=False)

    assert _tools(actions) == [
        "search_papers",
        "search_evidence",
        "get_paper",
        "get_paper",
    ]
    assert actions[2:] == (_paper("W1"), _paper("W2"))


def test_model_search_with_a_base_query_is_a_repeat() -> None:
    actions = _ensure((_search(_QUESTION, limit=5), _paper()))

    assert _tools(actions) == [*_BASE, "get_paper"]


def test_small_budget_keeps_base_order() -> None:
    assert _tools(_ensure((_paper(),), max_actions=2)) == _BASE[:2]
    assert _tools(_ensure((_paper(),), max_actions=1)) == ["search_papers"]


def test_paper_search_keeps_the_run_year_filter() -> None:
    papers = _ensure((), year_from=2015, year_to=2024)[0]

    assert isinstance(papers, SearchPapersAction)
    assert (papers.year_from, papers.year_to) == (2015, 2024)


def test_discovery_year_filter_is_clamped_to_its_floor() -> None:
    clamped = _ensure((), year_from=2015, year_to=2024)[2]
    kept = _ensure((), year_from=2022)[2]

    assert isinstance(clamped, DiscoverPapersAction)
    assert (clamped.year_from, clamped.year_to) == (None, 2024)
    assert isinstance(kept, DiscoverPapersAction)
    assert kept.year_from == 2022


def test_no_discovery_when_unconfigured_or_filter_ends_before_2020() -> None:
    assert _tools(_ensure((), discovery=False)) == _BASE[:2]
    assert _tools(_ensure((), year_from=2010, year_to=2018)) == _BASE[:2]


def test_long_question_is_truncated_to_each_query_limit() -> None:
    papers, evidence, discover = _ensure((), question="q" * 1000)

    assert isinstance(papers, SearchPapersAction)
    assert len(papers.query) == 500
    assert isinstance(evidence, SearchEvidenceAction)
    assert len(evidence.query) == 500
    assert isinstance(discover, DiscoverPapersAction)
    assert len(discover.query) == 300
