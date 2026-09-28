"""Checked rendering and arithmetic for frozen Phase 2 acceptance gates."""

from __future__ import annotations

from pathlib import Path

import pytest

from research_platform.evaluation.acceptance_report import (
    AcceptanceReportError,
    build_acceptance_gate_report,
    load_acceptance_config,
    render_acceptance_gate_markdown,
)

ROOT = Path(__file__).resolve().parents[1]


def _observations() -> dict[str, object]:
    return {
        "paper_ndcg_at_10": 0.92,
        "paper_direct_mrr_at_10": 1.0,
        "paper_judged_recall_at_20": 1.0,
        "evidence_ndcg_at_10": 0.66,
        "evidence_direct_mrr_at_10": 0.63,
        "evidence_judged_recall_at_20": 0.87,
        "source_anchor_recall_at_10": 0.55,
        "source_anchor_recall_at_50": 0.55,
        "positive_families_with_source_hit_at_10_fraction": 4 / 7,
        "hard_failure_fraction": 0.0,
        "reranker_fallback_fraction": 0.1,
        "warm_p95_ms": 1485.8,
        "combined_cold_model_load_ms": 6142.4,
        "summed_cuda_allocated_bytes": 224_966_656,
    }


def test_gate_table_and_pass_total_come_from_the_same_fourteen_rows() -> None:
    acceptance = load_acceptance_config(ROOT / "benchmarks/phase2/acceptance-v9.toml")
    report = build_acceptance_gate_report(acceptance, _observations())
    markdown = render_acceptance_gate_markdown(report)

    assert report["gate_count"] == 14
    assert report["pass_count"] == 14
    assert report["passed"] is True
    assert markdown.count("| Pass |") == 14
    assert "Numeric gates passed: **14/14**" in markdown


def test_failed_gate_is_retained_in_the_aggregate_and_rendered_table() -> None:
    acceptance = load_acceptance_config(ROOT / "benchmarks/phase2/acceptance-v9.toml")
    observations = _observations()
    observations["warm_p95_ms"] = 1602.2
    report = build_acceptance_gate_report(acceptance, observations)
    markdown = render_acceptance_gate_markdown(report)

    assert report["gate_count"] == 14
    assert report["pass_count"] == 13
    assert report["passed"] is False
    assert "Numeric gates passed: **13/14**" in markdown
    assert "| Warm p95 | <= 1,500 | 1,602.2 | Fail |" in markdown


def test_gate_input_rejects_missing_nonfinite_and_unknown_metrics() -> None:
    acceptance = load_acceptance_config(ROOT / "benchmarks/phase2/acceptance-v9.toml")
    observations = _observations()
    del observations["warm_p95_ms"]
    with pytest.raises(AcceptanceReportError, match="missing metrics"):
        build_acceptance_gate_report(acceptance, observations)

    observations = _observations()
    observations["warm_p95_ms"] = float("nan")
    with pytest.raises(AcceptanceReportError, match="finite number"):
        build_acceptance_gate_report(acceptance, observations)

    observations = _observations()
    observations["unspecified_metric"] = 1.0
    with pytest.raises(AcceptanceReportError, match="unknown metrics"):
        build_acceptance_gate_report(acceptance, observations)


def test_gate_input_rejects_missing_frozen_criterion_and_bad_arithmetic() -> None:
    acceptance = load_acceptance_config(ROOT / "benchmarks/phase2/acceptance-v9.toml")
    acceptance = dict(acceptance)
    heldout = dict(acceptance["heldout"])
    del heldout["minimum_paper_ndcg_at_10"]
    acceptance["heldout"] = heldout
    with pytest.raises(AcceptanceReportError, match="criterion is missing"):
        build_acceptance_gate_report(acceptance, _observations())

    valid = build_acceptance_gate_report(
        load_acceptance_config(ROOT / "benchmarks/phase2/acceptance-v9.toml"),
        _observations(),
    )
    valid["pass_count"] = 13
    with pytest.raises(AcceptanceReportError, match="arithmetic"):
        render_acceptance_gate_markdown(valid)
