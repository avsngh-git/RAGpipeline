"""Synthetic checks for the v14 acceptance runner: relative gate, CUDA windows, roster."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import tomllib

from research_platform.evaluation.acceptance_context import (
    baseline_context,
    validate_freeze_precheck,
)
from research_platform.evaluation.acceptance_report import (
    build_acceptance_gate_report,
    load_acceptance_config,
)

ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location(
    "phase2_r8_v14_acceptance_under_test", ROOT / "scripts/phase2_r8_v14_acceptance.py"
)
assert _SPEC is not None and _SPEC.loader is not None
runner: Any = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = runner
_SPEC.loader.exec_module(runner)


def _base_report() -> dict[str, Any]:
    acceptance = load_acceptance_config(ROOT / "benchmarks/phase2/acceptance-v14.toml")
    heldout = acceptance["heldout"]
    operations = acceptance["operations"]
    assert isinstance(heldout, dict) and isinstance(operations, dict)
    observations: dict[str, float] = {
        "paper_ndcg_at_10": 0.7,
        "paper_direct_mrr_at_10": 0.75,
        "paper_judged_recall_at_20": 0.95,
        "evidence_ndcg_at_10": 0.5,
        "evidence_direct_mrr_at_10": 0.5,
        "evidence_judged_recall_at_20": 0.6,
        "source_anchor_recall_at_10": 0.3,
        "source_anchor_recall_at_50": 0.4,
        "positive_families_with_source_hit_at_10_fraction": 0.6,
        "hard_failure_fraction": 0.0,
        "reranker_fallback_fraction": 0.0,
        "warm_p95_ms": 900.0,
        "combined_cold_model_load_ms": 8000.0,
        "summed_cuda_allocated_bytes": 500_000_000,
    }
    return build_acceptance_gate_report(acceptance, observations)


def _paired(paper_low: float | None, evidence_low: float | None) -> dict[str, Any]:
    def entry(low: float | None) -> dict[str, Any]:
        return {
            "n_families": 30,
            "mean_delta": None if low is None else low + 0.05,
            "ci95_low": low,
            "ci95_high": None if low is None else low + 0.1,
        }

    return {
        "paper_ndcg_at_10": entry(paper_low),
        "evidence_ndcg_at_10": entry(evidence_low),
    }


def test_relative_gate_passes_only_with_positive_lower_bounds() -> None:
    base = _base_report()
    assert base["passed"] and base["gate_count"] == 14

    report = runner._with_relative_gates(base, _paired(0.02, 0.01))
    assert report["gate_count"] == 16 and report["pass_count"] == 16
    assert report["passed"] is True

    for paper, evidence in ((0.0, 0.02), (0.02, -0.01), (None, 0.02)):
        failed = runner._with_relative_gates(base, _paired(paper, evidence))
        assert failed["passed"] is False
        assert failed["pass_count"] == 15
    # The inputs are not mutated.
    assert base["gate_count"] == 14


def test_relative_gate_fails_when_the_numeric_gates_already_fail() -> None:
    base = _base_report()
    base["gates"][0]["passed"] = False
    base["pass_count"] = 13
    base["passed"] = False
    report = runner._with_relative_gates(base, _paired(0.05, 0.05))
    assert report["passed"] is False and report["pass_count"] == 15


def test_paired_bootstrap_lower_bound_positive_for_uniform_gain() -> None:
    rows = {
        "sel": {f"f{i}": {"paper_ndcg_at_10": 0.8 + 0.001 * i} for i in range(30)},
        "bm25": {f"f{i}": {"paper_ndcg_at_10": 0.6 + 0.001 * i} for i in range(30)},
    }
    result = runner._paired_bootstrap(
        rows, "sel", "bm25", ("paper_ndcg_at_10",), seed=7, repetitions=500
    )["paper_ndcg_at_10"]
    assert result["n_families"] == 30
    assert result["ci95_low"] == pytest.approx(0.2)
    gate = runner._with_relative_gates(
        {"gates": [], "gate_count": 0, "pass_count": 0, "passed": True},
        {"paper_ndcg_at_10": result, "evidence_ndcg_at_10": result},
    )
    assert gate["passed"] is True

    tie = runner._paired_bootstrap(
        {"sel": rows["bm25"], "bm25": rows["bm25"]},
        "sel",
        "bm25",
        ("paper_ndcg_at_10",),
        seed=7,
        repetitions=200,
    )["paper_ndcg_at_10"]
    assert tie["ci95_low"] == 0.0


class _FakeCuda:
    """Tracks allocation and a peak counter that only reset_peak clears."""

    def __init__(self, allocated: int, peak: int) -> None:
        self.allocated = allocated
        self.peak = peak
        self.resets = 0

    def is_available(self) -> bool:
        return True

    def synchronize(self, device: str) -> None:
        pass

    def memory_allocated(self, device: str) -> int:
        return self.allocated

    def max_memory_allocated(self, device: str) -> int:
        return self.peak

    def reset_peak_memory_stats(self, device: str) -> None:
        self.resets += 1
        self.peak = self.allocated

    def alloc(self, amount: int, *, transient: int = 0) -> None:
        self.allocated += amount
        self.peak = max(self.peak, self.allocated + transient)


def test_cuda_window_ignores_earlier_runtimes_in_the_same_process() -> None:
    cuda = _FakeCuda(allocated=900_000_000, peak=3_000_000_000)  # earlier session
    torch = SimpleNamespace(cuda=cuda)
    with runner._cuda_window(torch) as window:
        cuda.alloc(400_000_000, transient=100_000_000)
    assert cuda.resets == 1
    assert window["allocated_delta_bytes"] == 400_000_000
    assert window["peak_delta_bytes"] == 500_000_000

    with runner._cuda_window(torch) as second:
        cuda.alloc(10, transient=0)
    assert second["peak_delta_bytes"] == 10 and cuda.resets == 2


def test_cuda_window_without_cuda_reports_none() -> None:
    cuda = SimpleNamespace(is_available=lambda: False)
    with runner._cuda_window(SimpleNamespace(cuda=cuda)) as window:
        pass
    assert window == {"allocated_delta_bytes": None, "peak_delta_bytes": None}


def test_roster_matches_the_frozen_v10_profile_and_acceptance_v14() -> None:
    frozen = tomllib.loads(runner.FROZEN_PROFILE_PATH.read_text(encoding="utf-8"))
    comparison = frozen["comparison_profiles"]
    assert set(runner.PROFILE_NAMES) <= set(comparison)
    assert runner.PROFILE_NAMES[0] == "bm25_lexical"
    assert runner.PROFILE_NAMES[3] == runner.SELECTED_NAME
    acceptance = tomllib.loads(runner.ACCEPTANCE_PATH.read_text(encoding="utf-8"))
    assert acceptance["selected_profile"] == comparison[runner.SELECTED_NAME]
    assert acceptance["selected_profile"] == frozen["profile_id"]
    assert acceptance["benchmark_split"] == "phase2-benchmark-v14"
    assert runner.FREEZE_PATH.name == "r8-v14-freeze-v1.toml"
    assert runner.FREEZE_ID == "phase2-r8-v14-v1"


def _coverage_counts() -> dict[str, int]:
    return {
        f"{kind}_top{cut}_{state}": 10 if state == "judged" else 0
        for kind in ("paper", "evidence")
        for cut in (10, 20)
        for state in ("judged", "unjudged")
    }


def test_freeze_precheck_and_baseline_context_accept_the_v14_roster() -> None:
    freeze = {
        "coverage": {
            "selected_profile": runner.SELECTED_NAME,
            "requirements": {
                "minimum_micro_at_10": 0.95,
                "minimum_micro_at_20": 0.9,
                "minimum_selected_family_at_10": 0.8,
            },
            "profiles": {name: _coverage_counts() for name in runner.PROFILE_NAMES},
            "selected_family_minimum_top10": {"evidence": 1.0, "paper": 1.0},
            "pool": {
                "paper_depth": 20,
                "evidence_depth": 50,
                "paper_cap": 80,
                "evidence_cap": 200,
                "max_unique_papers_per_family": 40,
                "max_unique_evidence_per_family": 100,
            },
            "passed": True,
        },
        "difficulty_band": {
            "bm25_paper_ndcg_at_10": [0.5, 0.85],
            "bm25_evidence_ndcg_at_10": [0.25, 0.75],
        },
    }
    validate_freeze_precheck(freeze, declared_profiles=runner.PROFILE_NAMES)
    with pytest.raises(Exception, match="five declared profiles"):
        validate_freeze_precheck(freeze)  # legacy E5 roster is the default

    summaries = {
        "bm25_lexical": {
            "paper_ndcg_at_10_macro": 0.6,
            "evidence_ndcg_at_10_macro": 0.3,
        },
        "dense_gte": {"paper_ndcg_at_10_macro": 0.7, "evidence_ndcg_at_10_macro": 0.4},
    }
    context = baseline_context(summaries, dense_profile="dense_gte")
    assert {row.profile for row in context.rows} == {"bm25_lexical", "dense_gte"}
    assert context.unusual is False
