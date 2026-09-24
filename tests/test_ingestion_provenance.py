"""Tests for reproducible source-code provenance."""

from __future__ import annotations

import subprocess
from pathlib import Path

from research_platform.ingestion.provenance import code_revision


def _git(path: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _repository(path: Path) -> str:
    _git(path, "init", "--quiet")
    _git(path, "config", "user.name", "Phase 1 tests")
    _git(path, "config", "user.email", "phase1-tests@example.invalid")
    (path / ".gitignore").write_text("*.cache\n", encoding="utf-8")
    (path / "source.py").write_text("VALUE = 1\n", encoding="utf-8")
    _git(path, "add", ".gitignore", "source.py")
    _git(path, "commit", "--quiet", "-m", "initial")
    return _git(path, "rev-parse", "HEAD")


def test_code_revision_distinguishes_tracked_and_untracked_source_changes(
    tmp_path: Path, monkeypatch
) -> None:
    head = _repository(tmp_path)
    monkeypatch.chdir(tmp_path)

    clean_revision = code_revision()
    assert clean_revision == head

    (tmp_path / "source.py").write_text("VALUE = 2\n", encoding="utf-8")
    tracked_revision = code_revision()
    assert tracked_revision.startswith(f"{head}+dirty.sha256:")
    assert tracked_revision != clean_revision

    (tmp_path / "new_module.py").write_text("VALUE = 3\n", encoding="utf-8")
    untracked_revision = code_revision()
    assert untracked_revision.startswith(f"{head}+dirty.sha256:")
    assert untracked_revision != tracked_revision


def test_code_revision_ignores_git_ignored_generated_files(
    tmp_path: Path, monkeypatch
) -> None:
    _repository(tmp_path)
    monkeypatch.chdir(tmp_path)

    source_revision = code_revision()
    (tmp_path / "download.cache").write_bytes(b"generated artifact")

    assert code_revision() == source_revision
