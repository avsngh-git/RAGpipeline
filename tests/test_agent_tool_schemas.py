"""Native Ollama tool schemas map back to validated agent actions."""

import re

import pytest

from research_platform.agents.tool_schemas import (
    TOOL_DESCRIPTIONS,
    actions_from_tool_calls,
    research_tool_definitions,
    tool_schema_digest,
)


def _call(name: str, arguments: object) -> dict[str, object]:
    return {"function": {"name": name, "arguments": arguments}}


def test_tool_schema_digest_is_stable() -> None:
    first = tool_schema_digest()

    assert first == tool_schema_digest()
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", first)


def test_definitions_cover_eight_tools_without_tool_property() -> None:
    definitions = research_tool_definitions()

    assert len(definitions) == 8
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


def test_discover_papers_tool_definition() -> None:
    definition = next(
        item["function"]
        for item in research_tool_definitions()
        if item["function"]["name"] == "discover_papers"
    )
    assert definition["description"] == (
        "search OpenAlex for papers not in the local corpus; returns candidates with "
        "abstracts and whether they are already ingested"
    )
    parameters = definition["parameters"]
    assert isinstance(parameters, dict)
    properties = parameters["properties"]
    assert isinstance(properties, dict)
    assert properties["query"]["minLength"] == 1
    assert properties["query"]["maxLength"] == 300
    for year_field in ("year_from", "year_to"):
        variants = properties[year_field]["anyOf"]
        integer_variant = next(
            variant for variant in variants if variant.get("type") == "integer"
        )
        assert integer_variant["minimum"] == 2020
        assert integer_variant["maximum"] == 2100
    assert properties["limit"]["default"] == 5
    assert properties["limit"]["minimum"] == 1
    assert properties["limit"]["maximum"] == 10


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


@pytest.mark.anyio
async def test_fitness_native_plan_rejects_overlong_batches() -> None:
    import httpx

    from research_platform.config import Settings
    from research_platform.llm.types import CallKind
    from scripts.phase3_generator_fitness import FitnessCase, _native_plan

    calls = [_call("get_paper", {"paper_id": f"W{index}"}) for index in range(5)]
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"message": {"tool_calls": calls}})
    )
    case = FitnessCase(
        "overlong-plan",
        CallKind.PLAN,
        ({"role": "user", "content": "Find papers."},),
        {"tools": ["get_paper"]},
    )
    async with httpx.AsyncClient(
        transport=transport, base_url="http://ollama.test"
    ) as http:
        result = await _native_plan(http, Settings(), case, think=True)

    assert result[0] is None
    assert result[4] == "ValidationError"


def test_fitness_uses_shared_tool_descriptions() -> None:
    from scripts import phase3_generator_fitness

    assert phase3_generator_fitness.TOOL_DESCRIPTIONS is TOOL_DESCRIPTIONS
