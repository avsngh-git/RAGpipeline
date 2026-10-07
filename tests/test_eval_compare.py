from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from research_platform.evaluation.cli import _parser
from research_platform.evaluation.compare import (
    ComparisonError,
    compare_experiments,
    flatten,
    render_markdown,
)
from research_platform.evaluation.experiments import (
    ExperimentRecord,
    ExperimentStatus,
)
from research_platform.evaluation.statistics import paired_bootstrap


def _record(
    *,
    suite: str = "scripted-regression",
    dataset_sha256: str = "a" * 64,
    configuration: dict[str, object] | None = None,
    metrics: dict[str, int | float | None] | None = None,
) -> ExperimentRecord:
    experiment_id = uuid4()
    return ExperimentRecord(
        experiment_id=experiment_id,
        suite=suite,
        status=ExperimentStatus.COMPLETED,
        dataset_name="synthetic",
        dataset_version="v1",
        dataset_sha256=dataset_sha256,
        code_revision="revision-a",
        configuration=configuration or {},
        metrics=metrics or {},
        items_path=f"local-reference/experiments/{experiment_id}/items.jsonl",
        started_at=datetime.now(UTC),
    )


def test_paired_bootstrap_known_values() -> None:
    identical = paired_bootstrap([(0.5, 0.5), (0.8, 0.8)], seed=3, repetitions=100)
    positive = paired_bootstrap([(1.0, 0.0), (2.0, 1.0)], seed=3, repetitions=100)

    assert identical.n == 2
    assert identical.mean_delta == 0
    assert (identical.ci95_low, identical.ci95_high) == (0, 0)
    assert positive.mean_delta == 1
    assert (positive.ci95_low, positive.ci95_high) == (1, 1)


def test_paired_bootstrap_empty() -> None:
    assert paired_bootstrap([], seed=3, repetitions=10).n == 0
    assert paired_bootstrap([], seed=3, repetitions=10).mean_delta is None
    assert paired_bootstrap([], seed=3, repetitions=10).ci95_low is None
    assert paired_bootstrap([], seed=3, repetitions=10).ci95_high is None


def test_bootstrap_is_seeded() -> None:
    pairs = [(0.9, 0.4), (0.1, 0.8), (0.7, 0.3)]
    assert paired_bootstrap(pairs, seed=17, repetitions=200) == paired_bootstrap(
        pairs, seed=17, repetitions=200
    )


def test_compare_rejects_different_suite_or_dataset() -> None:
    record = _record()
    with pytest.raises(ComparisonError, match="same suite"):
        compare_experiments(
            record,
            _record(suite="agent-dev"),
            [],
            [],
            repetitions=10,
        )
    with pytest.raises(ComparisonError, match="same dataset"):
        compare_experiments(
            record,
            _record(dataset_sha256="b" * 64),
            [],
            [],
            repetitions=10,
        )


def test_metric_deltas_and_non_numeric() -> None:
    baseline = _record(metrics={"shared": 1, "missing": None})
    candidate = _record(metrics={"shared": 3, "other": 5})
    baseline = baseline.model_copy(
        update={"metrics": {"shared": 1, "missing": None, "truth": True, "text": "a"}}
    )
    candidate = candidate.model_copy(
        update={"metrics": {"shared": 3, "other": 5, "truth": 1, "text": "b"}}
    )
    comparison = compare_experiments(
        baseline,
        candidate,
        [],
        [],
        repetitions=10,
    )

    assert comparison.metric_deltas == {
        "missing": (None, None, None),
        "other": (None, 5.0, None),
        "shared": (1.0, 3.0, 2.0),
        "text": (None, None, None),
        "truth": (None, 1.0, None),
    }


def test_item_bootstrap_matches_items_by_id() -> None:
    comparison = compare_experiments(
        _record(),
        _record(),
        [
            {"item_id": "one", "score": 1, "passed": True, "task_id": "ignored"},
            {"item_id": "two", "score": 2},
            {"item_id": "baseline-only", "score": 9},
        ],
        [
            {"item_id": "one", "score": 4, "passed": False, "task_id": "ignored"},
            {"item_id": "two", "score": "unknown"},
            {"item_id": "candidate-only", "score": 0},
        ],
        seed=5,
        repetitions=100,
    )

    assert comparison.unmatched_items == (1, 1)
    assert set(comparison.item_bootstrap) == {"score"}
    assert comparison.item_bootstrap["score"].n == 1
    assert comparison.item_bootstrap["score"].mean_delta == 3
    assert (
        comparison.item_bootstrap["score"].ci95_low,
        comparison.item_bootstrap["score"].ci95_high,
    ) == (3, 3)


def test_stage_counts() -> None:
    comparison = compare_experiments(
        _record(),
        _record(),
        [
            {"item_id": "a", "run_id": "run-a"},
            {"item_id": "b", "run_id": "run-b"},
            {"item_id": "c"},
        ],
        [{"item_id": "d", "run_id": "run-b"}, {"item_id": "e", "run_id": "run-c"}],
        stages={"run-a": "retrieval", "run-b": "generation", "run-c": "none"},
        repetitions=10,
    )

    assert comparison.stage_counts == {
        "generation": (1, 1),
        "none": (0, 1),
        "retrieval": (1, 0),
    }


def test_configuration_differences() -> None:
    comparison = compare_experiments(
        _record(configuration={"model": {"name": "a", "temperature": 0.1}}),
        _record(configuration={"model": {"name": "b", "temperature": 0.1}, "seed": 2}),
        [],
        [],
        repetitions=10,
    )

    assert comparison.configuration_differences == ("model.name", "seed")
    assert flatten({"model": {"name": "a"}}) == {"model.name": "a"}


def test_markdown_sections_present() -> None:
    comparison = compare_experiments(
        _record(metrics={"score": 0.5}),
        _record(metrics={"score": 0.75}),
        [{"item_id": "one", "score": 0.5}],
        [{"item_id": "one", "score": 0.75}],
        stages={"run-a": "generation"},
        repetitions=10,
    )

    report = render_markdown(comparison)
    for section in (
        "# Compare ",
        "## Experiments",
        "## Metric deltas",
        "## Item bootstrap",
        "## Stage counts",
        "## Configuration differences",
        "## Unmatched items",
    ):
        assert section in report
    assert "| score | 0.5 | 0.75 | 0.25 |" in report


def test_compare_cli_arguments() -> None:
    baseline_id, candidate_id = uuid4(), uuid4()
    args = _parser().parse_args(
        ["compare", str(baseline_id), str(candidate_id), "--with-stages"]
    )

    assert args.command == "compare"
    assert args.baseline_id == baseline_id
    assert args.candidate_id == candidate_id
    assert args.with_stages is True
