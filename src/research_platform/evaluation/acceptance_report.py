"""Checked rendering of frozen Phase 2 gate observations."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import tomllib


class AcceptanceReportError(ValueError):
    """Frozen criteria or aggregate observations cannot produce a valid report."""


Direction = Literal["minimum", "maximum"]


@dataclass(frozen=True)
class _GateSpec:
    observation: str
    label: str
    config_path: tuple[str, str]
    direction: Direction


_GATE_SPECS = (
    _GateSpec(
        "paper_ndcg_at_10",
        "Paper nDCG@10",
        ("heldout", "minimum_paper_ndcg_at_10"),
        "minimum",
    ),
    _GateSpec(
        "paper_direct_mrr_at_10",
        "Paper direct MRR@10",
        ("heldout", "minimum_paper_direct_mrr_at_10"),
        "minimum",
    ),
    _GateSpec(
        "paper_judged_recall_at_20",
        "Paper judged Recall@20",
        ("heldout", "minimum_paper_judged_recall_at_20"),
        "minimum",
    ),
    _GateSpec(
        "evidence_ndcg_at_10",
        "Evidence nDCG@10",
        ("heldout", "minimum_evidence_ndcg_at_10"),
        "minimum",
    ),
    _GateSpec(
        "evidence_direct_mrr_at_10",
        "Evidence direct MRR@10",
        ("heldout", "minimum_evidence_direct_mrr_at_10"),
        "minimum",
    ),
    _GateSpec(
        "evidence_judged_recall_at_20",
        "Evidence judged Recall@20",
        ("heldout", "minimum_evidence_judged_recall_at_20"),
        "minimum",
    ),
    _GateSpec(
        "source_anchor_recall_at_10",
        "Source-anchor Recall@10",
        ("heldout", "minimum_source_anchor_recall_at_10"),
        "minimum",
    ),
    _GateSpec(
        "source_anchor_recall_at_50",
        "Source-anchor Recall@50",
        ("heldout", "minimum_source_anchor_recall_at_50"),
        "minimum",
    ),
    _GateSpec(
        "positive_families_with_source_hit_at_10_fraction",
        "Positive source families with a hit at @10",
        ("heldout", "minimum_positive_families_with_source_hit_at_10_fraction"),
        "minimum",
    ),
    _GateSpec(
        "hard_failure_fraction",
        "Hard-failure fraction",
        ("operations", "maximum_hard_failure_fraction"),
        "maximum",
    ),
    _GateSpec(
        "reranker_fallback_fraction",
        "Reranker-fallback fraction",
        ("operations", "maximum_reranker_fallback_fraction"),
        "maximum",
    ),
    _GateSpec(
        "warm_p95_ms", "Warm p95", ("operations", "maximum_warm_p95_ms"), "maximum"
    ),
    _GateSpec(
        "combined_cold_model_load_ms",
        "Combined cold model load",
        ("operations", "maximum_combined_cold_model_load_ms"),
        "maximum",
    ),
    _GateSpec(
        "summed_cuda_allocated_bytes",
        "Summed CUDA allocation",
        ("operations", "maximum_summed_cuda_allocated_bytes"),
        "maximum",
    ),
)


def load_acceptance_config(path: Path) -> dict[str, object]:
    """Load a frozen acceptance TOML document."""
    try:
        loaded = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        raise AcceptanceReportError(
            "acceptance config is unreadable or invalid TOML"
        ) from None
    if not isinstance(loaded, dict) or loaded.get("schema_version") != 1:
        raise AcceptanceReportError("acceptance config schema is unsupported")
    return loaded


def build_acceptance_gate_report(
    acceptance: Mapping[str, object], observations: Mapping[str, object]
) -> dict[str, object]:
    """Evaluate all frozen numeric gates and derive the count from those rows."""
    if not isinstance(acceptance, Mapping) or not isinstance(observations, Mapping):
        raise AcceptanceReportError("acceptance and observations must be mappings")
    known_observations = {spec.observation for spec in _GATE_SPECS}
    if set(observations) != known_observations:
        missing = sorted(known_observations - set(observations))
        unknown = sorted(set(observations) - known_observations)
        details = []
        if missing:
            details.append("missing metrics: " + ", ".join(missing))
        if unknown:
            details.append("unknown metrics: " + ", ".join(unknown))
        raise AcceptanceReportError("; ".join(details))

    rows: list[dict[str, object]] = []
    for spec in _GATE_SPECS:
        threshold_value = _criterion(acceptance, spec.config_path)
        observed_value = observations[spec.observation]
        threshold = _finite_number(threshold_value, f"criterion {spec.config_path[1]}")
        observed = _finite_number(observed_value, f"observation {spec.observation}")
        passed = (
            observed >= threshold
            if spec.direction == "minimum"
            else observed <= threshold
        )
        rows.append(
            {
                "metric": spec.observation,
                "label": spec.label,
                "direction": spec.direction,
                "threshold": threshold,
                "observed": observed,
                "passed": passed,
            }
        )

    pass_count = sum(bool(row["passed"]) for row in rows)
    acceptance_id = acceptance.get("acceptance_id")
    selected_profile = acceptance.get("selected_profile")
    if not isinstance(acceptance_id, str) or not acceptance_id.strip():
        raise AcceptanceReportError("acceptance_id is missing")
    if not isinstance(selected_profile, str) or not selected_profile.startswith(
        "sha256:"
    ):
        raise AcceptanceReportError("selected_profile is missing or malformed")
    return {
        "acceptance_id": acceptance_id,
        "selected_profile": selected_profile,
        "gate_count": len(rows),
        "pass_count": pass_count,
        "passed": pass_count == len(rows),
        "gates": rows,
    }


def render_acceptance_gate_markdown(report: Mapping[str, object]) -> str:
    """Render the gate table and summary from one evaluated row collection."""
    gates = report.get("gates")
    pass_count = report.get("pass_count")
    gate_count = report.get("gate_count")
    if (
        not isinstance(gates, list)
        or not isinstance(pass_count, int)
        or not isinstance(gate_count, int)
        or gate_count != len(gates)
        or pass_count
        != sum(bool(row.get("passed")) for row in gates if isinstance(row, dict))
    ):
        raise AcceptanceReportError("gate report arithmetic is inconsistent")
    lines = [
        f"Acceptance config: `{report.get('acceptance_id')}`",
        f"Selected profile: `{report.get('selected_profile')}`",
        f"Numeric gates passed: **{pass_count}/{gate_count}**",
        "",
        "| Gate | Frozen limit | Observed | Result |",
        "| --- | ---: | ---: | --- |",
    ]
    for row in gates:
        if not isinstance(row, dict):
            raise AcceptanceReportError("gate report row is malformed")
        direction = ">=" if row.get("direction") == "minimum" else "<="
        threshold = _format_number(float(row["threshold"]))
        observed = _format_number(float(row["observed"]))
        result = "Pass" if row.get("passed") is True else "Fail"
        lines.append(
            f"| {row.get('label')} | {direction} {threshold} | {observed} | {result} |"
        )
    return "\n".join(lines) + "\n"


def _criterion(acceptance: Mapping[str, object], path: tuple[str, str]) -> object:
    section = acceptance.get(path[0])
    if not isinstance(section, Mapping) or path[1] not in section:
        raise AcceptanceReportError(f"frozen criterion is missing: {path[0]}.{path[1]}")
    return section[path[1]]


def _finite_number(value: object, name: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
    ):
        raise AcceptanceReportError(f"{name} must be a finite number")
    return float(value)


def _format_number(value: float) -> str:
    if value >= 1000:
        return f"{value:,.1f}" if not value.is_integer() else f"{value:,.0f}"
    return f"{value:.4f}" if not value.is_integer() else f"{value:.0f}"
