"""Text-free model call records and their optional payloads (ADR-0026)."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal

from research_platform.llm.contracts import ChatMessage
from research_platform.llm.types import CallKind

LLMCallStatus = Literal["succeeded", "failed"]


@dataclass(frozen=True)
class LLMCallRecord:
    """Text-free description of one model call made during a run."""

    kind: CallKind
    status: LLMCallStatus
    model_name: str
    think: bool
    attempts: int
    duration_ms: float
    options: Mapping[str, object] = field(default_factory=dict)
    prompt_version: str | None = None
    prompt_fingerprint: str | None = None
    prompt_tokens: int | None = None
    output_tokens: int | None = None
    thinking_chars: int | None = None
    error_type: str | None = None
    trace_id: str | None = None
    span_id: str | None = None

    def __post_init__(self) -> None:
        if self.status not in ("succeeded", "failed"):
            raise ValueError("status must be succeeded or failed")
        if (self.status == "failed") != (self.error_type is not None):
            raise ValueError("failed calls, and only failed calls, have an error_type")
        if not self.model_name.strip():
            raise ValueError("model_name must be non-empty")
        if self.attempts < 0:
            raise ValueError("attempts must be non-negative")
        if not math.isfinite(self.duration_ms) or self.duration_ms < 0:
            raise ValueError("duration_ms must be finite and non-negative")
        for name in ("prompt_tokens", "output_tokens", "thinking_chars"):
            value = getattr(self, name)
            if value is not None and value < 0:
                raise ValueError(f"{name} must be non-negative")


@dataclass(frozen=True)
class LLMCallPayload:
    """The messages sent and the text returned; stored only at trace content full."""

    messages: tuple[ChatMessage, ...]
    output: str | None = None
    thinking: str | None = None
    error_preview: str | None = None


@dataclass(frozen=True)
class StoredLLMCall:
    """A persisted model call with its ordinal and, when requested, its payload."""

    ordinal: int
    record: LLMCallRecord
    payload: LLMCallPayload | None = None
