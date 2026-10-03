from __future__ import annotations

import pytest

from research_platform.evaluation.phase3_metrics import (
    Phase3RunMetricsInput,
    aggregate_phase3_metrics,
    categorized_failure_rate,
    completion_rates,
    nearest_rank_percentile,
    spot_check_rate,
    unknown_handle_count,
    unsupported_task_outcomes,
)


def _run(**overrides: object) -> Phase3RunMetricsInput:
    values: dict[str, object] = {
        "task_id": "synthetic-task",
        "mode": "quick",
        "status": "completed",
        "answer_outcome": "answered",
        "failure_category": None,
        "cited_handles": ("E1",),
        "registry_handles": frozenset({"E1"}),
        "cited_paper_ids": frozenset({"paper-a"}),
        "judged_paper_ids": frozenset({"paper-a"}),
        "support_labels": ("supported",),
        "citation_counts": (1,),
        "tool_calls": 2,
        "tool_call_records": 2,
        "plan_rounds": 1,
        "model_calls": 3,
        "active_seconds": 12.0,
        "unsupported": False,
    }
    values.update(overrides)
    return Phase3RunMetricsInput(**values)  # type: ignore[arg-type]


def test_completion_rate_per_mode() -> None:
    runs = (
        _run(task_id="one", mode="quick", status="completed"),
        _run(task_id="two", mode="quick", status="failed"),
        _run(task_id="three", mode="deep_research", status="completed"),
    )

    rates = completion_rates(runs)

    assert rates["quick"] == {"completed": 1, "total": 2, "rate": 0.5}
    assert rates["deep_research"] == {"completed": 1, "total": 1, "rate": 1.0}
    assert rates["overall"] == {"completed": 2, "total": 3, "rate": 2 / 3}


def test_failed_runs_without_category_fail_gate_3() -> None:
    runs = (
        _run(task_id="uncategorized", status="failed", failure_category=None),
        _run(task_id="empty-category", status="failed", failure_category=""),
        _run(task_id="unknown-category", status="failed", failure_category="unknown"),
        _run(task_id="categorized", status="failed", failure_category="timeout"),
    )

    assert categorized_failure_rate(runs) == 0.25
    assert (
        aggregate_phase3_metrics(runs)["gates"]["failure_categories"]["pass"] is False
    )  # type: ignore[index]


def test_unknown_handle_count_uses_independent_registry() -> None:
    run = _run(cited_handles=("E1", "E99", "E99"), registry_handles=frozenset({"E1"}))

    assert unknown_handle_count(run) == 2
    assert aggregate_phase3_metrics((run,))["gates"]["unknown_handles"] == {
        "limit": 0,
        "value": 2,
        "pass": False,
    }  # type: ignore[index]


def test_latency_percentiles_use_nearest_rank() -> None:
    assert nearest_rank_percentile((1, 2, 3, 4, 5), 0.95) == 5
    assert nearest_rank_percentile((), 0.95) is None
    with pytest.raises(ValueError, match="between 0 and 1"):
        nearest_rank_percentile((1, 2), 1.1)


def test_spot_check_skips_tasks_without_judged_papers() -> None:
    runs = (
        _run(task_id="without-judgments", judged_paper_ids=frozenset()),
        _run(
            task_id="judged-no-match",
            judged_paper_ids=frozenset({"paper-b"}),
            cited_paper_ids=frozenset({"paper-a"}),
        ),
        _run(
            task_id="judged-match",
            judged_paper_ids=frozenset({"paper-a"}),
            cited_paper_ids=frozenset({"paper-a"}),
        ),
    )

    assert spot_check_rate(runs) == {"matched": 1, "eligible": 2, "rate": 0.5}
    assert spot_check_rate((runs[0],)) == {"matched": 0, "eligible": 0, "rate": 0.0}


def test_unsupported_task_outcomes() -> None:
    runs = (
        _run(
            task_id="unsupported-expected",
            unsupported=True,
            answer_outcome="insufficient_evidence",
        ),
        _run(
            task_id="unsupported-wrong",
            unsupported=True,
            answer_outcome="answered",
        ),
        _run(task_id="supported-task", unsupported=False),
    )

    assert unsupported_task_outcomes(runs) == {
        "expected_outcome": "insufficient_evidence",
        "expected_count": 1,
        "task_count": 2,
        "expected_rate": 0.5,
        "outcome_counts": {"answered": 1, "insufficient_evidence": 1},
    }


def test_completion_gate_requires_each_mode_and_overall() -> None:
    runs = (
        tuple(
            _run(task_id=f"quick-{index}", mode="quick", status="completed")
            for index in range(9)
        )
        + (_run(task_id="quick-fail", mode="quick", status="failed"),)
        + tuple(
            _run(task_id=f"deep-{index}", mode="deep_research", status="failed")
            for index in range(2)
        )
    )

    gate = aggregate_phase3_metrics(runs)["gates"]["completion"]  # type: ignore[index]

    assert gate["value"]["quick"]["rate"] == 0.9
    assert gate["value"]["deep_research"]["rate"] == 0.0
    assert gate["pass"] is False


def test_completed_run_budget_violations_are_reported() -> None:
    runs = (
        _run(budget_violations=("tool_calls", "active_seconds")),
        _run(
            task_id="failed-budget-run",
            status="failed",
            failure_category="budget_exhausted",
            budget_violations=("plan_rounds",),
        ),
    )

    report = aggregate_phase3_metrics(runs)

    assert report["completed_runs_with_budget_violations"] == 1
    assert report["completed_budget_violation_counts"] == {
        "active_seconds": 1,
        "tool_calls": 1,
    }
    mode_report = report["reported_by_mode"]["quick"]  # type: ignore[index]
    assert mode_report["completed_run_budget_violation_counts"] == {
        "active_seconds": 1,
        "tool_calls": 1,
    }


def test_reported_mode_metrics_include_claim_tool_and_latency_aggregates() -> None:
    runs = (
        _run(
            task_id="first",
            citation_counts=(2, 1),
            support_labels=("supported", "partial"),
            tool_calls=4,
            tool_call_records=6,
            plan_rounds=2,
            model_calls=6,
            active_seconds=10.0,
        ),
        _run(
            task_id="second",
            citation_counts=(),
            support_labels=(),
            answer_outcome="insufficient_evidence",
            tool_calls=2,
            tool_call_records=4,
            plan_rounds=1,
            model_calls=3,
            active_seconds=20.0,
        ),
    )

    metrics = aggregate_phase3_metrics(runs)["reported_by_mode"]["quick"]  # type: ignore[index]

    assert metrics["answer_outcomes"] == {
        "answered": 1,
        "insufficient_evidence": 1,
    }
    assert metrics["support_labels"] == {"partial": 1, "supported": 1}
    assert metrics["mean_claims_per_answer"] == 1.0
    assert metrics["mean_citations_per_claim"] == 1.5
    assert metrics["mean_tool_calls_per_run"] == 3.0
    assert metrics["mean_tool_call_records_per_run"] == 5.0
    assert metrics["mean_plan_rounds_per_run"] == 1.5
    assert metrics["mean_model_calls_per_run"] == 4.5
    assert metrics["active_seconds_median"] == 15.0
    assert metrics["active_seconds_p95_nearest_rank"] == 20.0
