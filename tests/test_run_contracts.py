"""Tests for Phase 3 research run contracts."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from research_platform.llm.types import CallKind, ModelIdentity
from research_platform.runs.contracts import (
    AnswerOutcome,
    ClaimResult,
    EvidenceCitation,
    FailureCategory,
    ResearchFilters,
    ResearchMode,
    ResearchRequest,
    ResearchRunView,
    RunBudgets,
    RunProvenance,
    RunStatus,
    RunUsage,
    SupportLabel,
    configuration_id,
)


def test_budgets_defaults_match_adr() -> None:
    assert RunBudgets().model_dump() == {
        "max_plan_rounds": 3,
        "max_actions_per_plan": 4,
        "max_tool_calls": 12,
        "max_citation_depth": 2,
        "max_evidence_passages": 40,
        "max_synthesis_tokens": 8000,
        "max_model_retries": 2,
        "max_active_seconds": 1800.0,
        "max_resumes": 2,
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("max_plan_rounds", 0),
        ("max_actions_per_plan", 11),
        ("max_tool_calls", 51),
        ("max_citation_depth", 4),
        ("max_evidence_passages", 0),
        ("max_synthesis_tokens", 499),
        ("max_model_retries", 6),
        ("max_active_seconds", 0),
        ("max_resumes", 6),
    ],
)
def test_budgets_reject_out_of_range(field: str, value: int | float) -> None:
    with pytest.raises(ValidationError):
        RunBudgets(**{field: value})


def test_request_requires_mode() -> None:
    with pytest.raises(ValidationError):
        ResearchRequest(question="Explain retrieval")


@pytest.mark.parametrize("question", ["", "  ", "ab", "x" * 2001])
def test_request_strips_and_bounds_question(question: str) -> None:
    with pytest.raises(ValidationError):
        ResearchRequest(question=question, mode=ResearchMode.QUICK)


def test_request_strips_valid_question() -> None:
    request = ResearchRequest(question="  Explain retrieval  ", mode="quick")
    assert request.question == "Explain retrieval"


def test_filters_reject_inverted_years() -> None:
    with pytest.raises(ValidationError):
        ResearchFilters(year_from=2025, year_to=2024)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("handle", "E0"),
        ("handle", "e1"),
        ("claim_id", "claim-0"),
        ("claim_id", "claim-x"),
    ],
)
def test_claim_requires_evidence_and_patterns(field: str, value: str) -> None:
    citation = EvidenceCitation(handle="E1", chunk_id="chunk-1", paper_id="W1")
    claim_data = {
        "claim_id": "claim-1",
        "text": "A claim.",
        "evidence": (citation,),
        "support": SupportLabel.SUPPORTED,
    }
    if field == "handle":
        claim_data["evidence"] = (
            {"handle": value, "chunk_id": "chunk-1", "paper_id": "W1"},
        )
    else:
        claim_data[field] = value
    with pytest.raises(ValidationError):
        ClaimResult(**claim_data)

    with pytest.raises(ValidationError):
        ClaimResult(
            claim_id="claim-1", text="No citation.", evidence=(), support="partial"
        )


def _run_view(**overrides: object) -> ResearchRunView:
    values: dict[str, object] = {
        "run_id": uuid4(),
        "status": RunStatus.QUEUED,
        "mode": ResearchMode.QUICK,
        "question": "Explain retrieval",
        "created_at": datetime.now(UTC),
    }
    values.update(overrides)
    return ResearchRunView(**values)


def test_run_view_status_invariants() -> None:
    assert _run_view(status=RunStatus.QUEUED)
    assert _run_view(status=RunStatus.RUNNING)
    assert _run_view(
        status=RunStatus.COMPLETED,
        answer_outcome=AnswerOutcome.ANSWERED,
    )
    assert _run_view(
        status=RunStatus.FAILED,
        failure_category=FailureCategory.INTERNAL,
    )

    for status in (RunStatus.QUEUED, RunStatus.RUNNING):
        with pytest.raises(ValidationError):
            _run_view(status=status, answer_outcome=AnswerOutcome.ANSWERED)
        with pytest.raises(ValidationError):
            _run_view(
                status=status,
                claims=(
                    ClaimResult(
                        claim_id="claim-1",
                        text="A claim.",
                        evidence=(
                            EvidenceCitation(
                                handle="E1", chunk_id="chunk-1", paper_id="W1"
                            ),
                        ),
                        support=SupportLabel.SUPPORTED,
                    ),
                ),
            )

    with pytest.raises(ValidationError):
        _run_view(status=RunStatus.COMPLETED)
    with pytest.raises(ValidationError):
        _run_view(
            status=RunStatus.COMPLETED,
            answer_outcome=AnswerOutcome.ANSWERED,
            failure_category=FailureCategory.INTERNAL,
        )
    with pytest.raises(ValidationError):
        _run_view(status=RunStatus.FAILED)
    with pytest.raises(ValidationError):
        _run_view(
            status=RunStatus.FAILED,
            failure_category=FailureCategory.INTERNAL,
            answer_outcome=AnswerOutcome.ANSWERED,
        )


def test_configuration_id_is_order_independent_and_prefixed() -> None:
    assert configuration_id({"b": 2, "a": 1}) == configuration_id({"a": 1, "b": 2})
    assert configuration_id({"a": 1}).startswith("sha256:")


def test_models_are_frozen_and_forbid_extra() -> None:
    budgets = RunBudgets()
    with pytest.raises(ValidationError):
        RunBudgets(unexpected=True)
    with pytest.raises(ValidationError):
        budgets.max_tool_calls = 1  # type: ignore[misc]

    model = ModelIdentity(name="model", runtime="scripted", context_tokens=512)
    with pytest.raises(ValidationError):
        ModelIdentity(name="model", runtime="scripted", context_tokens=512, extra=1)
    with pytest.raises(ValidationError):
        model.name = "changed"  # type: ignore[misc]


def test_provenance_validates_configuration_identifier() -> None:
    with pytest.raises(ValidationError):
        RunProvenance(
            snapshot_id=uuid4(),
            retrieval_profile_id="profile",
            configuration_id="invalid",
            code_revision="revision",
            model=ModelIdentity(name="model", runtime="scripted", context_tokens=512),
            thinking={CallKind.PLAN: False},
            prompt_versions={},
            budgets=RunBudgets(),
            trace_id="trace",
        )


def test_usage_defaults_are_independent() -> None:
    assert RunUsage().tool_calls == 0
