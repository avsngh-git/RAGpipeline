import json
from pathlib import Path

from research_platform.agents.actions import ActionBatch, SearchPapersAction
from research_platform.llm.types import CallKind
from scripts.phase3_generator_fitness import (
    ACTION_TOOL_NAMES,
    OUTPUT_TOKEN_LIMITS,
    THINKING_TOKEN_ALLOWANCE,
    TOOL_DESCRIPTIONS,
    FitnessAnswer,
    FitnessCase,
    FitnessClaim,
    FitnessJudgement,
    _native_tools,
    case_messages,
    load_cases,
    output_token_limit,
    score_case,
    validate_case_coverage,
)


def test_plan_score_uses_tool_set() -> None:
    value = ActionBatch(
        rationale="route the query",
        actions=(SearchPapersAction(tool="search_papers", query="amber indexing"),),
    )

    assert score_case(CallKind.PLAN, value, {"tools": ["search_papers"]}) == 1.0
    assert score_case(CallKind.PLAN, value, {"tools": ["get_paper"]}) == 0.0


def test_synthesize_score_rejects_unknown_handle() -> None:
    value = FitnessAnswer(
        answer="Luma reduced errors.",
        claims=(FitnessClaim(text="Luma reduced errors.", handles=["E99"]),),
    )

    assert score_case(CallKind.SYNTHESIZE, value, {"handles": ["E1"]}) == 0.0


def test_judge_score_requires_exact_labels() -> None:
    expected = {"labels": ["supported", "unsupported"]}

    assert (
        score_case(
            CallKind.JUDGE,
            FitnessJudgement(labels=["supported", "unsupported"]),
            expected,
        )
        == 1.0
    )
    assert (
        score_case(
            CallKind.JUDGE,
            FitnessJudgement(labels=["supported", "partial"]),
            expected,
        )
        == 0.0
    )


def test_invalid_output_scores_zero() -> None:
    assert score_case(CallKind.PLAN, None, {"tools": ["search_papers"]}) == 0.0


def test_cases_file_has_required_coverage() -> None:
    path = (
        Path(__file__).resolve().parents[1]
        / "benchmarks/phase3/generator-fitness-cases-v1.json"
    )
    cases = load_cases(path)

    assert len(cases) == 15
    validate_case_coverage(cases)


def test_thinking_calls_get_the_thinking_allowance() -> None:
    for kind, limit in OUTPUT_TOKEN_LIMITS.items():
        assert output_token_limit(kind, think=False) == limit
        assert output_token_limit(kind, think=True) == limit + THINKING_TOKEN_ALLOWANCE


def test_plan_messages_list_every_tool_and_other_kinds_are_unchanged() -> None:
    messages = (
        {"role": "system", "content": "Choose tools."},
        {"role": "user", "content": "Find papers."},
    )
    plan = FitnessCase("plan-x", CallKind.PLAN, messages, {"tools": ["search_papers"]})
    judge = FitnessCase("judge-x", CallKind.JUDGE, messages, {"labels": []})

    system = case_messages(plan)[0]["content"]
    assert system.startswith("Choose tools.")
    for name in ACTION_TOOL_NAMES:
        assert f"{name}: {TOOL_DESCRIPTIONS[name]}" in system
    assert case_messages(plan)[1] == messages[1]
    assert case_messages(judge) == messages


def test_native_tools_use_the_shared_descriptions() -> None:
    tools = _native_tools()

    assert [tool["function"]["name"] for tool in tools] == list(ACTION_TOOL_NAMES)  # type: ignore[index]
    for tool in tools:
        function = tool["function"]
        assert function["description"] == TOOL_DESCRIPTIONS[function["name"]]  # type: ignore[index]


def test_fitness_claim_schema_constrains_handle_format() -> None:
    import pytest
    from pydantic import ValidationError

    assert FitnessClaim(text="x", handles=["E1", "E12"]).handles == ["E1", "E12"]
    with pytest.raises(ValidationError):
        FitnessClaim(text="x", handles=["Evidence E2"])
    schema = FitnessAnswer.model_json_schema()
    assert "^E[1-9][0-9]*$" in json.dumps(schema)
