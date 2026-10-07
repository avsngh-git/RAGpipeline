"""The deep planner's first plan always includes search_evidence and, when it is
configured, discovery."""

from __future__ import annotations

from research_platform.agents.actions import (
    Action,
    DiscoverPapersAction,
    SearchEvidenceAction,
    SearchPapersAction,
)
from research_platform.agents.graph_deep import (
    discovery_query,
    ensure_first_plan_searches,
)
from research_platform.runs.contracts import ResearchFilters

_QUESTION = "synthetic question about reranking"


def _search(query: str = _QUESTION) -> SearchPapersAction:
    return SearchPapersAction(tool="search_papers", query=query)


def _evidence(query: str = _QUESTION) -> SearchEvidenceAction:
    return SearchEvidenceAction(tool="search_evidence", query=query)


def _filters(**values: int | None) -> ResearchFilters:
    return ResearchFilters.model_validate(values)


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
        filters=_filters(**filters),
        max_actions=max_actions,
        discovery=discovery,
    )


def _tools(actions: tuple[Action, ...]) -> list[str]:
    return [action.tool for action in actions]


def test_evidence_and_discovery_appended_when_missing() -> None:
    actions = _ensure((_search(),))

    assert _tools(actions) == ["search_papers", "search_evidence", "discover_papers"]
    evidence, discover = actions[1], actions[2]
    assert isinstance(evidence, SearchEvidenceAction)
    assert (evidence.query, evidence.limit, evidence.paper_ids) == (_QUESTION, 20, ())
    assert isinstance(discover, DiscoverPapersAction)
    assert discover.query == "synthetic OR question OR reranking"


def test_only_evidence_appended_without_discovery() -> None:
    assert _tools(_ensure((_search(),), discovery=False)) == [
        "search_papers",
        "search_evidence",
    ]


def test_existing_searches_are_kept_unchanged() -> None:
    planned = (
        _search(),
        _evidence("model query"),
        DiscoverPapersAction(tool="discover_papers", query="model query", limit=3),
    )

    assert _ensure(planned) == planned


def test_full_plan_keeps_first_choices_and_replaces_the_last() -> None:
    planned = tuple(_search(f"query {n}") for n in range(4))

    actions = _ensure(planned)

    assert actions[:2] == planned[:2]
    assert _tools(actions) == [
        "search_papers",
        "search_papers",
        "search_evidence",
        "discover_papers",
    ]


def test_two_action_plan_prefers_evidence_over_discovery() -> None:
    actions = _ensure((_search(), _search("other")), max_actions=2)

    assert _tools(actions) == ["search_papers", "search_evidence"]


def test_two_action_plan_with_evidence_adds_discovery() -> None:
    actions = _ensure((_search(), _evidence()), max_actions=2)

    assert _tools(actions) == ["search_papers", "discover_papers"]


def test_nothing_added_when_only_one_action_allowed() -> None:
    assert _ensure((_search(),), max_actions=1) == (_search(),)


def test_year_filter_is_clamped_to_discovery_floor() -> None:
    clamped = _ensure((_search(),), year_from=2015, year_to=2024)[-1]
    kept = _ensure((_search(),), year_from=2022)[-1]

    assert isinstance(clamped, DiscoverPapersAction)
    assert (clamped.year_from, clamped.year_to) == (None, 2024)
    assert isinstance(kept, DiscoverPapersAction)
    assert kept.year_from == 2022


def test_no_discovery_when_filter_ends_before_2020() -> None:
    actions = _ensure((_search(),), year_from=2010, year_to=2018)

    assert _tools(actions) == ["search_papers", "search_evidence"]


def test_long_question_is_truncated_to_each_query_limit() -> None:
    actions = _ensure((_search(),), question="q" * 1000)

    evidence, discover = actions[1], actions[2]
    assert isinstance(evidence, SearchEvidenceAction)
    assert len(evidence.query) == 500
    assert isinstance(discover, DiscoverPapersAction)
    assert len(discover.query) == 300


def test_discovery_query_joins_content_words_with_or() -> None:
    question = "How does ListT5 compare with the TREC-COVID and FiQA baselines?"

    assert discovery_query(question) == "ListT5 OR TREC-COVID OR FiQA OR baselines"


def test_discovery_query_drops_repeated_words() -> None:
    assert discovery_query("reranking or Reranking reranking") == (
        "reranking OR Reranking"
    )


def test_discovery_query_stops_at_the_query_limit() -> None:
    query = discovery_query(" ".join(f"term{n}" for n in range(200)))

    assert len(query) <= 300
    assert query.startswith("term0 OR term1 OR ")
    assert not query.endswith(" OR")


def test_discovery_query_falls_back_to_the_question() -> None:
    assert discovery_query("what is the") == "what is the"
