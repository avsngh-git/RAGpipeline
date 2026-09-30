"""Descriptive acceptance context and freeze checks for the enlarged held-out set.

ADR 0014 adds a baseline difficulty band and an N-family freeze. Nothing here reads
or changes a gate threshold or a gate outcome.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from research_platform.evaluation.coverage import (
    DEFAULT_REQUIREMENTS,
    CoverageError,
    check_recorded_coverage_table,
)

MINIMUM_HELDOUT_FAMILIES = 24
TARGET_HELDOUT_FAMILIES = 30
DECLARED_PROFILES = (
    "bm25_lexical",
    "dense_e5",
    "hybrid_e5",
    "reranked_minilm_hybrid",
    "fixed_window_dense_e5",
)


class FreezeError(ValueError):
    """The freeze manifest is inconsistent with the sample, plan or ADR 0014."""


@dataclass(frozen=True)
class DifficultyBand:
    """Reference range for BM25 nDCG@10 from published sets (judgment, not a gate)."""

    paper_ndcg_at_10: tuple[float, float] = (0.50, 0.85)
    evidence_ndcg_at_10: tuple[float, float] = (0.25, 0.75)

    def to_dict(self) -> dict[str, list[float]]:
        return {
            "bm25_paper_ndcg_at_10": list(self.paper_ndcg_at_10),
            "bm25_evidence_ndcg_at_10": list(self.evidence_ndcg_at_10),
        }


REFERENCE_BAND = DifficultyBand()


@dataclass(frozen=True)
class BaselineRow:
    profile: str
    metric: str
    value: float | None
    band: tuple[float, float] | None
    in_band: bool | None


@dataclass(frozen=True)
class BaselineContext:
    rows: tuple[BaselineRow, ...]
    unusual: bool


def baseline_context(
    profile_summaries: Mapping[str, Mapping[str, Any]],
    band: DifficultyBand = REFERENCE_BAND,
    *,
    dense_profile: str = "dense_e5",
) -> BaselineContext:
    """Compare baseline macro nDCG@10 with the reference band; purely descriptive."""
    rows: list[BaselineRow] = []
    for profile, bands in (
        (
            "bm25_lexical",
            (band.paper_ndcg_at_10, band.evidence_ndcg_at_10),
        ),
        (dense_profile, (None, None)),
    ):
        summary = profile_summaries.get(profile, {})
        for metric, limits in zip(
            ("paper_ndcg_at_10", "evidence_ndcg_at_10"), bands, strict=True
        ):
            raw = summary.get(f"{metric}_macro")
            value = float(raw) if isinstance(raw, (int, float)) else None
            if value is not None and not math.isfinite(value):
                value = None
            in_band = (
                None
                if limits is None or value is None
                else limits[0] <= value <= limits[1]
            )
            rows.append(BaselineRow(profile, metric, value, limits, in_band))
    unusual = any(
        row.profile == "bm25_lexical" and row.in_band is not True for row in rows
    )
    return BaselineContext(rows=tuple(rows), unusual=unusual)


def render_baseline_lines(context: BaselineContext) -> list[str]:
    lines = ["Baseline context (descriptive only; never changes a gate result):"]
    for row in context.rows:
        value = f"{row.value:.4f}" if row.value is not None else "n/a"
        if row.band is None:
            flag = "no reference band"
            band = ""
        else:
            band = f" (reference {row.band[0]:.2f}-{row.band[1]:.2f})"
            flag = {True: "in band", False: "OUT OF BAND", None: "unavailable"}[
                row.in_band
            ]
        lines.append(f"  {row.profile} {row.metric}: {value}{band} - {flag}")
    lines.append(
        "  Set difficulty unusual: yes; diagnostic context only"
        if context.unusual
        else "  Set difficulty unusual: no"
    )
    return lines


def dataset_fact_mismatches(
    expected: Mapping[str, Any], observed: Mapping[str, Any]
) -> list[str]:
    """Names of sample facts that differ between the freeze and the loaded dataset."""
    return sorted(key for key, value in observed.items() if expected.get(key) != value)


def validate_freeze_scale(
    freeze: Mapping[str, Any],
    *,
    family_count: int,
    dataset_id: str,
    sampling_plan: Mapping[str, Any],
) -> None:
    """Check that N comes from the freeze and sampling plan, not a constant."""
    dataset = freeze.get("dataset")
    if not isinstance(dataset, Mapping):
        raise FreezeError("freeze dataset facts are missing")
    floor = dataset.get("minimum_family_count")
    if not isinstance(floor, int) or floor < MINIMUM_HELDOUT_FAMILIES:
        raise FreezeError("freeze must record a family floor of at least 24")
    if family_count < floor:
        raise FreezeError("held-out family count is below the recorded floor")
    if dataset.get("family_count") != family_count:
        raise FreezeError("freeze family count differs from the dataset")
    positive = dataset.get("positive_family_count")
    unsupported = dataset.get("unsupported_family_count")
    if (
        not isinstance(positive, int)
        or not isinstance(unsupported, int)
        or positive + unsupported != family_count
    ):
        raise FreezeError("freeze positive and unsupported counts do not sum to N")
    if sampling_plan.get("dataset_id") != dataset_id:
        raise FreezeError("sampling plan dataset differs from the held-out dataset")
    if sampling_plan.get("heldout_family_count") != family_count:
        raise FreezeError("sampling plan held-out size differs from the dataset")
    plan_floor = sampling_plan.get("heldout_family_floor")
    if plan_floor is not None and plan_floor != floor:
        raise FreezeError("freeze family floor differs from the sampling plan")
    precheck = sampling_plan.get("coverage_precheck")
    if precheck is not None and (
        not isinstance(precheck, Mapping)
        or (
            precheck.get("minimum_judged_fraction_top10_micro"),
            precheck.get("minimum_judged_fraction_top20_micro"),
            precheck.get("minimum_judged_fraction_top10_per_family_selected_profile"),
        )
        != (
            DEFAULT_REQUIREMENTS.minimum_micro_at_10,
            DEFAULT_REQUIREMENTS.minimum_micro_at_20,
            DEFAULT_REQUIREMENTS.minimum_selected_family_at_10,
        )
    ):
        raise FreezeError("sampling plan coverage thresholds differ from ADR 0014")


def validate_freeze_precheck(
    freeze: Mapping[str, Any],
    *,
    declared_profiles: Sequence[str] = DECLARED_PROFILES,
) -> None:
    """Require the recorded coverage table and difficulty band from ADR 0014."""
    coverage = freeze.get("coverage")
    if not isinstance(coverage, Mapping):
        raise FreezeError("freeze lacks the recorded coverage table")
    try:
        verdict = check_recorded_coverage_table(coverage)
    except CoverageError as error:
        raise FreezeError(str(error)) from error
    if not verdict.passed:
        raise FreezeError("recorded coverage table does not meet the requirements")
    profiles = coverage.get("profiles")
    if not isinstance(profiles, Mapping) or set(profiles) != set(declared_profiles):
        raise FreezeError("coverage table must cover the five declared profiles")
    band = freeze.get("difficulty_band")
    if not isinstance(band, Mapping) or _normalized(band) != _normalized(
        REFERENCE_BAND.to_dict()
    ):
        raise FreezeError("freeze difficulty band differs from ADR 0014")


def _normalized(value: Mapping[str, Any]) -> dict[str, Sequence[float]]:
    return {
        key: [float(item) for item in items]
        for key, items in value.items()
        if key.startswith("bm25_")
    }
