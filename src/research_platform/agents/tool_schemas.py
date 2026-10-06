"""Native tool definitions and validated conversion to research actions."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Final

from pydantic import BaseModel, TypeAdapter

from research_platform.agents.actions import (
    Action,
    DiscoverPapersAction,
    FindRelatedPapersAction,
    GetCitationsAction,
    GetPaperAction,
    GetReferencesAction,
    RequestIngestionAction,
    SearchEvidenceAction,
    SearchPapersAction,
)

TOOL_DESCRIPTIONS: Final[dict[str, str]] = {
    "discover_papers": (
        "search OpenAlex for papers not in the local corpus; returns candidates with "
        "abstracts and whether they are already ingested"
    ),
    "request_ingestion": (
        "ask to add up to five discover_papers candidates to the local corpus; code "
        "decides each paper and reports the decisions"
    ),
    "search_papers": (
        "find papers relevant to a query; returns ranked papers with supporting "
        "passages."
    ),
    "search_evidence": (
        "find specific passages for a query, optionally limited to given paper_ids."
    ),
    "get_paper": "read one paper's title, year and availability by paper_id.",
    "get_citations": "list stored papers that cite the given paper_id.",
    "get_references": "list stored papers that the given paper_id cites.",
    "find_related_papers": (
        "find papers related to paper_id by stored citation relationships or semantic similarity."
    ),
}

_ACTION_MODELS: Final[tuple[tuple[str, type[BaseModel]], ...]] = (
    ("discover_papers", DiscoverPapersAction),
    ("request_ingestion", RequestIngestionAction),
    ("search_papers", SearchPapersAction),
    ("search_evidence", SearchEvidenceAction),
    ("get_paper", GetPaperAction),
    ("get_citations", GetCitationsAction),
    ("get_references", GetReferencesAction),
    ("find_related_papers", FindRelatedPapersAction),
)
_ACTION_ADAPTER: Final[TypeAdapter[Action]] = TypeAdapter(Action)


def research_tool_definitions() -> list[dict[str, object]]:
    """Return Ollama-compatible definitions for the typed research actions."""
    tools: list[dict[str, object]] = []
    for name, model in _ACTION_MODELS:
        schema = model.model_json_schema()
        properties_value = schema.get("properties")
        if not isinstance(properties_value, dict):
            raise ValueError("action schema properties must be an object")
        arguments_schema = dict(schema)
        arguments_schema["properties"] = {
            key: value for key, value in properties_value.items() if key != "tool"
        }
        required_value = schema.get("required", [])
        if isinstance(required_value, list):
            arguments_schema["required"] = [
                key for key in required_value if key != "tool"
            ]
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": TOOL_DESCRIPTIONS[name],
                    "parameters": arguments_schema,
                },
            }
        )
    return tools


def actions_from_tool_calls(
    calls: Sequence[Mapping[str, object]], *, max_actions: int
) -> tuple[Action, ...]:
    """Validate native calls into actions, retaining at most ``max_actions``."""
    if max_actions < 1:
        raise ValueError("max_actions must be positive")
    if not calls:
        raise ValueError("Ollama reply did not contain tool_calls")

    actions: list[Action] = []
    for call in calls[:max_actions]:
        function = call.get("function")
        if not isinstance(function, Mapping):
            raise ValueError("Ollama returned an invalid tool call")
        name = function.get("name")
        arguments = function.get("arguments")
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError as exc:
                raise ValueError("Ollama returned invalid tool arguments") from exc
        if not isinstance(name, str) or name not in TOOL_DESCRIPTIONS:
            raise ValueError("Ollama returned an unknown tool")
        if not isinstance(arguments, Mapping):
            raise ValueError("Ollama returned invalid tool arguments")
        try:
            action = _ACTION_ADAPTER.validate_python({**arguments, "tool": name})
        except (TypeError, ValueError) as exc:
            raise ValueError("Ollama returned invalid tool arguments") from exc
        actions.append(action)
    return tuple(actions)
