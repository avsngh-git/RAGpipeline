"""Pure aggregation for the Phase 3 live development evaluation."""

from __future__ import annotations

import math
import statistics
from collections import Counter
from dataclasses import dataclass
from typing import Literal, Sequence

from research_platform.runs.contracts import FailureCategory

ResearchModeName = Literal["quick", "deep_research"]
RUN_MODES: tuple[ResearchModeName, ...] = ("quick", "deep_research")
VALID_FAILURE_CATEGORIES = frozenset(category.value for category in FailureCategory)


@dataclass(frozen=True, slots=True)
class Phase3RunMetricsInput:
    """Text-free measurements from one private task/mode run record."""

    task_id: str
    mode: ResearchModeName
    status: Literal["queued", "running", "completed", "failed"]
    answer_outcome: str | None
    failure_category: str | None
    cited_handles: tuple[str, ...]
    registry_handles: frozenset[str]
    cited_paper_ids: frozenset[str]
    judged_paper_ids: frozenset[str]
    support_labels: tuple[str, ...]
    citation_counts: tuple[int, ...]
    tool_calls: int
    tool_call_records: int
    plan_rounds: int
    model_calls: int
    active_seconds: float
    unsupported: bool
    budget_violations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.task_id:
            raise ValueError("task_id must be non-empty")
        for name in (
            "tool_calls",
            "tool_call_records",
            "plan_rounds",
            "model_calls",
        ):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must be non-negative")
        if any(count < 0 for count in self.citation_counts):
            raise ValueError("citation counts must be non-negative")
        if not math.isfinite(self.active_seconds) or self.active_seconds < 0:
            raise ValueError("active_seconds must be finite and non-negative")
        if len(self.support_labels) != len(self.citation_counts):
            raise ValueError("support labels and citation counts must align by claim")


def unknown_handle_count(run: Phase3RunMetricsInput) -> int:
    """Count cited handle occurrences absent from the independent run registry."""
    return sum(handle not in run.registry_handles for handle in run.cited_handles)


def completion_rates(
    runs: Sequence[Phase3RunMetricsInput],
) -> dict[str, dict[str, int | float]]:
    """Return completed/total counts and rates for each mode and all runs."""
    result: dict[str, dict[str, int | float]] = {}
    for group, selected in (
        *((mode, [run for run in runs if run.mode == mode]) for mode in RUN_MODES),
        ("overall", list(runs)),
    ):
        completed = sum(run.status == "completed" for run in selected)
        total = len(selected)
        result[group] = {
            "completed": completed,
            "total": total,
            "rate": completed / total if total else 0.0,
        }
    return result


def categorized_failure_rate(runs: Sequence[Phase3RunMetricsInput]) -> float:
    """Return the fraction of failed runs carrying a failure category."""
    failed = [run for run in runs if run.status == "failed"]
    if not failed:
        return 1.0
    return sum(
        run.failure_category in VALID_FAILURE_CATEGORIES for run in failed
    ) / len(failed)


def nearest_rank_percentile(values: Sequence[float], percentile: float) -> float | None:
    """Return a percentile using the nearest-rank method, or ``None`` if empty."""
    if not 0.0 <= percentile <= 1.0:
        raise ValueError("percentile must be between 0 and 1")
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile * len(ordered)))
    return ordered[rank - 1]


def spot_check_rate(runs: Sequence[Phase3RunMetricsInput]) -> dict[str, int | float]:
    """Measure tasks with judgments where a cited paper has a label-2 judgment."""
    eligible = [run for run in runs if run.judged_paper_ids]
    matched = sum(bool(run.cited_paper_ids & run.judged_paper_ids) for run in eligible)
    return {
        "matched": matched,
        "eligible": len(eligible),
        "rate": matched / len(eligible) if eligible else 0.0,
    }


def unsupported_task_outcomes(
    runs: Sequence[Phase3RunMetricsInput],
) -> dict[str, object]:
    """Summarize outcomes for unsupported tasks against the expected outcome."""
    unsupported = [run for run in runs if run.unsupported]
    outcomes = Counter(run.answer_outcome or run.status for run in unsupported)
    expected = sum(
        run.status == "completed" and run.answer_outcome == "insufficient_evidence"
        for run in unsupported
    )
    return {
        "expected_outcome": "insufficient_evidence",
        "expected_count": expected,
        "task_count": len(unsupported),
        "expected_rate": expected / len(unsupported) if unsupported else 0.0,
        "outcome_counts": dict(sorted(outcomes.items())),
    }


def _mean(values: Sequence[float]) -> float | None:
    return statistics.fmean(values) if values else None


def _mode_report(runs: Sequence[Phase3RunMetricsInput]) -> dict[str, object]:
    completed = [run for run in runs if run.status == "completed"]
    support_counts = Counter(label for run in completed for label in run.support_labels)
    claims = [count for run in completed for count in run.citation_counts]
    tool_calls = [float(run.tool_calls) for run in runs]
    tool_call_records = [float(run.tool_call_records) for run in runs]
    plan_rounds = [float(run.plan_rounds) for run in runs]
    model_calls = [float(run.model_calls) for run in runs]
    active_seconds = [run.active_seconds for run in runs]
    return {
        "runs": len(runs),
        "completed": len(completed),
        "failed": sum(run.status == "failed" for run in runs),
        "answer_outcomes": dict(
            sorted(
                Counter(
                    run.answer_outcome for run in completed if run.answer_outcome
                ).items()
            )
        ),
        "support_labels": dict(sorted(support_counts.items())),
        "mean_claims_per_answer": _mean(
            [float(len(run.support_labels)) for run in completed]
        ),
        "mean_citations_per_claim": _mean([float(count) for count in claims]),
        "mean_tool_calls_per_run": _mean(tool_calls),
        "mean_tool_call_records_per_run": _mean(tool_call_records),
        "mean_plan_rounds_per_run": _mean(plan_rounds),
        "mean_model_calls_per_run": _mean(model_calls),
        "active_seconds_median": statistics.median(active_seconds)
        if active_seconds
        else None,
        "active_seconds_p95_nearest_rank": nearest_rank_percentile(
            active_seconds, 0.95
        ),
        "unknown_handle_count": sum(unknown_handle_count(run) for run in runs),
        "judged_paper_spot_check": spot_check_rate(runs),
        "unsupported_task_outcomes": unsupported_task_outcomes(runs),
        "failure_counts_by_category": dict(
            sorted(
                Counter(
                    run.failure_category or "uncategorized"
                    for run in runs
                    if run.status == "failed"
                ).items()
            )
        ),
        "completed_run_budget_violation_counts": dict(
            sorted(
                Counter(
                    violation
                    for run in completed
                    for violation in run.budget_violations
                ).items()
            )
        ),
    }


def aggregate_phase3_metrics(
    runs: Sequence[Phase3RunMetricsInput],
) -> dict[str, object]:
    """Aggregate operational gates and reported metrics without private text."""
    rates = completion_rates(runs)
    unknown = sum(unknown_handle_count(run) for run in runs)
    categorized = categorized_failure_rate(runs)
    per_mode = {
        mode: _mode_report([run for run in runs if run.mode == mode])
        for mode in RUN_MODES
    }
    completed = [run for run in runs if run.status == "completed"]
    budget_violation_counts = Counter(
        violation for run in completed for violation in run.budget_violations
    )
    return {
        "gates": {
            "unknown_handles": {"limit": 0, "value": unknown, "pass": unknown == 0},
            "completion": {
                "limit": 0.9,
                "value": rates,
                "pass": all(
                    float(rates[group]["rate"]) >= 0.9
                    for group in (*RUN_MODES, "overall")
                ),
            },
            "failure_categories": {
                "limit": 1.0,
                "value": categorized,
                "pass": categorized == 1.0,
            },
        },
        "reported_by_mode": per_mode,
        "completed_runs_with_budget_violations": sum(
            bool(run.budget_violations) for run in completed
        ),
        "completed_budget_violation_counts": dict(
            sorted(budget_violation_counts.items())
        ),
    }
