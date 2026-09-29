"""Synthetic checks for the ADR 0014 coverage pre-check and baseline context."""

from __future__ import annotations

import copy
import json
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from research_platform.evaluation.acceptance_context import (
    DECLARED_PROFILES,
    REFERENCE_BAND,
    FreezeError,
    baseline_context,
    dataset_fact_mismatches,
    render_baseline_lines,
    validate_freeze_precheck,
    validate_freeze_scale,
)
from research_platform.evaluation.acceptance_report import (
    build_acceptance_gate_report,
    load_acceptance_config,
)
from research_platform.evaluation.calibration import (
    CalibrationDataset,
    CalibrationQuery,
    CalibrationSourceAnchor,
    CalibrationSourceDocument,
    EvidenceJudgment,
    PaperJudgment,
    QuestionFamily,
)
from research_platform.evaluation.coverage import (
    DEFAULT_REQUIREMENTS,
    CoverageError,
    JudgedCount,
    QueryCoverage,
    build_coverage_report,
    check_recorded_coverage_table,
    coverage_table,
    evaluate_coverage,
    query_coverage,
    render_coverage_lines,
)
from research_platform.evaluation.matching import TextEvidenceRegion
from research_platform.evaluation.source_alignment import (
    SourceAlignmentDataset,
    TextAnchorAlignment,
    TextSpanRequirement,
)
from research_platform.ingestion.evidence import SourceLocation
from research_platform.search.contracts import (
    ComponentScores,
    EvidenceHit,
    PaperHit,
    SearchFilters,
)
from scripts.phase2_r8_v13_acceptance import (
    _measured_request_count,
    _timing_case_order,
    _timing_cases,
)

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_ID = UUID("4b11fab3-d4a5-4e7a-a58e-8654accf2c6c")
DOCUMENT_ID = UUID("00000000-0000-0000-0000-000000000001")
EXTRACTION_ID = UUID("00000000-0000-0000-0000-000000000002")
JUDGED_PAPER = "W111"
QUERY_TEXT = "Which synthetic method reported the result?"


def _dataset(family_count: int = 1, queries_per_family: int = 1) -> CalibrationDataset:
    document = CalibrationSourceDocument(
        DOCUMENT_ID, JUDGED_PAPER, EXTRACTION_ID, "c" * 64
    )
    anchor = CalibrationSourceAnchor(
        id="anchor",
        document_id=DOCUMENT_ID,
        page_index_zero_based=1,
        region_type="prose",
        locator="page 2",
        source_check="original_pdf_text_crosschecked",
    )
    families = tuple(
        QuestionFamily(
            id=f"family-{index}",
            split="held_out",
            categories=("specific_evidence",),
            reviewer_status="assistant_reviewed",
            reviewed_on=date(2026, 9, 29),
            filters=SearchFilters(),
            unsupported=False,
            requires_evidence=True,
            queries=tuple(
                CalibrationQuery(
                    id=f"family-{index}-q{number}",
                    role="canonical" if number == 0 else "paraphrase",
                    text=f"{QUERY_TEXT} {index}-{number}",
                )
                for number in range(queries_per_family)
            ),
            paper_judgments=(PaperJudgment(JUDGED_PAPER, 2, "direct"),),
            evidence_judgments=(EvidenceJudgment(JUDGED_PAPER, "anchor", 2, "direct"),),
            evidence_groups=(),
        )
        for index in range(family_count)
    )
    return CalibrationDataset(
        schema_version=1,
        dataset_id="synthetic-heldout-v1",
        dataset_kind="held_out",
        snapshot_id=SNAPSHOT_ID,
        split_policy_id="synthetic-split-v1",
        source_documents=(document,),
        source_anchors=(anchor,),
        families=families,
    )


def _alignment(dataset: CalibrationDataset) -> SourceAlignmentDataset:
    return SourceAlignmentDataset(
        schema_version=1,
        alignment_id="synthetic-alignment-v1",
        calibration_dataset_id=dataset.dataset_id,
        snapshot_id=SNAPSHOT_ID,
        policy_id="source-match-policy-v1",
        table_alignments=(),
        text_alignments=(
            TextAnchorAlignment(
                "anchor",
                DOCUMENT_ID,
                EXTRACTION_ID,
                (TextSpanRequirement(0, 0, 10, 0.8),),
            ),
        ),
    )


def _evidence_hit(rank: int, evidence_id: str) -> EvidenceHit:
    return EvidenceHit(
        chunk_id=f"chunk-{evidence_id}",
        source_evidence_ids=(evidence_id,),
        paper_id=JUDGED_PAPER,
        document_id=DOCUMENT_ID,
        document_version="published-1",
        document_version_kind="published",
        extraction_id=EXTRACTION_ID,
        chunking_configuration_id=None,
        kind="text",
        source_location=SourceLocation(page_index_zero_based=1),
        rank=rank,
        component_scores=ComponentScores(),
        text="secret synthetic passage",
    )


def _paper_hit(rank: int, paper_id: str) -> PaperHit:
    return PaperHit(
        paper_id=paper_id,
        title="secret synthetic title",
        publication_year=2024,
        rank=rank,
        component_scores=ComponentScores(),
    )


def _query_coverage() -> QueryCoverage:
    dataset = _dataset()
    paper_hits = [_paper_hit(1, JUDGED_PAPER)] + [
        _paper_hit(rank, f"W{200 + rank}") for rank in range(2, 13)
    ]
    evidence_hits = [
        _evidence_hit(1, "judged"),
        _evidence_hit(2, "off-anchor"),
        _evidence_hit(25, "deep-off-anchor"),
    ]
    regions = {
        "judged": TextEvidenceRegion("judged", DOCUMENT_ID, EXTRACTION_ID, 0, 0, 10),
        "off-anchor": TextEvidenceRegion(
            "off-anchor", DOCUMENT_ID, EXTRACTION_ID, 1, 0, 10
        ),
        "deep-off-anchor": TextEvidenceRegion(
            "deep-off-anchor", DOCUMENT_ID, EXTRACTION_ID, 2, 0, 10
        ),
    }
    return query_coverage(
        dataset,
        family_id="family-0",
        query_id="family-0-q0",
        paper_hits=paper_hits,
        evidence_hits=evidence_hits,
        regions_by_evidence_id=regions,
        alignments=_alignment(dataset),
    )


def test_query_coverage_counts_judged_and_unjudged_by_cutoff() -> None:
    coverage = _query_coverage()

    assert coverage.counts["paper_top10"] == JudgedCount(1, 9)
    assert coverage.counts["paper_top20"] == JudgedCount(1, 11)
    assert coverage.counts["evidence_top10"] == JudgedCount(1, 1)
    assert coverage.counts["evidence_top20"] == JudgedCount(1, 1)
    assert "chunk-deep-off-anchor" in coverage.unjudged_evidence_ids
    assert "chunk-deep-off-anchor" in coverage.pooled_evidence_ids
    assert JUDGED_PAPER not in coverage.unjudged_paper_ids
    assert len(coverage.pooled_paper_ids) == 12


def test_unknown_family_and_query_are_rejected() -> None:
    dataset = _dataset()
    kwargs: dict[str, Any] = {
        "paper_hits": (),
        "evidence_hits": (),
        "regions_by_evidence_id": {},
        "alignments": _alignment(dataset),
    }
    with pytest.raises(CoverageError):
        query_coverage(dataset, family_id="missing", query_id="x", **kwargs)
    with pytest.raises(CoverageError):
        query_coverage(dataset, family_id="family-0", query_id="x", **kwargs)


def _synthetic_queries(
    dataset: CalibrationDataset,
    *,
    judged: int = 20,
    unjudged: int = 0,
    weak_family: str | None = None,
) -> list[QueryCoverage]:
    queries = []
    for family in dataset.families:
        bad = family.id == weak_family
        top10 = JudgedCount(7, 3) if bad else JudgedCount(10, 0)
        queries.append(
            QueryCoverage(
                family_id=family.id,
                query_id=family.queries[0].id,
                counts={
                    "paper_top10": top10,
                    "paper_top20": JudgedCount(judged, unjudged),
                    "evidence_top10": JudgedCount(10, 0),
                    "evidence_top20": JudgedCount(20, 0),
                },
                pooled_paper_ids=frozenset({"W1", "W2"}),
                pooled_evidence_ids=frozenset({"c1"}),
                unjudged_paper_ids=frozenset(),
                unjudged_evidence_ids=frozenset(),
            )
        )
    return queries


def _report(
    profile_overrides: dict[str, dict[str, Any]] | None = None,
    family_count: int = 30,
):
    dataset = _dataset(family_count)
    queries = {
        name: _synthetic_queries(dataset, **(profile_overrides or {}).get(name, {}))
        for name in DECLARED_PROFILES
    }
    return build_coverage_report(
        dataset, queries, selected_profile="reranked_minilm_hybrid"
    )


def test_complete_coverage_meets_requirements_for_thirty_families() -> None:
    report = _report()

    assert len(report.family_order) == 30
    assert evaluate_coverage(report).passed
    assert report.profiles["bm25_lexical"].counts["paper_top10"] == JudgedCount(300, 0)


def test_top20_shortfall_names_the_profile_and_cutoff() -> None:
    # 5 of 30 families with 10% unjudged at top 20 gives 0.983; 6 unjudged of 20 per
    # family gives 0.70, well under 0.90.
    report = _report({"dense_e5": {"judged": 14, "unjudged": 6}})
    verdict = evaluate_coverage(report)

    assert not verdict.passed
    assert any("dense_e5 paper top 20" in failure for failure in verdict.failures)


def test_micro_top10_threshold_is_inclusive_at_95_percent() -> None:
    dataset = _dataset(2)
    queries = _synthetic_queries(dataset)
    exact = replace(
        queries[0],
        counts={**queries[0].counts, "paper_top10": JudgedCount(19, 1)},
    )
    report = build_coverage_report(
        dataset,
        {name: [exact, queries[1]] for name in DECLARED_PROFILES},
        selected_profile="reranked_minilm_hybrid",
    )
    # (19 + 10) / 20 = 0.95 exactly: meets the micro floor.
    assert not [
        failure
        for failure in evaluate_coverage(report).failures
        if "top 10: judged" in failure
    ]
    below = replace(
        queries[0], counts={**queries[0].counts, "paper_top10": JudgedCount(18, 2)}
    )
    report = build_coverage_report(
        dataset,
        {name: [below, queries[1]] for name in DECLARED_PROFILES},
        selected_profile="reranked_minilm_hybrid",
    )
    assert any("top 10: judged" in f for f in evaluate_coverage(report).failures)


def test_one_weak_selected_family_fails_even_when_micro_coverage_passes() -> None:
    report = _report({"reranked_minilm_hybrid": {"weak_family": "family-3"}})
    verdict = evaluate_coverage(report)

    assert report.profiles["reranked_minilm_hybrid"].counts[
        "paper_top10"
    ].fraction == pytest.approx(297 / 300)
    assert not verdict.passed
    assert len(verdict.failures) == 1
    assert "family top 10" in verdict.failures[0]


def test_weak_family_in_a_non_selected_profile_does_not_trigger_family_floor() -> None:
    report = _report({"bm25_lexical": {"weak_family": "family-3"}})

    assert evaluate_coverage(report).passed


def test_coverage_output_has_no_labels_metrics_ranks_or_text() -> None:
    dataset = _dataset()
    coverage = _query_coverage()
    report = build_coverage_report(
        dataset,
        {name: [coverage] for name in DECLARED_PROFILES},
        selected_profile="reranked_minilm_hybrid",
    )
    printed = "\n".join(render_coverage_lines(report))
    table = json.dumps(coverage_table(report))

    for output in (printed, table):
        lowered = output.lower()
        for forbidden in (
            "ndcg",
            "mrr",
            "recall",
            "label",
            "rank ",
            "family-0",
            QUERY_TEXT.lower(),
            JUDGED_PAPER.lower(),
            "chunk-",
            "secret synthetic",
            "rationale",
        ):
            assert forbidden not in lowered
    # Families appear only as opaque ordinals in printed output.
    assert "family 01" in printed


def test_recorded_table_round_trips_and_detects_tampering() -> None:
    report = _report()
    table = coverage_table(report)

    assert check_recorded_coverage_table(table).passed
    assert json.loads(json.dumps(table)) == table

    forged = copy.deepcopy(table)
    forged["profiles"]["bm25_lexical"]["paper_top10_unjudged"] = 200
    with pytest.raises(CoverageError, match="verdict differs"):
        check_recorded_coverage_table(forged)

    loosened = copy.deepcopy(table)
    loosened["requirements"]["minimum_micro_at_10"] = 0.5
    with pytest.raises(CoverageError, match="requirements differ"):
        check_recorded_coverage_table(loosened)

    with pytest.raises(CoverageError, match="malformed"):
        check_recorded_coverage_table({"selected_profile": "x"})
    assert table["requirements"] == DEFAULT_REQUIREMENTS.to_dict()


def _summaries(
    bm25_paper: float | None, bm25_evidence: float | None
) -> dict[str, dict[str, Any]]:
    return {
        "bm25_lexical": {
            "paper_ndcg_at_10_macro": bm25_paper,
            "evidence_ndcg_at_10_macro": bm25_evidence,
        },
        "dense_e5": {
            "paper_ndcg_at_10_macro": 0.9,
            "evidence_ndcg_at_10_macro": 0.9,
        },
    }


def test_baseline_band_flags_in_and_out_of_band_values() -> None:
    inside = baseline_context(_summaries(0.62, 0.11 + 0.2))
    assert not inside.unusual
    assert [row.in_band for row in inside.rows] == [True, True, None, None]

    below = baseline_context(_summaries(0.343, 0.18))
    assert below.unusual
    assert [row.in_band for row in below.rows[:2]] == [False, False]

    edge = baseline_context(_summaries(0.85, 0.25))
    assert not edge.unusual
    assert baseline_context(_summaries(None, 0.4)).unusual

    lines = "\n".join(render_baseline_lines(below))
    assert "OUT OF BAND" in lines
    assert "Set difficulty unusual: yes" in lines
    assert "dense_e5 paper_ndcg_at_10: 0.9000 - no reference band" in lines
    assert REFERENCE_BAND.to_dict() == {
        "bm25_paper_ndcg_at_10": [0.5, 0.85],
        "bm25_evidence_ndcg_at_10": [0.25, 0.75],
    }


def _gate_observations() -> dict[str, object]:
    return {
        "paper_ndcg_at_10": 0.82,
        "paper_direct_mrr_at_10": 0.9,
        "paper_judged_recall_at_20": 0.95,
        "evidence_ndcg_at_10": 0.5,
        "evidence_direct_mrr_at_10": 0.5,
        "evidence_judged_recall_at_20": 0.7,
        "source_anchor_recall_at_10": 0.5,
        "source_anchor_recall_at_50": 0.6,
        "positive_families_with_source_hit_at_10_fraction": 0.6,
        "hard_failure_fraction": 0.0,
        "reranker_fallback_fraction": 0.1,
        "warm_p95_ms": 900.0,
        "combined_cold_model_load_ms": 6000.0,
        "summed_cuda_allocated_bytes": 200_000_000,
    }


def test_baseline_flag_never_changes_gate_results() -> None:
    acceptance = load_acceptance_config(ROOT / "benchmarks/phase2/acceptance-v13.toml")
    before = build_acceptance_gate_report(acceptance, _gate_observations())
    baseline_context(_summaries(0.05, 0.99))
    after = build_acceptance_gate_report(acceptance, _gate_observations())

    assert before == after
    assert before["gate_count"] == 14
    assert before["passed"] is True


def test_v13_gate_thresholds_match_the_frozen_v10_thresholds() -> None:
    def gate_sections(name: str) -> dict[str, Any]:
        import tomllib

        raw = tomllib.loads(
            (ROOT / "benchmarks/phase2" / name).read_text(encoding="utf-8")
        )
        return {key: raw[key] for key in ("heldout", "operations", "selection")}

    assert gate_sections("acceptance-v13.toml") == gate_sections("acceptance-v10.toml")


def _freeze(family_count: int = 30, positive: int | None = None) -> dict[str, Any]:
    report = _report(family_count=family_count)
    return {
        "dataset": {
            "family_count": family_count,
            "minimum_family_count": 24,
            "positive_family_count": positive or family_count - 6,
            "unsupported_family_count": family_count - (positive or family_count - 6),
        },
        "coverage": coverage_table(report),
        "difficulty_band": REFERENCE_BAND.to_dict(),
    }


def _plan(family_count: int = 30) -> dict[str, Any]:
    return {"dataset_id": "phase2-benchmark-v13", "heldout_family_count": family_count}


@pytest.mark.parametrize("family_count", [24, 27, 30, 36])
def test_freeze_scale_follows_the_dataset_not_a_constant_ten(
    family_count: int,
) -> None:
    validate_freeze_scale(
        _freeze(family_count),
        family_count=family_count,
        dataset_id="phase2-benchmark-v13",
        sampling_plan=_plan(family_count),
    )
    validate_freeze_precheck(_freeze(family_count))


def test_freeze_scale_rejects_ten_families_and_inconsistent_sizes() -> None:
    kwargs: dict[str, Any] = {"dataset_id": "phase2-benchmark-v13"}
    with pytest.raises(FreezeError, match="below the recorded floor"):
        validate_freeze_scale(
            _freeze(10), family_count=10, sampling_plan=_plan(10), **kwargs
        )
    with pytest.raises(FreezeError, match="differs from the dataset"):
        validate_freeze_scale(
            _freeze(30), family_count=28, sampling_plan=_plan(28), **kwargs
        )
    with pytest.raises(FreezeError, match="sampling plan held-out size"):
        validate_freeze_scale(
            _freeze(30), family_count=30, sampling_plan=_plan(24), **kwargs
        )
    with pytest.raises(FreezeError, match="sampling plan dataset"):
        validate_freeze_scale(
            _freeze(30),
            family_count=30,
            dataset_id="another-dataset",
            sampling_plan=_plan(30),
        )
    lowered = _freeze(30)
    lowered["dataset"]["minimum_family_count"] = 10
    with pytest.raises(FreezeError, match="floor of at least 24"):
        validate_freeze_scale(lowered, family_count=30, sampling_plan=_plan(), **kwargs)
    unbalanced = _freeze(30)
    unbalanced["dataset"]["unsupported_family_count"] = 1
    with pytest.raises(FreezeError, match="do not sum"):
        validate_freeze_scale(
            unbalanced, family_count=30, sampling_plan=_plan(), **kwargs
        )


def test_freeze_precheck_requires_coverage_table_and_difficulty_band() -> None:
    missing = _freeze()
    del missing["coverage"]
    with pytest.raises(FreezeError, match="coverage table"):
        validate_freeze_precheck(missing)

    failing = _freeze()
    failing["coverage"]["profiles"]["dense_e5"]["evidence_top10_unjudged"] = 400
    with pytest.raises(FreezeError):
        validate_freeze_precheck(failing)

    fewer = _freeze()
    del fewer["coverage"]["profiles"]["fixed_window_dense_e5"]
    with pytest.raises(FreezeError, match="five declared profiles"):
        validate_freeze_precheck(fewer)

    moved = _freeze()
    moved["difficulty_band"]["bm25_paper_ndcg_at_10"] = [0.2, 0.9]
    with pytest.raises(FreezeError, match="difficulty band"):
        validate_freeze_precheck(moved)

    no_band = _freeze()
    del no_band["difficulty_band"]
    with pytest.raises(FreezeError, match="difficulty band"):
        validate_freeze_precheck(no_band)


def test_dataset_fact_mismatches_lists_only_differing_facts() -> None:
    expected = {"family_count": 30, "categories": {"discovery": 5}, "extra": 1}
    assert dataset_fact_mismatches(expected, dict(expected, extra=1)) == []
    assert dataset_fact_mismatches(
        expected, {"family_count": 29, "categories": {"discovery": 5}}
    ) == ["family_count"]


def test_timing_workload_visits_every_case_at_thirty_families() -> None:
    dataset = _dataset(family_count=30, queries_per_family=3)
    cases = _timing_cases(dataset)
    # 30 families x 3 queries x 2 operations + 2 zero-match cases.
    assert len(cases) == 182
    measured = _measured_request_count(len(cases), 100)
    assert measured == 182

    order = _timing_case_order(cases, warmups=6, measured=measured, seed=1)
    timed = order[6:]
    assert len(order) == 188
    visited = {(case["query"], case["operation"], case["kind"]) for case in timed}
    assert len(visited) == len(cases)
    # The frozen 100-request rule alone would leave later families untimed.
    assert _measured_request_count(42, 100) == 100


def test_freeze_scale_cross_checks_the_real_v3_sampling_plan() -> None:
    import tomllib

    plan = tomllib.loads(
        (ROOT / "benchmarks/phase2/benchmark-sampling-plan-v3.toml").read_text(
            encoding="utf-8"
        )
    )
    validate_freeze_scale(
        _freeze(30),
        family_count=30,
        dataset_id=str(plan["dataset_id"]),
        sampling_plan=plan,
    )
    altered = copy.deepcopy(plan)
    altered["coverage_precheck"]["minimum_judged_fraction_top10_micro"] = 0.9
    with pytest.raises(FreezeError, match="coverage thresholds"):
        validate_freeze_scale(
            _freeze(30),
            family_count=30,
            dataset_id=str(plan["dataset_id"]),
            sampling_plan=altered,
        )
    altered = copy.deepcopy(plan)
    altered["heldout_family_floor"] = 20
    with pytest.raises(FreezeError, match="floor differs"):
        validate_freeze_scale(
            _freeze(30),
            family_count=30,
            dataset_id=str(plan["dataset_id"]),
            sampling_plan=altered,
        )
