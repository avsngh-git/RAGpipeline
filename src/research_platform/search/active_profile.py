"""Resolve the one tracked Phase 2 active-profile reference."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import tomllib

ACTIVE_PROFILE_POINTER_FILENAME = "active-profile.toml"
PROFILE_OVERRIDE_ENV = "RESEARCH_PLATFORM_PHASE2_PROFILE"


def resolve_frozen_profile_path(
    path: Path | None = None, *, repository_root: Path | None = None
) -> Path:
    """Resolve an active pointer or return an explicitly selected frozen manifest.

    With no explicit path, RESEARCH_PLATFORM_PHASE2_PROFILE may name a manifest (for
    measuring a candidate profile); otherwise the tracked active pointer is used.
    """
    override = os.environ.get(PROFILE_OVERRIDE_ENV)
    if path is None and override:
        path = Path(override)
    selected = (
        Path(path) if path is not None else _default_active_pointer(repository_root)
    )
    if selected.name != ACTIVE_PROFILE_POINTER_FILENAME:
        return selected
    try:
        raw = tomllib.loads(selected.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        raise ValueError("active Phase 2 profile pointer is unreadable") from None
    if raw.get("schema_version") != 1:
        raise ValueError("active Phase 2 profile pointer schema is unsupported")
    manifest_name = raw.get("profile_manifest")
    expected_profile_id = raw.get("profile_id")
    expected_sha256 = raw.get("profile_manifest_sha256")
    if (
        not isinstance(manifest_name, str)
        or Path(manifest_name).name != manifest_name
        or not manifest_name.startswith("frozen-profile-")
        or not manifest_name.endswith(".toml")
        or not isinstance(expected_profile_id, str)
        or not expected_profile_id.startswith("sha256:")
        or not isinstance(expected_sha256, str)
        or not expected_sha256.startswith("sha256:")
    ):
        raise ValueError("active Phase 2 profile pointer is malformed")
    manifest_path = selected.parent / manifest_name
    try:
        manifest_bytes = manifest_path.read_bytes()
    except OSError:
        raise ValueError("active Phase 2 frozen profile is missing") from None
    actual_sha256 = "sha256:" + hashlib.sha256(manifest_bytes).hexdigest()
    if actual_sha256 != expected_sha256:
        raise ValueError("active Phase 2 profile manifest digest differs")
    manifest = tomllib.loads(manifest_bytes.decode("utf-8"))
    if manifest.get("profile_id") != expected_profile_id:
        raise ValueError("active Phase 2 profile identity differs")
    return manifest_path


def _default_active_pointer(repository_root: Path | None) -> Path:
    roots = []
    if repository_root is not None:
        roots.append(Path(repository_root))
    roots.extend((Path.cwd(), Path(__file__).resolve().parents[3]))
    candidates = [
        root / "benchmarks" / "phase2" / ACTIVE_PROFILE_POINTER_FILENAME
        for root in dict.fromkeys(roots)
    ]
    return next(
        (candidate for candidate in candidates if candidate.is_file()), candidates[0]
    )
