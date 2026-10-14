from __future__ import annotations

import os
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "demo_load.sh"


def test_api_service_is_configured_for_small_mode() -> None:
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    api = compose["services"]["api"]

    assert api["image"].startswith(
        "${RESEARCH_PLATFORM_IMAGE:-ghcr.io/avsngh-git/ragpipeline:"
    )
    assert "build" in api
    assert api["environment"]["RESEARCH_PLATFORM_EVIDENCE_ACCESS_PROFILE"] == (
        "trusted_private_local"
    )
    assert api["environment"]["HF_HOME"] == "/models/hf"
    assert "model_cache:/models" in api["volumes"]
    assert "./demo-data:/demo-data:ro" in api["volumes"]
    assert api["healthcheck"]


def test_ports_stay_on_loopback() -> None:
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))

    for service in compose["services"].values():
        for port in service.get("ports", []):
            published_port = port if isinstance(port, str) else port["published"]
            assert str(published_port).startswith("127.0.0.1:")


def test_demo_load_script_is_strict_and_executable() -> None:
    script = SCRIPT.read_text(encoding="utf-8")

    assert script.startswith("#!/usr/bin/env bash")
    assert "set -euo pipefail" in script
    assert "sha256sum -c" in script
    assert "research-migrate" in script
    assert "research-demo load" in script
    assert "research-demo fetch-models" in script
    assert "--principal demo --scope read" in script
    assert os.access(SCRIPT, os.X_OK)


def test_demo_load_never_prints_the_key() -> None:
    script = SCRIPT.read_text(encoding="utf-8")

    assert not any(
        ("echo" in line and "api_key" in line) or "cat demo-data/api-key" in line
        for line in script.splitlines()
    )


def test_demo_data_is_ignored() -> None:
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")

    assert "/demo-data/" in ignore


def test_demo_load_help_runs() -> None:
    result = subprocess.run(
        ["bash", str(SCRIPT), "--help"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
