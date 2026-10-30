"""Contract tests for fetching only the files used by the serving models."""

from __future__ import annotations

import importlib
from types import SimpleNamespace
from typing import Any

import pytest

from research_platform.demo.cli import main


def test_fetch_models_limits_files_for_each_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    def snapshot_download(**options: Any) -> str:
        calls.append(options)
        return "local-snapshot"

    hub = SimpleNamespace(snapshot_download=snapshot_download)
    original = importlib.import_module

    def import_module(name: str, package: str | None = None) -> object:
        if name == "huggingface_hub":
            return hub
        return original(name, package)

    monkeypatch.setattr(
        "research_platform.demo.cli.importlib.import_module", import_module
    )

    main(["fetch-models"])

    assert len(calls) == 2
    for options in calls:
        assert "*.safetensors" in options["allow_patterns"]
        assert "onnx/*" in options["ignore_patterns"]
