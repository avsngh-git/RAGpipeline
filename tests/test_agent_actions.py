"""Tests for typed research agent actions."""

import json

import pytest
from pydantic import ValidationError

from research_platform.agents.actions import (
    ActionBatch,
    FindRelatedPapersAction,
    GetCitationsAction,
    GetPaperAction,
    GetReferencesAction,
    SearchEvidenceAction,
    SearchPapersAction,
    SufficiencyDecision,
    action_key,
)


@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        ("search_papers", {"query": "retrieval"}),
        ("search_evidence", {"query": "retrieval", "paper_ids": ["W1"]}),
        ("get_paper", {"paper_id": "W1"}),
        ("get_citations", {"paper_id": "W1"}),
        ("get_references", {"paper_id": "W1"}),
        ("find_related_papers", {"paper_id": "W1"}),
    ],
)
def test_action_batch_parses_each_tool_from_json(
    tool: str, arguments: dict[str, object]
) -> None:
    action_data = {"tool": tool, **arguments}
    batch = ActionBatch.model_validate_json(
        json.dumps({"rationale": "Find evidence", "actions": [action_data]})
    )
    assert batch.actions[0].tool == tool


def test_unknown_tool_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ActionBatch.model_validate(
            {"rationale": "Unknown", "actions": [{"tool": "run_sql"}]}
        )


@pytest.mark.parametrize("actions", [[], [{"tool": "get_paper", "paper_id": "W1"}] * 5])
def test_action_batch_bounds(actions: list[dict[str, str]]) -> None:
    with pytest.raises(ValidationError):
        ActionBatch.model_validate({"rationale": "Bound test", "actions": actions})


def test_sufficient_decision_ignores_next_actions() -> None:
    action = SearchPapersAction(tool="search_papers", query="retrieval")
    assert SufficiencyDecision(sufficient=True).next_actions == ()
    assert (
        SufficiencyDecision(sufficient=True, next_actions=(action,)).next_actions == ()
    )
    parsed = SufficiencyDecision.model_validate_json(
        '{"sufficient": true, "next_actions": [{"tool": "get_paper", "paper_id": "W1"}]}'
    )
    assert parsed.next_actions == ()
    assert SufficiencyDecision(
        sufficient=False, next_actions=(action,)
    ).next_actions == (action,)


def test_action_key_normalizes_query_and_paper_ids() -> None:
    first = SearchEvidenceAction(
        tool="search_evidence", query="  Retrieval  ", paper_ids=("W2", "W1")
    )
    second = SearchEvidenceAction(
        tool="search_evidence", query="retrieval", paper_ids=("W1", "W2")
    )
    assert action_key(first) == action_key(second)


def test_action_batch_json_schema_has_discriminator() -> None:
    schema = ActionBatch.model_json_schema()
    schema_text = json.dumps(schema)
    for tool in (
        "search_papers",
        "search_evidence",
        "get_paper",
        "get_citations",
        "get_references",
        "find_related_papers",
    ):
        assert tool in schema_text
    assert '"propertyName": "tool"' in schema_text


@pytest.mark.parametrize(
    "action",
    [
        SearchPapersAction(tool="search_papers", query="retrieval"),
        SearchEvidenceAction(tool="search_evidence", query="evidence"),
        GetPaperAction(tool="get_paper", paper_id=" W1 "),
        GetCitationsAction(tool="get_citations", paper_id=" W1 "),
        GetReferencesAction(tool="get_references", paper_id=" W1 "),
        FindRelatedPapersAction(tool="find_related_papers", paper_id=" W1 "),
    ],
)
def test_action_models_strip_strings(action: object) -> None:
    if hasattr(action, "paper_id"):
        assert action.paper_id == "W1"


@pytest.mark.parametrize(
    "values",
    [{"year_from": 2025, "year_to": 2024}],
)
def test_search_actions_reject_inverted_year_range(
    values: dict[str, int],
) -> None:
    with pytest.raises(ValidationError):
        SearchPapersAction(tool="search_papers", query="retrieval", **values)
    with pytest.raises(ValidationError):
        SearchEvidenceAction(tool="search_evidence", query="retrieval", **values)
