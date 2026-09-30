"""Input guards for the development-only Phase 2 timing harness."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.phase2_dev_benchmark import _load_cases, _response_fingerprint

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "benchmarks/phase2/phase2-synthetic-development-inputs-v1.json"
ALLOWLIST = ROOT / "benchmarks/phase2/phase2-dev-input-allowlist-v1.json"


def test_synthetic_fixture_is_allowlisted_and_contains_required_mix() -> None:
    dataset, cases = _load_cases(FIXTURE, ALLOWLIST)

    assert dataset["dataset_kind"] == "synthetic_development_diagnostic"
    assert len(cases) == 10
    assert {case["operation"] for case in cases} == {
        "paper_search",
        "evidence_search",
    }
    assert {case["category"] for case in cases} == {
        "discovery",
        "cross-paper-comparison",
        "table",
        "restrictive-filter",
        "zero-eligibility",
    }


def test_spent_family_and_unknown_heldout_input_are_rejected(tmp_path: Path) -> None:
    cases = [
        {
            "query_id": "q20",
            "family_id": "q20",
            "category": "discovery",
            "query": "synthetic excluded query",
            "operation": "paper_search",
            "filters": {},
            "limit": 10,
        }
    ]
    dataset = {
        "schema_version": 1,
        "dataset_kind": "reviewed_development",
        "split": "development",
        "split_policy_id": "phase2-benchmark-v3",
        "question_manifest_sha256": "questions",
        "split_manifest_sha256": "split",
        "cases": cases,
    }
    allowlist = {
        "schema_version": 1,
        "synthetic_diagnostic": {},
        "reviewed_development": {
            "split_policy_id": "phase2-benchmark-v3",
            "question_manifest_sha256": "questions",
            "split_manifest_sha256": "split",
            "allowed_family_ids": ["q20"],
            "excluded_family_ids": ["q20", "q21"],
        },
    }
    input_path = tmp_path / "inputs.json"
    allowlist_path = tmp_path / "allowlist.json"
    input_path.write_text(json.dumps(dataset), encoding="utf-8")
    allowlist_path.write_text(json.dumps(allowlist), encoding="utf-8")

    with pytest.raises(ValueError, match="q20 and q21 are excluded"):
        _load_cases(input_path, allowlist_path)

    dataset["dataset_kind"] = "heldout"
    input_path.write_text(json.dumps(dataset), encoding="utf-8")
    with pytest.raises(ValueError, match="unrecognized input kinds"):
        _load_cases(input_path, allowlist_path)


def test_response_fingerprint_hashes_content_without_emitting_it() -> None:
    sensitive_response = {"request_id": "random", "hits": [{"text": "secret passage"}]}

    first = _response_fingerprint(sensitive_response)
    second = _response_fingerprint(
        {"request_id": "different", "hits": [{"text": "secret passage"}]}
    )

    assert first == second
    assert "secret passage" not in first
