from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def _workflow(path: str) -> dict[Any, Any]:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def test_ci_pushes_only_from_main() -> None:
    workflow = _workflow(".github/workflows/ci.yml")
    steps = workflow["jobs"]["checks"]["steps"]
    push_step = next(step for step in steps if step.get("name") == "Push image to GHCR")
    image_scan_index = next(
        index
        for index, step in enumerate(steps)
        if step.get("name") == "Scan image for vulnerabilities"
    )

    assert push_step["if"] == (
        "github.event_name == 'push' && github.ref == 'refs/heads/main'"
    )
    assert steps.index(push_step) > image_scan_index


def test_ci_job_can_write_packages() -> None:
    workflow = _workflow(".github/workflows/ci.yml")

    assert workflow["jobs"]["checks"]["permissions"] == {
        "contents": "read",
        "packages": "write",
    }


def test_release_runs_on_version_tags() -> None:
    workflow = _workflow(".github/workflows/release.yml")

    assert workflow[True] == {"push": {"tags": ["v*.*.*"]}}


def test_release_never_rebuilds() -> None:
    release_text = Path(".github/workflows/release.yml").read_text(encoding="utf-8")

    assert "imagetools create" in release_text
    assert "docker build " not in release_text
    assert "docker push " not in release_text


def test_release_passes_tag_through_env() -> None:
    workflow = _workflow(".github/workflows/release.yml")
    run_blocks = [
        step["run"] for step in workflow["jobs"]["release"]["steps"] if "run" in step
    ]

    assert all("${{" not in run_block for run_block in run_blocks)
