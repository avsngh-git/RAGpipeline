"""Each run records the installed PyTorch build, the same in every process."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

from research_platform.runs import runner


def _fake_torch(
    tmp_path: Path, version_line: str | None
) -> importlib.machinery.ModuleSpec:
    package = tmp_path / "torch"
    package.mkdir()
    if version_line is not None:
        (package / "version.py").write_text(version_line + "\ncuda = '13.0'\n")
    spec = importlib.machinery.ModuleSpec("torch", None, is_package=True)
    spec.submodule_search_locations = [str(package)]
    return spec


def test_version_comes_from_torch_version_file_with_cuda_label(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = _fake_torch(tmp_path, "__version__ = '2.14.0+cu130'")
    monkeypatch.setattr(runner.importlib.util, "find_spec", lambda _name: spec)

    assert runner.torch_version() == "2.14.0+cu130"


def test_without_torch_installed_the_version_is_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runner.importlib.util, "find_spec", lambda _name: None)

    assert runner.torch_version() is None


def test_reading_the_version_does_not_import_torch() -> None:
    code = (
        "import sys; from research_platform.runs.runner import torch_version; "
        "torch_version(); print('torch' in sys.modules)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )

    assert result.stdout.strip() == "False"
