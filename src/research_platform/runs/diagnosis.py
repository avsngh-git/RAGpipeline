"""Deterministic, text-free diagnosis of persisted research runs."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from research_platform.observability.span_export import read_run_spans
from research_platform.runs.contracts import (
    AnswerOutcome,
    ClaimVerdict,
    DraftClaimOutcome,
    FailureCategory,
    ResearchMode,
    ResearchRunView,
    RunStatus,
    SynthesisSummary,
)
from research_platform.runs.llm_records import StoredLLMCall
from research_platform.runs.repository import ToolCallRecord
from research_platform.runs.store import RunStore


class DiagnosisStage(StrEnum):
    """Where a run failed or fell short."""

    NONE = "none"
    IN_PROGRESS = "in_progress"
    MODEL = "model"
    PLANNING = "planning"
    RETRIEVAL = "retrieval"
    EVIDENCE = "evidence"
    GENERATION = "generation"
    VERIFICATION = "verification"
    BUDGET = "budget"
    INGESTION = "ingestion"
    INFRASTRUCTURE = "infrastructure"


class Finding(BaseModel):
    """One observation; detail holds identifiers, counts or codes, never text."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    code: str
    detail: str


class LLMCallSummary(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    ordinal: int
    kind: str
    status: str
    attempts: int
    duration_ms: float
    prompt_tokens: int | None
    output_tokens: int | None
    error_type: str | None


class SpanTiming(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    name: str
    duration_ms: float


class RunDiagnosis(BaseModel):
    """The deterministic explanation of one run."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    run_id: UUID
    status: RunStatus
    mode: ResearchMode
    answer_outcome: AnswerOutcome | None
    failure_category: FailureCategory | None
    stage: DiagnosisStage
    findings: tuple[Finding, ...]
    configuration_id: str | None
    trace_id: str | None
    tool_path: tuple[str, ...]
    llm_calls: tuple[LLMCallSummary, ...]
    draft_verdicts: dict[str, int]
    evidence_count: int
    slowest_spans: tuple[SpanTiming, ...] = ()


@dataclass(frozen=True)
class DiagnosisInputs:
    view: ResearchRunView
    tool_calls: tuple[ToolCallRecord, ...]
    llm_calls: tuple[StoredLLMCall, ...]
    drafts: tuple[DraftClaimOutcome, ...]
    synthesis: SynthesisSummary | None
    evidence_handles: tuple[str, ...]
    spans: tuple[Mapping[str, object], ...] = ()


async def load_diagnosis_inputs(
    store: RunStore, run_id: UUID, *, spans_path: Path | None = None
) -> DiagnosisInputs:
    """Load only text-free run records and optional spans for diagnosis."""
    view = await store.get_run_view(run_id)
    tool_calls = await store.list_tool_calls(run_id)
    llm_calls = await store.list_llm_calls(run_id, include_payloads=False)
    drafts = await store.list_draft_claims(run_id)
    synthesis = await store.get_synthesis_summary(run_id)
    evidence_handles = tuple(sorted(await store.load_evidence(run_id)))
    spans = (
        tuple(read_run_spans(spans_path, run_id=str(run_id)))
        if spans_path is not None
        else ()
    )
    return DiagnosisInputs(
        view, tool_calls, llm_calls, drafts, synthesis, evidence_handles, spans
    )


def diagnose(inputs: DiagnosisInputs) -> RunDiagnosis:
    """Apply the card's deterministic stage rules and collect safe findings."""
    view = inputs.view
    verdicts = Counter(draft.verdict.value for draft in inputs.drafts)
    stage = _stage(inputs)
    findings: list[Finding] = []
    succeeded = sum(call.status == "succeeded" for call in inputs.tool_calls)
    if not inputs.evidence_handles:
        findings.append(
            Finding(
                code="no_evidence_collected",
                detail=f"{len(inputs.tool_calls)} tool calls, {succeeded} succeeded",
            )
        )
    synthesis = inputs.synthesis
    if synthesis is not None and synthesis.model_declared_insufficient:
        findings.append(
            Finding(
                code="model_declared_insufficient",
                detail=(
                    f"{len(inputs.evidence_handles)} passages collected, "
                    f"{len(synthesis.packed_handles)} shown, "
                    f"{len(synthesis.omitted_handles)} omitted by the token cap"
                ),
            )
        )
    if any(draft.verdict is not ClaimVerdict.KEPT for draft in inputs.drafts):
        findings.append(
            Finding(
                code="drafts_rejected",
                detail=" ".join(f"{k}={v}" for k, v in sorted(verdicts.items())),
            )
        )
    failed_checks = Counter(
        check for draft in inputs.drafts for check in draft.failed_checks
    )
    findings.extend(
        Finding(code=f"failed_check:{name}", detail=str(count))
        for name, count in sorted(failed_checks.items())
    )
    if any(
        call.tool_name == "ingestion_wait"
        and call.error_category == "ingestion_wait_cap"
        for call in inputs.tool_calls
    ):
        findings.append(
            Finding(
                code="ingestion_wait_cap",
                detail="answered from the published generation",
            )
        )
    names = {call.tool_name for call in inputs.tool_calls}
    if (
        view.mode is ResearchMode.DEEP_RESEARCH
        and view.answer_outcome is not AnswerOutcome.ANSWERED
        and "discover_papers" not in names
    ):
        findings.append(
            Finding(
                code="planner_never_discovered",
                detail=", ".join(sorted(names)),
            )
        )
    rejected = Counter(
        call.error_category or "unknown"
        for call in inputs.tool_calls
        if call.status == "rejected"
    )
    if rejected:
        findings.append(
            Finding(
                code="tool_rejections",
                detail=" ".join(f"{k}={v}" for k, v in sorted(rejected.items())),
            )
        )
    repairs = sum(call.record.attempts - 1 for call in inputs.llm_calls)
    if repairs > 0:
        findings.append(Finding(code="llm_repairs", detail=str(repairs)))
    if synthesis is not None and synthesis.omitted_handles:
        findings.append(
            Finding(code="omitted_evidence", detail=str(len(synthesis.omitted_handles)))
        )
    return RunDiagnosis(
        run_id=view.run_id,
        status=view.status,
        mode=view.mode,
        answer_outcome=view.answer_outcome,
        failure_category=view.failure_category,
        stage=stage,
        findings=tuple(findings),
        configuration_id=view.provenance.configuration_id if view.provenance else None,
        trace_id=view.provenance.trace_id if view.provenance else None,
        tool_path=tuple(
            f"{call.tool_name}:{call.status}" for call in inputs.tool_calls
        ),
        llm_calls=tuple(
            LLMCallSummary(
                ordinal=call.ordinal,
                kind=call.record.kind.value,
                status=call.record.status,
                attempts=call.record.attempts,
                duration_ms=call.record.duration_ms,
                prompt_tokens=call.record.prompt_tokens,
                output_tokens=call.record.output_tokens,
                error_type=call.record.error_type,
            )
            for call in inputs.llm_calls
        ),
        draft_verdicts=dict(verdicts),
        evidence_count=len(inputs.evidence_handles),
        slowest_spans=_slowest_spans(inputs.spans),
    )


def _stage(inputs: DiagnosisInputs) -> DiagnosisStage:
    view = inputs.view
    if view.status in (
        RunStatus.QUEUED,
        RunStatus.RUNNING,
        RunStatus.WAITING_FOR_INGESTION,
    ):
        return DiagnosisStage.IN_PROGRESS
    if view.status is RunStatus.FAILED:
        category = view.failure_category
        if category is FailureCategory.MODEL_UNAVAILABLE:
            return DiagnosisStage.MODEL
        if category is FailureCategory.TIMEOUT:
            last_call = inputs.llm_calls[-1] if inputs.llm_calls else None
            if (
                last_call is not None
                and last_call.record.status == "failed"
                and last_call.record.error_type == "LLMTimeout"
            ):
                return DiagnosisStage.MODEL
            return DiagnosisStage.BUDGET
        if category is FailureCategory.INVALID_MODEL_OUTPUT:
            failed = [
                call for call in inputs.llm_calls if call.record.status == "failed"
            ]
            if not failed:
                return DiagnosisStage.GENERATION
            kind = failed[-1].record.kind.value
            if kind == "synthesize":
                return DiagnosisStage.GENERATION
            if kind in ("plan", "evaluate"):
                return DiagnosisStage.PLANNING
            return DiagnosisStage.GENERATION
        return {
            FailureCategory.BUDGET_EXHAUSTED: DiagnosisStage.BUDGET,
            FailureCategory.RETRIEVAL_ERROR: DiagnosisStage.RETRIEVAL,
            FailureCategory.RESUME_EXHAUSTED: DiagnosisStage.INFRASTRUCTURE,
            FailureCategory.CONFIGURATION_CHANGED: DiagnosisStage.INFRASTRUCTURE,
            FailureCategory.INTERNAL: DiagnosisStage.INFRASTRUCTURE,
        }[cast(FailureCategory, category)]
    if view.status is RunStatus.COMPLETED:
        if view.answer_outcome is AnswerOutcome.ANSWERED:
            return DiagnosisStage.NONE
        if not inputs.evidence_handles:
            return DiagnosisStage.RETRIEVAL
        if (
            inputs.synthesis is not None
            and inputs.synthesis.model_declared_insufficient
        ):
            return DiagnosisStage.EVIDENCE
        if any(draft.verdict is not ClaimVerdict.KEPT for draft in inputs.drafts):
            return DiagnosisStage.VERIFICATION
        return DiagnosisStage.GENERATION
    return DiagnosisStage.NONE


def _slowest_spans(spans: tuple[Mapping[str, object], ...]) -> tuple[SpanTiming, ...]:
    timings: list[SpanTiming] = []
    for span in spans:
        name = span.get("name")
        duration = span.get("duration_ms")
        if name == "research_run" or not isinstance(name, str):
            continue
        if isinstance(duration, bool) or not isinstance(duration, (int, float)):
            continue
        timings.append(SpanTiming(name=name, duration_ms=float(duration)))
    timings.sort(key=lambda span: span.duration_ms, reverse=True)
    return tuple(timings[:5])


def render_markdown(diagnosis: RunDiagnosis) -> str:
    """Render a text-free summary of a run diagnosis."""
    d = diagnosis
    lines = [
        f"# Run {d.run_id}",
        f"Status: {d.status.value} · Mode: {d.mode.value} · Outcome: {d.answer_outcome.value if d.answer_outcome else '-'} · Failure: {d.failure_category.value if d.failure_category else '-'}",
        f"Stage: **{d.stage.value}**",
        f"Configuration: {d.configuration_id or '-'} · Trace: {d.trace_id or '-'}",
        "",
        "## Findings",
    ]
    lines.extend(f"- {finding.code}: {finding.detail}" for finding in d.findings)
    lines.extend(["", "## Tool path"])
    lines.extend(f"{index}. {tool}" for index, tool in enumerate(d.tool_path, start=1))
    lines.extend(
        [
            "",
            "## Model calls",
            "| # | kind | status | attempts | ms | prompt tokens | output tokens | error |",
        ]
    )
    lines.extend(
        f"| {call.ordinal} | {call.kind} | {call.status} | {call.attempts} | {call.duration_ms:g} | {call.prompt_tokens if call.prompt_tokens is not None else '-'} | {call.output_tokens if call.output_tokens is not None else '-'} | {call.error_type or '-'} |"
        for call in d.llm_calls
    )
    lines.extend(["", "## Drafted claims"])
    lines.extend(
        f"{verdict}: {count}" for verdict, count in sorted(d.draft_verdicts.items())
    )
    if d.slowest_spans:
        lines.extend(["", "## Slowest spans", "| span | ms |"])
        lines.extend(
            f"| {span.name} | {span.duration_ms:g} |" for span in d.slowest_spans
        )
    return "\n".join(lines) + "\n"
