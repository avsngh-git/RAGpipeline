"""Tests for the tracked frozen profile manifest."""

from pathlib import Path

import pytest

from research_platform.search.profile_manifest import load_frozen_profile

ROOT = Path(__file__).resolve().parents[1]


def test_frozen_profile_reconstructs_and_verifies_canonical_identity() -> None:
    profile = load_frozen_profile(ROOT / "benchmarks/phase2/frozen-profile-v1.toml")

    assert (
        profile.profile_id
        == "sha256:243e3d5923ee930940a29cf4ba79db2392cf4a5bfe777a54cedd2a316fd22870"
    )
    assert (
        profile.snapshot.chunk_selection_id
        == "sha256:cc5b7c30962ce66ad279a5ff95b0e1e6dd8aede68980292717d1a7a23ecd6f18"
    )
    assert profile.candidate_limits.rerank_top_k == 50
    assert profile.selection_rules.evidence_per_paper_limit == 5
    assert profile.selection_rules.paper_support_limit == 5

    assert (
        profile.dense_index is not None
        and profile.dense_index.index_configuration_id
        == "sha256:21cb8e4df7f24affb524a84a788f275fa54b08076d519afb1ecf5961ac88ee02"
    )


def test_frozen_profile_rejects_changed_acceptance_digest(tmp_path: Path) -> None:
    source = ROOT / "benchmarks/phase2/frozen-profile-v1.toml"
    manifest = tmp_path / source.name
    text = source.read_text(encoding="utf-8")
    manifest.write_text(text, encoding="utf-8")
    (tmp_path / "acceptance-v1.toml").write_text("changed = true\n", encoding="utf-8")

    import re

    text = re.sub(
        r'acceptance_config = "[^"]+"',
        'acceptance_config = "benchmarks/phase2/acceptance-v1.toml"',
        text,
    )
    manifest.write_text(text, encoding="utf-8")

    try:
        load_frozen_profile(manifest)
    except ValueError as error:
        assert "acceptance configuration digest" in str(error)
    else:
        raise AssertionError("changed acceptance configuration should be rejected")


def test_phase2_dense_configuration_isolated_from_phase1() -> None:
    import json

    from research_platform.ingestion.indexing import IndexConfiguration
    from research_platform.search.application import _load_phase2_dense_configuration

    configuration = _load_phase2_dense_configuration(ROOT / "benchmarks/phase2")
    manifest = json.loads(
        (ROOT / "benchmarks/phase2/e5-small-v2-filtered-index-v1.json").read_text(
            encoding="utf-8"
        )
    )

    assert configuration == IndexConfiguration.from_dict(manifest)
    assert configuration.collection_name == "phase2-e5-small-v2-filtered"
    assert configuration.collection_name != "phase1-e5-small-v2"


def test_missing_lexical_artifact_is_a_safe_dependency_failure(
    tmp_path: Path,
) -> None:
    from research_platform.search.application import (
        SearchDependencyUnavailable,
        _load_lexical_artifact,
    )

    profile = load_frozen_profile(ROOT / "benchmarks/phase2/frozen-profile-v1.toml")

    with pytest.raises(SearchDependencyUnavailable, match="artifact is not built"):
        _load_lexical_artifact(tmp_path, profile, "evidence", mmap=False)
