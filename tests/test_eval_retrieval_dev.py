"""Contract tests for the development retrieval experiment suite."""

from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from research_platform.evaluation.experiments import file_sha256
from research_platform.evaluation.suites.retrieval_dev import (
    RetrievalDevSuite,
    _item_from_record,
    _parse_datasets,
    _profile_id,
    summarize,
)


def test_parse_datasets_pairs() -> None:
    assert _parse_datasets("cal.toml:align.toml, other.toml:other-align.toml") == (
        (Path("cal.toml"), Path("align.toml")),
        (Path("other.toml"), Path("other-align.toml")),
    )


@pytest.mark.parametrize("value", ["", "cal.toml", ":align.toml", "cal.toml:", "a:b:c"])
def test_parse_datasets_rejects_malformed(value: str) -> None:
    with pytest.raises(ValueError):
        _parse_datasets(value)


def test_profile_id_required_and_validated() -> None:
    valid = f"sha256:{'a' * 64}"
    assert _profile_id({"profile_id": valid}) == valid
    for options in ({}, {"profile_id": "sha256:ABC"}, {"profile_id": "a" * 64}):
        with pytest.raises(ValueError):
            _profile_id(options)


def test_dataset_identity_is_stable(tmp_path: Path) -> None:
    calibration = tmp_path / "calibration-v1.toml"
    alignment = tmp_path / "alignment-v1.toml"
    calibration.write_text("calibration", encoding="utf-8")
    alignment.write_text("alignment", encoding="utf-8")
    options = {"datasets": f"{calibration}:{alignment}"}

    identity = RetrievalDevSuite().dataset(options)

    expected = hashlib.sha256(
        (file_sha256(calibration) + file_sha256(alignment)).encode("ascii")
    ).hexdigest()
    assert identity.name == "retrieval-development"
    assert identity.version == "calibration-v1"
    assert identity.sha256 == expected
    assert RetrievalDevSuite().dataset(options) == identity


def test_summarize_macro_means() -> None:
    records = [
        {
            "failed_attempts": 1,
            "paper": {
                "ndcg_at_10": 0.2,
                "direct_mrr_at_10": 0.4,
                "judged_recall_at_20": None,
                "judged_recall_at_50": None,
                "judgment_coverage": None,
            },
            "evidence": {
                "ndcg_at_10": 0.6,
                "direct_mrr_at_10": None,
                "judged_recall_at_20": None,
                "judged_recall_at_50": None,
                "judgment_coverage": None,
            },
        },
        {
            "failed_attempts": 0,
            "paper": {
                "ndcg_at_10": 0.8,
                "direct_mrr_at_10": None,
                "judged_recall_at_20": None,
                "judged_recall_at_50": None,
                "judgment_coverage": None,
            },
            "evidence": {
                "ndcg_at_10": None,
                "direct_mrr_at_10": 0.5,
                "judged_recall_at_20": None,
                "judged_recall_at_50": None,
                "judgment_coverage": None,
            },
        },
    ]

    metrics = summarize(records)

    assert metrics["queries"] == 2
    assert metrics["paper_ndcg_at_10"] == pytest.approx(0.5)
    assert metrics["paper_ndcg_at_10_queries"] == 2
    assert metrics["paper_direct_mrr_at_10"] == pytest.approx(0.4)
    assert metrics["paper_direct_mrr_at_10_queries"] == 1
    assert metrics["evidence_ndcg_at_10"] == pytest.approx(0.6)
    assert metrics["evidence_ndcg_at_10_queries"] == 1
    assert metrics["evidence_direct_mrr_at_10"] == pytest.approx(0.5)
    assert metrics["evidence_direct_mrr_at_10_queries"] == 1
    assert metrics["failed_attempts"] == 1


def test_item_from_record() -> None:
    score = SimpleNamespace(
        paper=SimpleNamespace(
            ndcg_at_10=SimpleNamespace(value=0.1),
            direct_mrr_at_10=SimpleNamespace(value=0.2),
            judged_recall_at_20=SimpleNamespace(value=0.3),
            judged_recall_at_50=SimpleNamespace(value=0.4),
            judgment_coverage=SimpleNamespace(value=0.5),
        ),
        evidence=SimpleNamespace(
            ndcg_at_10=SimpleNamespace(value=0.6),
            direct_mrr_at_10=SimpleNamespace(value=0.7),
            judged_recall_at_20=SimpleNamespace(value=0.8),
            judged_recall_at_50=SimpleNamespace(value=0.9),
            judgment_coverage=SimpleNamespace(value=1.0),
        ),
    )
    record = SimpleNamespace(
        family_id="family-1",
        query_id="query-1",
        score=score,
        attempts=[
            SimpleNamespace(status="failed"),
            SimpleNamespace(status="succeeded"),
        ],
    )

    assert _item_from_record(record) == {
        "item_id": "family-1:query-1",
        "family_id": "family-1",
        "query_id": "query-1",
        "failed_attempts": 1,
        "paper": {
            "ndcg_at_10": 0.1,
            "direct_mrr_at_10": 0.2,
            "judged_recall_at_20": 0.3,
            "judged_recall_at_50": 0.4,
            "judgment_coverage": 0.5,
        },
        "evidence": {
            "ndcg_at_10": 0.6,
            "direct_mrr_at_10": 0.7,
            "judged_recall_at_20": 0.8,
            "judged_recall_at_50": 0.9,
            "judgment_coverage": 1.0,
        },
    }
    unscored = SimpleNamespace(
        family_id="family-2",
        query_id="query-2",
        score=None,
        attempts=[],
    )
    item = _item_from_record(unscored)
    assert item["paper"] is None
    assert item["evidence"] is None
