"""The deep planner's first plan always includes discovery when it is configured."""

from __future__ import annotations

from research_platform.agents.actions import (
    DiscoverPapersAction,
    SearchEvidenceAction,
    SearchPapersAction,
)
from research_platform.agents.graph_deep import ensure_discovery
from research_platform.runs.contracts import ResearchFilters

_QUESTION = "synthetic question about reranking"


def _search() -> SearchPapersAction:
    return SearchPapersAction(tool="search_papers", query=_QUESTION)


def _evidence() -> SearchEvidenceAction:
    return SearchEvidenceAction(tool="search_evidence", query=_QUESTION)


def _filters(**values: int | None) -> ResearchFilters:
    return ResearchFilters.model_validate(values)


def test_discovery_appended_when_missing() -> None:
    actions = ensure_discovery(
        (_search(),), question=_QUESTION, filters=_filters(), max_actions=4
    )

    assert [action.tool for action in actions] == ["search_papers", "discover_papers"]
    discover = actions[-1]
    assert isinstance(discover, DiscoverPapersAction)
    assert discover.query == _QUESTION


def test_existing_discovery_is_kept_unchanged() -> None:
    planned = (
        _search(),
        DiscoverPapersAction(tool="discover_papers", query="model query", limit=3),
    )

    assert (
        ensure_discovery(planned, question=_QUESTION, filters=_filters(), max_actions=4)
        == planned
    )


def test_full_plan_replaces_last_action() -> None:
    actions = ensure_discovery(
        (_search(), _evidence()),
        question=_QUESTION,
        filters=_filters(),
        max_actions=2,
    )

    assert [action.tool for action in actions] == ["search_papers", "discover_papers"]


def test_nothing_added_when_only_one_action_allowed() -> None:
    assert ensure_discovery(
        (_search(),), question=_QUESTION, filters=_filters(), max_actions=1
    ) == (_search(),)


def test_year_filter_is_clamped_to_discovery_floor() -> None:
    clamped = ensure_discovery(
        (_search(),),
        question=_QUESTION,
        filters=_filters(year_from=2015, year_to=2024),
        max_actions=4,
    )[-1]
    kept = ensure_discovery(
        (_search(),),
        question=_QUESTION,
        filters=_filters(year_from=2022),
        max_actions=4,
    )[-1]

    assert isinstance(clamped, DiscoverPapersAction)
    assert (clamped.year_from, clamped.year_to) == (None, 2024)
    assert isinstance(kept, DiscoverPapersAction)
    assert kept.year_from == 2022


def test_nothing_added_when_filter_ends_before_2020() -> None:
    assert ensure_discovery(
        (_search(),),
        question=_QUESTION,
        filters=_filters(year_from=2010, year_to=2018),
        max_actions=4,
    ) == (_search(),)


def test_long_question_is_truncated_to_the_query_limit() -> None:
    discover = ensure_discovery(
        (_search(),), question="q" * 1000, filters=_filters(), max_actions=4
    )[-1]

    assert isinstance(discover, DiscoverPapersAction)
    assert len(discover.query) == 300
