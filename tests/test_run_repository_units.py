"""Pure serialization helpers for the run repository."""

from uuid import uuid4

from research_platform.llm.types import CallKind, ModelIdentity
from research_platform.runs.contracts import (
    ResearchFilters,
    ResearchMode,
    ResearchRequest,
    RunBudgets,
    RunProvenance,
    RunUsage,
)
from research_platform.runs.repository import (
    _provenance_from_json,
    _provenance_json,
    _request_from_json,
    _request_json,
    _truncate_message,
    _usage_from_json,
    _usage_json,
)


def test_request_json_round_trip() -> None:
    request = ResearchRequest(
        question="How does hybrid retrieval perform?",
        mode=ResearchMode.DEEP_RESEARCH,
        snapshot_id=uuid4(),
        filters=ResearchFilters(year_from=2021, year_to=2025),
    )

    assert _request_from_json(_request_json(request)) == request


def test_usage_json_round_trip() -> None:
    usage = RunUsage(
        plan_rounds=2,
        tool_calls=4,
        model_calls=7,
        active_seconds=28.5,
        resumes=1,
        rejected_claims=2,
        unsupported_claims=1,
    )

    assert _usage_from_json(_usage_json(usage)) == usage


def test_provenance_json_round_trip() -> None:
    provenance = RunProvenance(
        snapshot_id=uuid4(),
        retrieval_profile_id="profile-v10",
        configuration_id=f"sha256:{'a' * 64}",
        code_revision="test-revision",
        model=ModelIdentity(name="qwen", runtime="ollama", context_tokens=8192),
        thinking={CallKind.PLAN: False, CallKind.SYNTHESIZE: True},
        prompt_versions={"system": "v1"},
        budgets=RunBudgets(max_tool_calls=8),
        trace_id="trace-1",
    )

    assert _provenance_from_json(_provenance_json(provenance)) == provenance


def test_truncate_message_caps_error_at_500_characters() -> None:
    message = "x" * 700

    assert _truncate_message(message) == "x" * 500
