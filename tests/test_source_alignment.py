"""Regression checks for the checked-in Phase 2 source alignment manifest."""

from pathlib import Path

from research_platform.evaluation.calibration import load_calibration
from research_platform.evaluation.source_alignment import load_source_alignment


def test_phase2_source_alignment_manifest_loads_against_calibration() -> None:
    root = Path(__file__).resolve().parents[1]
    calibration = load_calibration(root / "benchmarks/phase2/calibration-v1.toml")
    alignment = load_source_alignment(
        root / "benchmarks/phase2/source-alignment-v1.toml", calibration
    )

    assert len(alignment.table_alignments) == 8
    assert alignment.text_alignments == ()
    positive_anchor_ids = {
        judgment.source_anchor_id
        for family in calibration.families
        for judgment in family.evidence_judgments
        if judgment.label == 2
    }
    assert positive_anchor_ids <= set(alignment.by_anchor_id)
