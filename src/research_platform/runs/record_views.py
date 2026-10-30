"""Public response views for a research run's execution record."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from research_platform.runs.contracts import DraftClaimOutcome, SynthesisSummary
from research_platform.runs.diagnosis import RunDiagnosis
from research_platform.runs.llm_records import StoredLLMCall
from research_platform.runs.repository import ToolCallRecord


class ToolCallView(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    ordinal: int
    tool_name: str
    arguments: dict[str, object]
    status: Literal["succeeded", "failed", "rejected", "cached"]
    result_summary: dict[str, object]
    duration_ms: float
    error_category: str | None = None
    recorded_at: datetime | None = None


class ModelCallView(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    ordinal: int
    kind: str
    status: Literal["succeeded", "failed"]
    model_name: str
    think: bool
    attempts: int
    prompt_version: str | None = None
    prompt_tokens: int | None = None
    output_tokens: int | None = None
    thinking_chars: int | None = None
    duration_ms: float
    error_type: str | None = None
    recorded_at: datetime | None = None
    text_recorded: bool


class RunRecordView(BaseModel):
    """What a run did, for its owner: the run record of the glossary."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    run_id: UUID
    tool_calls: tuple[ToolCallView, ...]
    model_calls: tuple[ModelCallView, ...]
    drafted_claims: tuple[DraftClaimOutcome, ...]
    synthesis: SynthesisSummary | None
    diagnosis: RunDiagnosis


ModelCallTextState = Literal["available", "not_recorded", "withheld"]


class ModelMessageView(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    role: Literal["system", "user", "assistant"]
    content: str


class ModelCallTextView(BaseModel):
    """The stored text of one model call, or why it is not shown."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    run_id: UUID
    ordinal: int
    kind: str
    state: ModelCallTextState
    messages: tuple[ModelMessageView, ...] = ()
    thinking: str | None = None
    output: str | None = None
    error_preview: str | None = None


def tool_call_view(record: ToolCallRecord) -> ToolCallView:
    """Map a stored tool call to its text-free API view."""
    return ToolCallView(
        ordinal=record.ordinal,
        tool_name=record.tool_name,
        arguments=dict(record.arguments),
        status=record.status,
        result_summary=dict(record.result_summary),
        duration_ms=record.duration_ms,
        error_category=record.error_category,
        recorded_at=record.recorded_at,
    )


def model_call_view(call: StoredLLMCall, *, text_recorded: bool) -> ModelCallView:
    """Map stored model metadata without exposing payload text."""
    record = call.record
    return ModelCallView(
        ordinal=call.ordinal,
        kind=record.kind.value,
        status=record.status,
        model_name=record.model_name,
        think=record.think,
        attempts=record.attempts,
        prompt_version=record.prompt_version,
        prompt_tokens=record.prompt_tokens,
        output_tokens=record.output_tokens,
        thinking_chars=record.thinking_chars,
        duration_ms=record.duration_ms,
        error_type=record.error_type,
        recorded_at=call.recorded_at,
        text_recorded=text_recorded,
    )
