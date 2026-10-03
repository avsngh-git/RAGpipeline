"""Native Ollama tool schemas map back to validated agent actions."""

import pytest

from research_platform.agents.tool_schemas import (
    TOOL_DESCRIPTIONS,
    actions_from_tool_calls,
    research_tool_definitions,
)


def _call(name: str, arguments: object) -> dict[str, object]:
    return {"function": {"name": name, "arguments": arguments}}


def test_definitions_cover_six_tools_without_tool_property() -> None:
    definitions = research_tool_definitions()

    assert len(definitions) == 6
    for definition in definitions:
        function = definition["function"]
        assert isinstance(function, dict)
        name = function["name"]
        assert isinstance(name, str)
        assert function["description"] == TOOL_DESCRIPTIONS[name]
        parameters = function["parameters"]
        assert isinstance(parameters, dict)
        properties = parameters["properties"]
        assert isinstance(properties, dict)
        assert "tool" not in properties
        assert "tool" not in parameters.get("required", [])


def test_actions_from_tool_calls_parses_dict_and_string_arguments() -> None:
    actions = actions_from_tool_calls(
        (
            _call("search_papers", {"query": "dense retrieval"}),
            _call("get_paper", '{"paper_id":"W123"}'),
        ),
        max_actions=4,
    )

    assert [action.tool for action in actions] == ["search_papers", "get_paper"]
    assert actions[0].query == "dense retrieval"
    assert actions[1].paper_id == "W123"


def test_unknown_tool_and_bad_arguments_raise() -> None:
    with pytest.raises(ValueError, match="unknown tool"):
        actions_from_tool_calls((_call("search_the_web", {}),), max_actions=4)
    with pytest.raises(ValueError, match="invalid tool arguments"):
        actions_from_tool_calls((_call("search_papers", {"limit": 0}),), max_actions=4)
    with pytest.raises(ValueError, match="invalid tool arguments"):
        actions_from_tool_calls((_call("search_papers", "{"),), max_actions=4)


def test_max_actions_truncates() -> None:
    actions = actions_from_tool_calls(
        (
            _call("get_paper", {"paper_id": "W1"}),
            _call("get_paper", {"paper_id": "W2"}),
        ),
        max_actions=1,
    )

    assert len(actions) == 1
    assert actions[0].paper_id == "W1"
