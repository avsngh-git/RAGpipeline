"""Validation tests for the versioned Phase 2 calibration dataset."""

from pathlib import Path

import pytest

from research_platform.evaluation.calibration import (
    CalibrationLoadError,
    load_calibration,
    load_heldout_dataset,
    parse_calibration,
    parse_heldout_dataset,
)

_DATASET_PATH = (
    Path(__file__).parents[1] / "benchmarks" / "phase2" / "calibration-v1.toml"
)


def _contents() -> str:
    return _DATASET_PATH.read_text(encoding="utf-8")


def test_loads_calibration_families_with_source_and_split_lineage() -> None:
    dataset = load_calibration(_DATASET_PATH)

    assert dataset.schema_version == 1
    assert len(dataset.source_documents) == 13
    assert len(dataset.source_anchors) == 19
    assert len(dataset.families) == 10
    assert {family.split for family in dataset.families} == {"development"}
    unsupported = next(family for family in dataset.families if family.id == "q06")
    assert unsupported.unsupported is True
    assert unsupported.evidence_groups == ()
    assert all(judgment.label < 2 for judgment in unsupported.evidence_judgments)


def test_rejects_duplicate_query_ids() -> None:
    contents = _contents().replace('id = "q02-v1"', 'id = "q01-v1"', 1)

    with pytest.raises(CalibrationLoadError, match="duplicate query ID"):
        parse_calibration(contents)


def test_rejects_a_family_assigned_to_multiple_splits() -> None:
    contents = _contents().replace(
        'id = "q02"\nsplit = "development"',
        'id = "q01"\nsplit = "held_out"',
        1,
    )

    with pytest.raises(CalibrationLoadError, match="must not overlap splits"):
        parse_calibration(contents)


def test_rejects_unknown_source_anchor_references() -> None:
    contents = _contents().replace(
        'source_anchor_id = "b-table7"',
        'source_anchor_id = "missing-anchor"',
        1,
    )

    with pytest.raises(CalibrationLoadError, match="unknown anchor"):
        parse_calibration(contents)


def test_rejects_empty_required_evidence_pieces() -> None:
    contents = _contents().replace(
        'required_pieces = [["b-table7"]]', "required_pieces = []", 1
    )

    with pytest.raises(CalibrationLoadError, match="required_pieces must not be empty"):
        parse_calibration(contents)


def test_rejects_evidence_groups_that_reference_non_direct_judgments() -> None:
    contents = _contents().replace(
        'required_pieces = [["b-table7"]]',
        'required_pieces = [["cc-abstract"]]',
        1,
    )

    with pytest.raises(CalibrationLoadError, match="must have label-2 evidence"):
        parse_calibration(contents)


def test_rejects_unreviewed_judgments() -> None:
    contents = _contents().replace(
        'reviewer_status = "assistant_reviewed"',
        'reviewer_status = "human_verified"',
        1,
    )

    with pytest.raises(CalibrationLoadError, match="must be assistant_reviewed"):
        parse_calibration(contents)


def test_rejects_invalid_search_filters() -> None:
    contents = _contents().replace(
        "year_from = 2024, year_to = 2024",
        "year_from = 2025, year_to = 2024",
        1,
    )

    with pytest.raises(CalibrationLoadError, match="year_from must be less than"):
        parse_calibration(contents)


def test_rejects_unknown_manifest_fields() -> None:
    contents = _contents().replace(
        'dataset_kind = "calibration"',
        'dataset_kind = "calibration"\nextra_field = true',
        1,
    )

    with pytest.raises(CalibrationLoadError, match="unknown fields: extra_field"):
        parse_calibration(contents)


def test_calibration_families_must_remain_in_development() -> None:
    contents = _contents().replace(
        'id = "q10"\nsplit = "development"',
        'id = "q10"\nsplit = "held_out"',
        1,
    )

    with pytest.raises(
        CalibrationLoadError, match="must all use the development split"
    ):
        parse_calibration(contents)


def test_evidence_groups_must_match_requires_evidence() -> None:
    contents = _contents().replace(
        "requires_evidence = true", "requires_evidence = false", 1
    )

    with pytest.raises(
        CalibrationLoadError, match="has evidence groups but does not require evidence"
    ):
        parse_calibration(contents)


def _heldout_contents() -> str:
    return (
        _contents()
        .replace('dataset_kind = "calibration"', 'dataset_kind = "held_out"')
        .replace('split = "development"', 'split = "held_out"')
    )


def test_loads_only_heldout_families_from_explicit_heldout_loader(
    tmp_path: Path,
) -> None:
    path = tmp_path / "heldout.toml"
    path.write_text(_heldout_contents(), encoding="utf-8")

    dataset = load_heldout_dataset(path)

    assert dataset.dataset_kind == "held_out"
    assert len(dataset.families) == 10
    assert {family.split for family in dataset.families} == {"held_out"}


def test_heldout_parser_rejects_calibration_kind_and_development_families() -> None:
    with pytest.raises(CalibrationLoadError, match='dataset_kind must be "held_out"'):
        parse_heldout_dataset(_contents())

    mixed = _heldout_contents().replace(
        'id = "q10"\nsplit = "held_out"',
        'id = "q10"\nsplit = "development"',
        1,
    )
    with pytest.raises(CalibrationLoadError, match="must all use the held_out split"):
        parse_heldout_dataset(mixed)


def test_calibration_parser_rejects_heldout_kind() -> None:
    with pytest.raises(
        CalibrationLoadError, match='dataset_kind must be "calibration"'
    ):
        parse_calibration(_heldout_contents())
