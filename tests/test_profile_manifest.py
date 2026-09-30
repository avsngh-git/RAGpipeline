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


def test_active_profile_pointer_is_shared_by_runtime_cli_and_image() -> None:
    from research_platform.ingestion.cli import _load_retrieval_profile
    from research_platform.search.active_profile import (
        ACTIVE_PROFILE_POINTER_FILENAME,
        resolve_frozen_profile_path,
    )

    pointer_path = ROOT / "benchmarks/phase2" / ACTIVE_PROFILE_POINTER_FILENAME
    manifest_path = resolve_frozen_profile_path(pointer_path)
    runtime_profile = load_frozen_profile(manifest_path)
    cli_profile = _load_retrieval_profile(pointer_path)
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")

    assert manifest_path.name == "frozen-profile-v9.toml"
    assert cli_profile.profile_id == runtime_profile.profile_id
    assert runtime_profile.profile_id == (
        "sha256:959e24b6ff6de711bbdfbf5020c5ac82a91cce43f48c8f52ba9d214c3e00e9be"
    )
    assert runtime_profile.candidate_limits.rerank_top_k == 16
    assert "acceptance-v9.toml" in manifest_path.read_text(encoding="utf-8")
    assert ACTIVE_PROFILE_POINTER_FILENAME in dockerfile
    assert "frozen-profile-v9.toml" in dockerfile
    assert "acceptance-v9.toml" in dockerfile
    assert f"!benchmarks/phase2/{ACTIVE_PROFILE_POINTER_FILENAME}" in dockerignore


def test_default_active_profile_resolves_from_runtime_bundle_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import shutil

    from research_platform.search.active_profile import resolve_frozen_profile_path

    benchmark_dir = tmp_path / "benchmarks" / "phase2"
    benchmark_dir.mkdir(parents=True)
    for name in ("active-profile.toml", "frozen-profile-v9.toml"):
        shutil.copyfile(ROOT / "benchmarks/phase2" / name, benchmark_dir / name)
    monkeypatch.chdir(tmp_path)

    assert resolve_frozen_profile_path() == benchmark_dir / "frozen-profile-v9.toml"


def test_active_profile_pointer_rejects_a_changed_manifest_digest(
    tmp_path: Path,
) -> None:
    import shutil

    from research_platform.search.active_profile import resolve_frozen_profile_path

    benchmark_dir = tmp_path / "benchmarks" / "phase2"
    benchmark_dir.mkdir(parents=True)
    shutil.copyfile(
        ROOT / "benchmarks/phase2/frozen-profile-v9.toml",
        benchmark_dir / "frozen-profile-v9.toml",
    )
    pointer = (ROOT / "benchmarks/phase2/active-profile.toml").read_text(
        encoding="utf-8"
    )
    (benchmark_dir / "active-profile.toml").write_text(
        pointer.replace("sha256:", "sha256:0", 1), encoding="utf-8"
    )

    with pytest.raises(ValueError, match="manifest digest differs"):
        resolve_frozen_profile_path(
            benchmark_dir / "active-profile.toml", repository_root=tmp_path
        )


def test_ettin_dev_profile_loads_but_is_not_frozen_or_active() -> None:
    from research_platform.search.profile_manifest import (
        load_retrieval_profile_manifest,
    )
    from research_platform.search.reranker_models import (
        validate_supported_reranker_identity,
    )

    path = ROOT / "benchmarks/phase2/dev-profile-ettin150m-v1.toml"
    profile = load_retrieval_profile_manifest(path)

    assert profile.reranker is not None
    assert profile.reranker.model == "cross-encoder/ettin-reranker-150m-v1"
    assert profile.reranker.maximum_input_tokens == 2048
    assert profile.reranker.precision == "fp16"
    assert profile.candidate_limits.rerank_top_k == 16
    validate_supported_reranker_identity(profile.reranker)
    with pytest.raises(ValueError, match="not frozen"):
        load_frozen_profile(path)
    active = (ROOT / "benchmarks/phase2/active-profile.toml").read_text("utf-8")
    assert "ettin" not in active


def test_fp32_precision_keeps_the_frozen_profile_identity() -> None:
    profile = load_frozen_profile(ROOT / "benchmarks/phase2/frozen-profile-v9.toml")

    assert profile.reranker is not None and profile.reranker.precision == "fp32"
    assert "precision" not in profile.to_dict()["reranker"]  # type: ignore[index]


def test_serving_profiles_for_v9_keep_the_e5_stack() -> None:
    from research_platform.search.application import _resolve_serving_profiles

    serving = _resolve_serving_profiles(
        ROOT / "benchmarks/phase2/frozen-profile-v9.toml"
    )

    assert serving.configuration.collection_name == "phase2-e5-small-v2-filtered"
    assert serving.hybrid is serving.lexical_source
    assert serving.hybrid.profile_id == (
        "sha256:29cc1cc6a9b78758f518d76df391859433b9cd034b9ef1f71f8ede30009cb5fa"
    )
    assert serving.dense.lexical_index is None and serving.dense.reranker is None


def test_serving_profiles_for_v10_build_gte_stack_and_reuse_bm25() -> None:
    from research_platform.search.application import _resolve_serving_profiles

    serving = _resolve_serving_profiles(
        ROOT / "benchmarks/phase2/frozen-profile-v10.toml"
    )

    assert serving.configuration.collection_name == "phase2-dev-gte-modernbert-base-v1"
    assert serving.configuration.vector_size == 768
    assert serving.frozen.reranker is not None
    assert serving.frozen.reranker.precision == "fp16"
    assert serving.hybrid.reranker is None
    assert serving.hybrid.candidate_limits.rerank_top_k is None
    assert serving.hybrid.profile_id != serving.lexical_source.profile_id
    assert serving.hybrid.lexical_index == serving.lexical_source.lexical_index
    assert serving.dense.dense_index == serving.frozen.dense_index
    assert serving.dense.profile_id != serving.hybrid.profile_id


def test_v10_rejects_unpinned_dense_identity(tmp_path: Path) -> None:
    import shutil

    from research_platform.search.application import (
        SearchDependencyUnavailable,
        _resolve_serving_profiles,
    )

    benchmark_dir = tmp_path / "phase2"
    shutil.copytree(ROOT / "benchmarks/phase2", benchmark_dir)
    path = benchmark_dir / "frozen-profile-v10.toml"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "gte-modernbert-base:no-prefix", "gte-modernbert-base:other-prefix"
        ),
        encoding="utf-8",
    )

    with pytest.raises((SearchDependencyUnavailable, ValueError)):
        _resolve_serving_profiles(path)


def test_profile_env_override_selects_candidate_without_changing_active(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from research_platform.search.active_profile import (
        PROFILE_OVERRIDE_ENV,
        resolve_frozen_profile_path,
    )

    candidate = ROOT / "benchmarks/phase2/frozen-profile-v10.toml"
    monkeypatch.setenv(PROFILE_OVERRIDE_ENV, str(candidate))

    assert resolve_frozen_profile_path() == candidate
    assert resolve_frozen_profile_path(
        ROOT / "benchmarks/phase2/active-profile.toml"
    ).name == ("frozen-profile-v9.toml")


def _fake_loader(calls: list[tuple[str, str]]):
    from research_platform.search.lexical import (
        BM25_SCORING_SETTINGS,
        SCIENTIFIC_BM25_IDENTITY,
        BuiltLexicalIndex,
        LexicalIndexManifest,
    )

    def load(profile, role):
        calls.append((profile.profile_id, role))
        manifest = LexicalIndexManifest(
            role=role,
            snapshot_status="finalized",
            snapshot=profile.snapshot,
            profile_id=profile.profile_id,
            lexical_index_id=SCIENTIFIC_BM25_IDENTITY.configuration_id,
            row_count=0,
            candidate_limit=profile.candidate_limits.lexical_top_k,
            empty_token_row_count=0,
            duplicate_content_row_count=0,
            row_map_sha256="sha256:" + "0" * 64,
            scoring=BM25_SCORING_SETTINGS,
        )
        return BuiltLexicalIndex(profile, manifest, (), None)

    return load


def test_v10_lexical_retrievers_are_rebound_to_the_gte_hybrid_profile() -> None:
    from research_platform.search.application import (
        _build_lexical_retrievers,
        _resolve_serving_profiles,
    )

    serving = _resolve_serving_profiles(
        ROOT / "benchmarks/phase2/frozen-profile-v10.toml"
    )
    calls: list[tuple[str, str]] = []
    evidence, papers = _build_lexical_retrievers(serving, _fake_loader(calls))

    hybrid = serving.hybrid
    retriever = evidence[hybrid.profile_id]
    # HybridEvidenceSearch requires both to equal the requested profile.
    assert retriever.profile == hybrid
    assert retriever.manifest.profile_id == hybrid.profile_id
    assert papers[hybrid.profile_id].profile == hybrid
    assert papers[serving.frozen.profile_id].manifest.role == "paper"
    # Artifacts are still loaded under the legacy profile they were built for.
    assert (serving.lexical_source.profile_id, "evidence") in calls
    assert evidence[serving.bm25.profile_id].profile == serving.bm25


def test_v9_lexical_retrievers_keep_the_built_profile() -> None:
    from research_platform.search.application import (
        _build_lexical_retrievers,
        _resolve_serving_profiles,
    )

    serving = _resolve_serving_profiles(
        ROOT / "benchmarks/phase2/frozen-profile-v9.toml"
    )
    evidence, _ = _build_lexical_retrievers(serving, _fake_loader([]))

    assert evidence[serving.hybrid.profile_id].profile is serving.hybrid
