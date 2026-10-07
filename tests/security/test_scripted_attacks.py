"""Scripted security cases over a synthetic adversarial corpus."""

from __future__ import annotations

from pathlib import Path

import pytest

from research_platform.evaluation.phase3_regression import (
    RegressionCase,
    load_cases,
    load_corpus,
    run_case,
)

_CASE_PATH = (
    Path(__file__).parents[2] / "benchmarks" / "phase4" / "security-cases-v1.json"
)
_CASES = load_cases(_CASE_PATH)
_CORPUS = load_corpus(_CASE_PATH)


@pytest.mark.anyio
@pytest.mark.parametrize("case", _CASES, ids=lambda case: case.case_id)
async def test_case(case: RegressionCase, monkeypatch: pytest.MonkeyPatch) -> None:
    if case.case_id == "sec-05-secret-exfiltration":
        monkeypatch.setenv("RESEARCH_PLATFORM_OPENALEX_API_KEY", "canary-secret-7731")

    result = await run_case(case, _CORPUS)

    assert result.passed, "; ".join(result.mismatches)


def test_every_case_has_a_safety_expectation() -> None:
    safety_keys = {
        "answer_excludes",
        "prompts_exclude",
        "evidence_papers_exclude",
        "tools_exclude",
        "tool_calls_at_most",
        "plan_rounds_at_most",
        "rejected_claims",
        "failure_category",
    }

    assert all(safety_keys.intersection(case.expect) for case in _CASES)


def test_case_ids_cover_attack_list() -> None:
    assert {case.case_id for case in _CASES} == {
        "sec-01-instruction-override",
        "sec-02-forged-evidence-tag",
        "sec-03-repeated-tool-calls",
        "sec-04-unknown-tool",
        "sec-05-secret-exfiltration",
        "sec-06-filter-escape",
        "sec-07-unknown-handle",
        "sec-08-malformed-handle",
        "sec-09-unbounded-loop",
    }
