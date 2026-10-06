"""Validation of text-free model call records."""

from __future__ import annotations

import math

import pytest

from research_platform.llm.types import CallKind
from research_platform.runs.llm_records import LLMCallRecord


def _record(**overrides: object) -> LLMCallRecord:
    values: dict[str, object] = {
        "kind": CallKind.SYNTHESIZE,
        "status": "succeeded",
        "model_name": "scripted",
        "think": True,
        "attempts": 1,
        "duration_ms": 12.5,
    }
    values.update(overrides)
    return LLMCallRecord(**values)  # type: ignore[arg-type]


def test_valid_succeeded_and_failed_records() -> None:
    assert _record().status == "succeeded"
    failed = _record(status="failed", error_type="LLMTimeout", attempts=0)
    assert failed.error_type == "LLMTimeout"


@pytest.mark.parametrize(
    "overrides",
    [
        {"status": "unknown"},
        {"status": "failed"},
        {"error_type": "LLMTimeout"},
        {"attempts": -1},
        {"duration_ms": -1.0},
        {"duration_ms": math.inf},
        {"duration_ms": math.nan},
        {"prompt_tokens": -1},
        {"output_tokens": -1},
        {"thinking_chars": -1},
        {"model_name": "  "},
    ],
)
def test_invalid_records_rejected(overrides: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        _record(**overrides)
