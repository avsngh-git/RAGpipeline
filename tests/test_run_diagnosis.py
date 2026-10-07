"""Deterministic run diagnosis coverage."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from research_platform.evaluation.phase3_regression import (
    load_cases,
    load_corpus,
    run_case_detailed,
)
from research_platform.llm.types import CallKind
from research_platform.runs.contracts import (
    AnswerOutcome,
    DraftClaimOutcome,
    FailureCategory,
    ResearchMode,
    ResearchRunView,
    RunStatus,
    SynthesisSummary,
)
from research_platform.runs.diagnosis import (
    DiagnosisInputs,
    DiagnosisStage,
    diagnose,
    load_diagnosis_inputs,
    render_markdown,
)
from research_platform.runs.llm_records import LLMCallRecord, StoredLLMCall
from research_platform.runs.repository import ToolCallRecord

_CASES_PATH = Path("benchmarks/phase3/regression-cases-v2.json")
_EXPECTED = {
    "route-01-search-path": DiagnosisStage.NONE,
    "failure-01-model-unavailable": DiagnosisStage.MODEL,
    "failure-02-invalid-synthesis": DiagnosisStage.GENERATION,
    "failure-03-retrieval-error": DiagnosisStage.RETRIEVAL,
    "budget-03-active-timeout": DiagnosisStage.BUDGET,
    "budget-04-recursion": DiagnosisStage.BUDGET,
    "verify-01-quote-not-in-passage": DiagnosisStage.VERIFICATION,
    "verify-02-invented-number": DiagnosisStage.VERIFICATION,
    "fabricated-01-unknown": DiagnosisStage.VERIFICATION,
}


@pytest.mark.parametrize(("case_id", "expected_stage"), _EXPECTED.items())
def test_stages_for_regression_cases(
    case_id: str, expected_stage: DiagnosisStage
) -> None:
    async def exercise() -> DiagnosisStage:
        cases = {case.case_id: case for case in load_cases(_CASES_PATH)}
        case_run = await run_case_detailed(cases[case_id], load_corpus(_CASES_PATH))
        inputs = await load_diagnosis_inputs(case_run.store, case_run.run_id)
        diagnosis = diagnose(inputs)
        if diagnosis.stage != expected_stage:
            pytest.fail(
                f"{case_id}: expected {expected_stage.value}; "
                f"observed {diagnosis.model_dump_json()}"
            )
        return diagnosis.stage

    actual = asyncio.run(exercise())
    if actual != expected_stage:
        pytest.fail(f"{case_id}: expected {expected_stage}, got {actual}")


def _view(
    *,
    status: RunStatus = RunStatus.COMPLETED,
    outcome: AnswerOutcome = AnswerOutcome.INSUFFICIENT_EVIDENCE,
    failure: FailureCategory | None = None,
    mode: ResearchMode = ResearchMode.QUICK,
) -> ResearchRunView:
    return ResearchRunView(
        run_id=uuid4(),
        status=status,
        mode=mode,
        question="synthetic query",
        answer_outcome=outcome if status is RunStatus.COMPLETED else None,
        failure_category=failure,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def _inputs(
    *,
    view: ResearchRunView | None = None,
    evidence: tuple[str, ...] = ("E1", "E2", "E3"),
    synthesis: SynthesisSummary | None = None,
    drafts: tuple[DraftClaimOutcome, ...] = (),
    tools: tuple[ToolCallRecord, ...] = (),
    llm: tuple[StoredLLMCall, ...] = (),
) -> DiagnosisInputs:
    return DiagnosisInputs(
        view=view or _view(),
        tool_calls=tools,
        llm_calls=llm,
        drafts=drafts,
        synthesis=synthesis,
        evidence_handles=evidence,
    )


def test_declared_insufficient_is_evidence_stage() -> None:
    summary = SynthesisSummary(
        model_declared_insufficient=True,
        packed_handles=("E1",),
        omitted_handles=("E2",),
    )
    assert diagnose(_inputs(synthesis=summary)).stage is DiagnosisStage.EVIDENCE


def test_no_evidence_is_retrieval_stage() -> None:
    assert diagnose(_inputs(evidence=())).stage is DiagnosisStage.RETRIEVAL


def test_timeout_with_llm_timeout_is_model_stage() -> None:
    view = _view(
        status=RunStatus.FAILED,
        failure=FailureCategory.TIMEOUT,
    )
    record = LLMCallRecord(
        kind=CallKind.PLAN,
        status="failed",
        model_name="scripted",
        think=False,
        attempts=1,
        duration_ms=1,
        error_type="LLMTimeout",
    )
    call = StoredLLMCall(ordinal=1, record=record)
    assert diagnose(_inputs(view=view, llm=(call,))).stage is DiagnosisStage.MODEL


def test_planner_never_discovered_finding() -> None:
    view = _view(mode=ResearchMode.DEEP_RESEARCH)
    tools = tuple(
        ToolCallRecord(
            ordinal=index,
            tool_name=name,
            arguments={},
            status="succeeded",
            result_summary={},
            duration_ms=1,
        )
        for index, name in enumerate(("search_papers", "search_evidence"), 1)
    )
    result = diagnose(_inputs(view=view, tools=tools))
    finding = next(
        item for item in result.findings if item.code == "planner_never_discovered"
    )
    assert finding.detail == "search_evidence, search_papers"


def test_ingestion_wait_cap_finding() -> None:
    tool = ToolCallRecord(
        ordinal=1,
        tool_name="ingestion_wait",
        arguments={},
        status="failed",
        result_summary={},
        duration_ms=1,
        error_category="ingestion_wait_cap",
    )
    result = diagnose(_inputs(tools=(tool,)))
    assert any(item.code == "ingestion_wait_cap" for item in result.findings)


def test_markdown_has_no_question_text() -> None:
    async def exercise() -> tuple[str, str]:
        case = next(
            case
            for case in load_cases(_CASES_PATH)
            if case.case_id == "route-01-search-path"
        )
        case = replace(
            case,
            request=case.request.model_copy(update={"question": "zq7731 marker"}),
        )
        case_run = await run_case_detailed(case, load_corpus(_CASES_PATH))
        inputs = await load_diagnosis_inputs(case_run.store, case_run.run_id)
        diagnosis = diagnose(inputs)
        return render_markdown(diagnosis), diagnosis.model_dump_json()

    markdown, serialized = asyncio.run(exercise())
    assert "zq7731" not in markdown
    assert "zq7731" not in serialized
