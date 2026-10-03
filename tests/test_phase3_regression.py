"""Whole-run Phase 3 regressions against a synthetic corpus and scripted model."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from research_platform.evaluation.phase3_regression import (
    RegressionCase,
    load_cases,
    load_corpus,
    run_case,
)
from research_platform.runs.contracts import FailureCategory, RunStatus

_CASE_PATH = (
    Path(__file__).parents[1] / "benchmarks" / "phase3" / "regression-cases-v1.json"
)
_CASES = load_cases(_CASE_PATH)
_CORPUS = load_corpus(_CASE_PATH)


@pytest.mark.anyio
@pytest.mark.parametrize("case", _CASES, ids=lambda case: case.case_id)
async def test_case(case: RegressionCase) -> None:
    result = await run_case(case, _CORPUS)

    assert result.passed, "; ".join(result.mismatches)


def test_case_file_meets_category_minimums() -> None:
    counts = Counter(case.category for case in _CASES)

    assert len(_CASES) >= 28
    assert counts == {
        "tool_routing": 10,
        "fabricated_handle": 4,
        "budget": 4,
        "prompt_injection": 5,
        "resume": 2,
        "failure_category": 3,
    }


def test_every_failure_category_case_has_category() -> None:
    failed_categories = {
        "model_unavailable",
        "invalid_model_output",
        "budget_exhausted",
        "timeout",
        "retrieval_error",
        "resume_exhausted",
        "configuration_changed",
        "internal",
    }
    for case in _CASES:
        expected = case.expect
        if expected.get("status") == RunStatus.FAILED.value:
            assert expected.get("failure_category") in failed_categories
        if case.category == "failure_category":
            assert expected.get("failure_category") in {
                FailureCategory.MODEL_UNAVAILABLE.value,
                FailureCategory.INVALID_MODEL_OUTPUT.value,
                FailureCategory.RETRIEVAL_ERROR.value,
            }
