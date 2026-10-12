"""Each MCP module imports on its own, without an import cycle."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
_MODULES = sorted(
    f"research_platform.mcp.{path.stem}"
    for path in (_SRC / "research_platform" / "mcp").glob("*.py")
    if path.stem != "__init__"
)


@pytest.mark.parametrize("module", _MODULES)
def test_module_imports_in_a_fresh_interpreter(module: str) -> None:
    result = subprocess.run(
        [sys.executable, "-c", f"import {module}"],
        capture_output=True,
        text=True,
        check=False,
        env={"PYTHONPATH": str(_SRC), "PATH": ""},
    )
    assert result.returncode == 0, result.stderr[-2000:]


def test_modules_were_found() -> None:
    assert "research_platform.mcp.server" in _MODULES
