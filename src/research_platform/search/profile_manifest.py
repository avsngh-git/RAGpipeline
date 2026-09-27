"""Load and verify tracked Phase 2 retrieval profile manifests."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import cast

import tomllib

from research_platform.search.profiles import RetrievalProfile


def _section(raw: dict[str, object], name: str) -> dict[str, object] | None:
    value = raw.get(name)
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError(f"profile manifest {name} section is malformed")
    return dict(value)


def _optional_limit(value: object, name: str) -> int | None:
    if value == "disabled":
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"profile manifest {name} must be an integer or disabled")
    return value


def _profile_from_manifest(raw: dict[str, object]) -> RetrievalProfile:
    """Construct a canonical RetrievalProfile from shared TOML sections."""
    try:
        if raw["schema_version"] != 1:
            raise ValueError("unsupported profile manifest schema")
        snapshot_section = _section(raw, "snapshot")
        if snapshot_section is None:
            raise ValueError("profile manifest has no snapshot section")
        snapshot = {
            "snapshot_id": raw["snapshot_id"],
            "snapshot_configuration_id": snapshot_section["configuration_id"],
            "chunk_selection_id": raw["snapshot_selection_identity"],
        }
        lexical_raw = _section(raw, "lexical")
        expected_lexical_id: object = None
        if lexical_raw is not None:
            expected_lexical_id = lexical_raw.pop("index_configuration_id")
            lexical_raw["implementation_revision"] = lexical_raw.pop("revision")
        dense_raw = _section(raw, "embedding")
        reranker_section = _section(raw, "reranker")
        reranker_data = None
        if reranker_section is not None:
            reranker_data = {
                "model": reranker_section["model"],
                "revision": reranker_section["revision"],
                "preprocessing_revision": reranker_section["preprocessing_revision"],
                "maximum_input_tokens": reranker_section["maximum_pair_tokens"],
            }
        limits_raw = _section(raw, "candidate_limits")
        selection_raw = _section(raw, "selection")
        if limits_raw is None or selection_raw is None:
            raise ValueError("profile manifest omits candidate or selection rules")
        limits = {
            name: _optional_limit(limits_raw.get(name), name)
            for name in (
                "lexical_top_k",
                "dense_top_k",
                "fused_top_k",
                "rerank_top_k",
            )
        }
        fusion_raw = _section(raw, "fusion")
        profile_data = {
            "schema_version": 2,
            "snapshot": snapshot,
            "lexical_index": lexical_raw,
            "dense_index": dense_raw,
            "reranker": reranker_data,
            "fusion": fusion_raw,
            "candidate_limits": limits,
            "selection_rules": selection_raw,
        }
        profile = RetrievalProfile.from_dict(profile_data)
        if profile.profile_id != raw["profile_id"]:
            raise ValueError("profile identity does not match its settings")
        if (
            profile.lexical_index.configuration_id
            if profile.lexical_index is not None
            else None
        ) != expected_lexical_id:
            raise ValueError("lexical identity does not match its settings")
        if str(profile.snapshot.snapshot_id) != raw["snapshot_id"]:
            raise ValueError("snapshot identity is inconsistent")
        if profile.snapshot.chunk_selection_id != raw["snapshot_selection_identity"]:
            raise ValueError("snapshot selection identity is inconsistent")
    except (KeyError, TypeError, OSError) as error:
        raise ValueError("profile manifest is incomplete") from error
    return profile


def load_retrieval_profile_manifest(path: Path) -> RetrievalProfile:
    """Load a tracked TOML profile and verify its canonical identity."""
    manifest_path = Path(path)
    try:
        raw = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        raise ValueError("retrieval profile manifest is unreadable") from None
    return _profile_from_manifest(raw)


def load_frozen_profile(path: Path) -> RetrievalProfile:
    """Load the selected profile and verify the acceptance freeze digest."""
    manifest_path = Path(path)
    try:
        raw = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        raise ValueError("frozen profile manifest is unreadable") from None
    profile = _profile_from_manifest(raw)
    try:
        if raw["status"] != "frozen_for_implementation_and_heldout":
            raise ValueError("profile manifest is not frozen")
        comparisons = cast(dict[str, str], raw["comparison_profiles"])
        if comparisons.get("reranked_minilm_hybrid") != profile.profile_id:
            raise ValueError("selected comparison does not match the frozen profile")
        acceptance_path = manifest_path.parent / Path(raw["acceptance_config"]).name
        expected_acceptance = raw["acceptance_config_sha256"]
        actual_acceptance = (
            "sha256:" + hashlib.sha256(acceptance_path.read_bytes()).hexdigest()
        )
        if expected_acceptance != actual_acceptance:
            raise ValueError("acceptance configuration digest differs from the freeze")
    except (KeyError, TypeError, OSError) as error:
        raise ValueError("frozen profile manifest is incomplete") from error
    return profile
