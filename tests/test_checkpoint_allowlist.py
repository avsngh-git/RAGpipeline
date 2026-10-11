"""The checkpoint allow-list is exactly the types a research run's state can hold."""

from __future__ import annotations

import enum
import logging
import typing
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from research_platform.agents.state import ResearchState
from research_platform.evaluation.phase3_regression import (
    load_cases,
    load_corpus,
    run_case,
)
from research_platform.runs.checkpointing import _CHECKPOINT_TYPES

_CASES = (
    Path(__file__).parents[1] / "benchmarks" / "phase3" / "regression-cases-v2.json"
)


def _reachable(annotation: Any, seen: set[tuple[str, str]]) -> None:
    if typing.get_origin(annotation) is not None:
        for argument in typing.get_args(annotation):
            _reachable(argument, seen)
        return
    if not isinstance(annotation, type) or not issubclass(
        annotation, (BaseModel, enum.Enum)
    ):
        return
    key = (annotation.__module__, annotation.__qualname__)
    if key in seen:
        return
    seen.add(key)
    if issubclass(annotation, BaseModel):
        for field in annotation.model_fields.values():
            _reachable(field.annotation, seen)


def test_allow_list_matches_the_types_reachable_from_state() -> None:
    reachable: set[tuple[str, str]] = set()
    for annotation in typing.get_type_hints(ResearchState).values():
        _reachable(annotation, reachable)

    assert set(_CHECKPOINT_TYPES) == reachable


@pytest.mark.anyio
async def test_scripted_runs_restore_checkpoints_without_unregistered_types(
    caplog: pytest.LogCaptureFixture,
) -> None:
    cases = {case.case_id: case for case in load_cases(_CASES)}
    corpus = load_corpus(_CASES)
    caplog.set_level(logging.WARNING)

    # resume-02 restores a checkpoint holding the verified answer after a cancel.
    result = await run_case(cases["resume-02-after-answer"], corpus)

    assert result.passed, result.mismatches
    assert "unregistered type" not in caplog.text
