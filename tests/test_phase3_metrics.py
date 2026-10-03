from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

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
from research_platform.runs.contracts import ResearchRunView
from scripts import phase3_dev_evaluation as evaluation


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


def test_resume_keeps_existing_pairs_out_of_submission_queue() -> None:
    tasks = tuple(
        evaluation.DevelopmentTask(
            task_id=f"task-{index}",
            source="calibration-v1",
            question="synthetic question",
            filters=None,
            unsupported=False,
            judged_paper_ids=frozenset(),
        )
        for index in range(2)
    )

    pending = evaluation._pending_task_pairs(
        tasks,
        ("quick", "deep_research"),
        {("task-0", "quick"), ("task-1", "quick"), ("task-0", "deep_research")},
    )

    assert [(task.task_id, mode) for _, task, mode in pending] == [
        ("task-1", "deep_research")
    ]


def test_resume_rejects_duplicate_or_unmapped_run_entries() -> None:
    run_id = str(uuid4())
    event = {
        "event": "run_view",
        "task": {"task_id": "task-0"},
        "mode": "deep_research",
        "run_id": run_id,
        "poll": 0,
        "view": {"status": "queued"},
    }

    with pytest.raises(ValueError, match="multiple tasks"):
        evaluation._journal_submissions(
            (
                event,
                {
                    **event,
                    "task": {"task_id": "task-1"},
                },
            )
        )
    with pytest.raises(ValueError, match="unmapped artifact"):
        evaluation._journal_submissions(
            (
                {
                    "event": "run_artifacts",
                    "run_id": run_id,
                    "registry_handles": [],
                    "tool_calls": [],
                },
            )
        )


@pytest.mark.anyio
async def test_resume_polls_existing_failed_run_without_posting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = uuid4()
    task = evaluation.DevelopmentTask(
        task_id="task-0",
        source="calibration-v1",
        question="synthetic question",
        filters=None,
        unsupported=False,
        judged_paper_ids=frozenset(),
    )
    current = ResearchRunView.model_validate(
        {
            "run_id": str(run_id),
            "status": "queued",
            "mode": "deep_research",
            "question": task.question,
            "created_at": datetime.now(UTC).isoformat(),
        }
    )
    failed = ResearchRunView.model_validate(
        {
            "run_id": str(run_id),
            "status": "failed",
            "mode": "deep_research",
            "question": task.question,
            "failure_category": "timeout",
            "created_at": datetime.now(UTC).isoformat(),
            "completed_at": datetime.now(UTC).isoformat(),
        }
    )

    class _Response:
        status_code = 200

        def json(self) -> dict[str, object]:
            return failed.model_dump(mode="json")

    class _Client:
        posts = 0
        gets = 0

        async def get(self, url: str) -> _Response:
            self.gets += 1
            return _Response()

        async def post(self, url: str, **kwargs: object) -> None:
            self.posts += 1
            raise AssertionError("resume must not submit an existing run again")

    client = _Client()
    journal = tmp_path / "runs.jsonl"
    journal.touch(mode=0o600)
    monkeypatch.setattr(evaluation, "POLL_INTERVAL_SECONDS", 0.0)
    recovered = await evaluation._poll_existing_run(
        client=client,  # type: ignore[arg-type]
        task=task,
        mode="deep_research",
        run_id=run_id,
        current=current,
        output_path=journal,
        poll_index=0,
    )

    assert recovered.status.value == "failed"
    assert recovered.failure_category.value == "timeout"
    assert client.gets == 1
    assert client.posts == 0
    saved = [json.loads(line) for line in journal.read_text().splitlines()]
    assert saved[-1]["view"]["failure_category"] == "timeout"


@pytest.mark.anyio
async def test_resume_orchestration_reconciles_ledger_and_preserves_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    task = evaluation.DevelopmentTask(
        task_id="task-0",
        source="calibration-v1",
        question="synthetic question",
        filters=None,
        unsupported=False,
        judged_paper_ids=frozenset(),
    )
    quick_id, deep_id = uuid4(), uuid4()
    now = datetime.now(UTC).isoformat()
    quick = ResearchRunView.model_validate(
        {
            "run_id": str(quick_id),
            "status": "completed",
            "mode": "quick",
            "question": task.question,
            "answer_outcome": "answered",
            "created_at": now,
            "completed_at": now,
        }
    )
    deep_queued = ResearchRunView.model_validate(
        {
            "run_id": str(deep_id),
            "status": "queued",
            "mode": "deep_research",
            "question": task.question,
            "created_at": now,
        }
    )
    deep_failed = ResearchRunView.model_validate(
        {
            "run_id": str(deep_id),
            "status": "failed",
            "mode": "deep_research",
            "question": task.question,
            "failure_category": "timeout",
            "created_at": now,
            "completed_at": now,
        }
    )
    output_dir = tmp_path / "evaluation"
    output_dir.mkdir(mode=0o700)
    journal = output_dir / "runs.jsonl"
    journal.touch(mode=0o600)
    task_record = {
        "task_id": task.task_id,
        "source": task.source,
        "question": task.question,
        "filters": None,
        "unsupported": False,
        "judged_paper_ids": [],
    }
    journal_events = (
        {
            "event": "run_view",
            "task": task_record,
            "mode": "quick",
            "run_id": str(quick_id),
            "poll": 1,
            "view": quick.model_dump(mode="json"),
        },
        {
            "event": "run_artifacts",
            "task": task_record,
            "mode": "quick",
            "run_id": str(quick_id),
            "registry_handles": [],
            "tool_calls": [],
        },
        {
            "event": "run_view",
            "task": task_record,
            "mode": "deep_research",
            "run_id": str(deep_id),
            "poll": 0,
            "view": deep_queued.model_dump(mode="json"),
        },
    )
    with journal.open("w", encoding="utf-8") as target:
        for event in journal_events:
            target.write(json.dumps(event) + "\n")
    journal.chmod(0o600)

    class _Pool:
        async def close(self) -> None:
            return None

    class _Sampler:
        def __init__(self, checkpoint_path: Path, *, resume: bool) -> None:
            return None

        async def sample(self) -> None:
            await asyncio.Event().wait()

        def stop(self) -> None:
            return None

        def report(self) -> dict[str, object]:
            return {"quick": None, "deep_research": None, "samples_by_mode": {}}

    class _Response:
        status_code = 200

        def json(self) -> dict[str, object]:
            return deep_failed.model_dump(mode="json")

    class _Client:
        def __init__(self, **kwargs: object) -> None:
            self.posts = 0
            self.gets = 0

        async def __aenter__(self) -> _Client:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def get(self, url: str) -> _Response:
            self.gets += 1
            return _Response()

        async def post(self, url: str, **kwargs: object) -> None:
            self.posts += 1
            raise AssertionError("resume must not resubmit an existing task/mode pair")

    client = _Client()
    monkeypatch.setattr(
        evaluation,
        "Settings",
        lambda: type("FakeSettings", (), {"database_url": "unused"})(),
    )
    monkeypatch.setattr(evaluation, "_validate_private_service", lambda settings: None)
    monkeypatch.setattr(evaluation.asyncpg, "create_pool", lambda *a, **k: _pool())
    monkeypatch.setattr(evaluation.httpx, "AsyncClient", lambda **kwargs: client)
    monkeypatch.setattr(evaluation, "_GpuSampler", _Sampler)

    async def _pool() -> _Pool:
        return _Pool()

    async def _artifacts(
        pool: object, run_id: object
    ) -> tuple[tuple[dict[str, object], ...], tuple[str, ...]]:
        return (), ()

    monkeypatch.setattr(evaluation, "_read_run_artifacts", _artifacts)

    result = await evaluation._evaluate(
        (task,), evaluation.MODES, output_dir, resume=True
    )

    assert result["run_count"] == 2
    assert client.gets == 1
    assert client.posts == 0
    assert result["gates"]["completion"]["value"]["overall"] == {
        "completed": 1,
        "total": 2,
        "rate": 0.5,
    }  # type: ignore[index]
    assert result["reported_by_mode"]["deep_research"][
        "failure_counts_by_category"
    ] == {"timeout": 1}  # type: ignore[index]


def test_recovered_aggregate_retains_the_timeout_failure() -> None:
    completed = _run(task_id="preserved-completed")
    timed_out = _run(
        task_id="preserved-timeout",
        mode="deep_research",
        status="failed",
        answer_outcome=None,
        failure_category="timeout",
        cited_handles=(),
        registry_handles=frozenset(),
        cited_paper_ids=frozenset(),
        judged_paper_ids=frozenset(),
        support_labels=(),
        citation_counts=(),
    )

    aggregate = aggregate_phase3_metrics((completed, timed_out))

    assert aggregate["gates"]["completion"]["value"]["overall"] == {
        "completed": 1,
        "total": 2,
        "rate": 0.5,
    }  # type: ignore[index]
    assert aggregate["gates"]["failure_categories"]["pass"] is True  # type: ignore[index]
    assert aggregate["reported_by_mode"]["deep_research"][
        "failure_counts_by_category"
    ] == {"timeout": 1}  # type: ignore[index]
