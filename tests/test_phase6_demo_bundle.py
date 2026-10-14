"""Unit tests for public demo bundle formatting and command wiring."""

from __future__ import annotations

import hashlib
import importlib
from pathlib import Path
from uuid import uuid4

import pytest
import tomllib

from research_platform.demo.bundle import (
    BUNDLE_FORMAT,
    AttributionRow,
    file_sha256,
    read_manifest,
    render_attribution,
    write_manifest,
)
from research_platform.demo.cli import main
from research_platform.demo.database import DemoLoadRefused


def test_render_attribution_header_and_rows() -> None:
    rows = (
        AttributionRow(
            paper_id="W1",
            title="Paper | One",
            authors=("A", "B", "C", "D"),
            year=2025,
            source="https://doi.org/10.1000/example",
            license_id="cc-by",
        ),
        AttributionRow(
            paper_id="W2",
            title="Second Paper",
            authors=("E",),
            year=None,
            source="https://example.org/paper.pdf",
            license_id="cc0",
        ),
    )

    rendered = render_attribution(rows)

    assert rendered.startswith(
        "# Attribution\n\n"
        "The passages, tables and research answers in this bundle are excerpts extracted from the\n"
        "papers below. Text was extracted from the original PDFs, split into sections and chunks, and\n"
        "tables were converted to rows; no other change was made. Each paper is used under the\n"
        "licence shown. Paper metadata comes from OpenAlex (CC0).\n\n"
        "| Paper | Authors | Year | Source | Licence |\n"
        "| --- | --- | --- | --- | --- |\n"
    )
    assert "Paper \\| One" in rendered
    assert "A, B, C, et al." in rendered
    assert "[CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/)" in rendered
    assert rendered.endswith("\n")


def test_manifest_round_trip_and_format_check(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    manifest: dict[str, object] = {"format": BUNDLE_FORMAT, "bundle_version": "v1"}
    write_manifest(path, manifest)

    assert read_manifest(path) == manifest

    write_manifest(path, {"format": "other"})
    with pytest.raises(DemoLoadRefused):
        read_manifest(path)


def test_file_sha256_prefix(tmp_path: Path) -> None:
    path = tmp_path / "small.bin"
    path.write_bytes(b"bundle")

    assert file_sha256(path) == "sha256:" + hashlib.sha256(b"bundle").hexdigest()


def test_export_refuses_an_existing_output_directory(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as error:
        main(
            [
                "export",
                "--snapshot-id",
                str(uuid4()),
                "--run-principal",
                "demo",
                "--output",
                str(tmp_path),
            ]
        )

    assert error.value.code == 1


def test_fetch_models_without_huggingface_hub_exits_2(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = importlib.import_module

    def import_module(name: str, package: str | None = None) -> object:
        if name == "huggingface_hub":
            raise ModuleNotFoundError(name)
        return original(name, package)

    monkeypatch.setattr(
        "research_platform.demo.cli.importlib.import_module", import_module
    )

    with pytest.raises(SystemExit) as error:
        main(["fetch-models"])

    assert error.value.code == 2


def test_research_demo_script_is_declared() -> None:
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert project["project"]["scripts"]["research-demo"] == (
        "research_platform.demo.cli:main"
    )
