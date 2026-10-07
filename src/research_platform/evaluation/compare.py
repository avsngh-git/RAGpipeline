"""Compare persisted evaluation experiments and their matched item results."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from research_platform.evaluation.experiments import ExperimentRecord
from research_platform.evaluation.statistics import BootstrapResult, paired_bootstrap


class ComparisonError(ValueError):
    """The two experiments cannot be compared."""


@dataclass(frozen=True)
class Comparison:
    baseline: ExperimentRecord
    candidate: ExperimentRecord
    metric_deltas: dict[str, tuple[float | None, float | None, float | None]]
    item_bootstrap: dict[str, BootstrapResult]
    configuration_differences: tuple[str, ...]
    stage_counts: dict[str, tuple[int, int]]
    unmatched_items: tuple[int, int]


_NON_METRIC_ITEM_KEYS = {"item_id", "run_id", "task_id", "family_id", "query_id"}


def flatten(mapping: Mapping[str, object], prefix: str = "") -> dict[str, object]:
    """Flatten nested mappings into dotted keys."""
    flattened: dict[str, object] = {}
    for key, value in mapping.items():
        dotted_key = f"{prefix}.{key}" if prefix else key
        if isinstance(value, Mapping):
            flattened.update(flatten(value, dotted_key))
        else:
            flattened[dotted_key] = value
    return flattened


def compare_experiments(
    baseline: ExperimentRecord,
    candidate: ExperimentRecord,
    baseline_items: Sequence[Mapping[str, object]],
    candidate_items: Sequence[Mapping[str, object]],
    *,
    stages: Mapping[str, str] | None = None,
    seed: int = 20261006,
    repetitions: int = 10000,
) -> Comparison:
    """Compare experiment aggregates and paired item metrics."""
    if baseline.suite != candidate.suite:
        raise ComparisonError("experiments must use the same suite")
    if baseline.dataset_sha256 != candidate.dataset_sha256:
        raise ComparisonError("experiments must use the same dataset")

    baseline_by_id = _items_by_id(baseline_items)
    candidate_by_id = _items_by_id(candidate_items)
    matched_ids = sorted(baseline_by_id.keys() & candidate_by_id.keys())
    unmatched = (
        len(baseline_by_id.keys() - candidate_by_id.keys()),
        len(candidate_by_id.keys() - baseline_by_id.keys()),
    )

    metric_deltas: dict[str, tuple[float | None, float | None, float | None]] = {}
    for key in sorted(baseline.metrics.keys() | candidate.metrics.keys()):
        left = _number(baseline.metrics.get(key))
        right = _number(candidate.metrics.get(key))
        delta = right - left if left is not None and right is not None else None
        metric_deltas[key] = (left, right, delta)

    flattened_pairs = [
        (
            flatten(baseline_by_id[item_id]),
            flatten(candidate_by_id[item_id]),
        )
        for item_id in matched_ids
    ]
    numeric_keys = sorted(
        {
            key
            for left, right in flattened_pairs
            for key in left.keys() & right.keys()
            if key not in _NON_METRIC_ITEM_KEYS
            and _number(left[key]) is not None
            and _number(right[key]) is not None
        }
    )
    item_bootstrap = {
        key: paired_bootstrap(
            [
                (right_value, left_value)
                for left, right in flattened_pairs
                if (left_value := _number(left.get(key))) is not None
                and (right_value := _number(right.get(key))) is not None
            ],
            seed=seed,
            repetitions=repetitions,
        )
        for key in numeric_keys
    }

    baseline_configuration = flatten(baseline.configuration)
    candidate_configuration = flatten(candidate.configuration)
    configuration_differences = tuple(
        key
        for key in sorted(
            baseline_configuration.keys() | candidate_configuration.keys()
        )
        if key not in baseline_configuration
        or key not in candidate_configuration
        or baseline_configuration[key] != candidate_configuration[key]
    )

    stage_counts: dict[str, tuple[int, int]] = {}
    if stages is not None:
        counts_a: Counter[str] = Counter()
        counts_b: Counter[str] = Counter()
        for items, counts in (
            (baseline_items, counts_a),
            (candidate_items, counts_b),
        ):
            for item in items:
                run_id = item.get("run_id")
                if isinstance(run_id, str) and run_id in stages:
                    counts[stages[run_id]] += 1
        stage_counts = {
            stage: (counts_a[stage], counts_b[stage])
            for stage in sorted(counts_a.keys() | counts_b.keys())
        }

    return Comparison(
        baseline=baseline,
        candidate=candidate,
        metric_deltas=metric_deltas,
        item_bootstrap=item_bootstrap,
        configuration_differences=configuration_differences,
        stage_counts=stage_counts,
        unmatched_items=unmatched,
    )


def render_markdown(comparison: Comparison) -> str:
    """Render a text-free, deterministic comparison report."""
    baseline = comparison.baseline
    candidate = comparison.candidate
    lines = [
        f"# Compare {baseline.experiment_id} → {candidate.experiment_id}",
        "",
        "## Experiments",
        "",
        f"- Suite: `{_cell(baseline.suite)}`",
        f"- Dataset: `{_cell(baseline.dataset_name)}` `{_cell(baseline.dataset_version)}`",
        f"- Dataset SHA-256: `{baseline.dataset_sha256}`",
        f"- Code revisions: `{_cell(baseline.code_revision)}` → `{_cell(candidate.code_revision)}`",
        "",
        "## Metric deltas",
        "",
        "| Metric | a | b | Δ |",
        "| --- | ---: | ---: | ---: |",
    ]
    lines.extend(
        f"| {_cell(key)} | {_display(a)} | {_display(b)} | {_display(delta)} |"
        for key, (a, b, delta) in comparison.metric_deltas.items()
    )
    lines.extend(
        [
            "",
            "## Item bootstrap",
            "",
            "| Field | n | Mean Δ | 95% CI |",
            "| --- | ---: | ---: | --- |",
        ]
    )
    lines.extend(
        f"| {_cell(key)} | {result.n} | {_display(result.mean_delta)} | "
        f"{_display(result.ci95_low)} – {_display(result.ci95_high)} |"
        for key, result in comparison.item_bootstrap.items()
    )
    lines.extend(
        ["", "## Stage counts", "", "| Stage | a | b |", "| --- | ---: | ---: |"]
    )
    lines.extend(
        f"| {_cell(stage)} | {counts[0]} | {counts[1]} |"
        for stage, counts in comparison.stage_counts.items()
    )
    lines.extend(["", "## Configuration differences", ""])
    lines.extend(f"- `{_cell(key)}`" for key in comparison.configuration_differences)
    if not comparison.configuration_differences:
        lines.append("- None")
    lines.extend(
        [
            "",
            "## Unmatched items",
            "",
            f"- Only in a: {comparison.unmatched_items[0]}",
            f"- Only in b: {comparison.unmatched_items[1]}",
        ]
    )
    return "\n".join(lines) + "\n"


def _items_by_id(
    items: Sequence[Mapping[str, object]],
) -> dict[str, Mapping[str, object]]:
    indexed: dict[str, Mapping[str, object]] = {}
    for item in items:
        item_id = item.get("item_id")
        if not isinstance(item_id, str) or not item_id:
            raise ComparisonError("every item must have a non-empty item_id")
        if item_id in indexed:
            raise ComparisonError("item_id values must be unique within an experiment")
        indexed[item_id] = item
    return indexed


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _display(value: float | None) -> str:
    return "—" if value is None else f"{value:.6g}"


def _cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ").replace("\r", " ")
