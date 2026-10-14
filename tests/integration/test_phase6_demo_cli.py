"""The research-demo command against a real PostgreSQL connection."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from urllib.parse import urlparse

import pytest

from research_platform.demo.bundle import BUNDLE_FORMAT, file_sha256, write_manifest
from research_platform.demo.cli import main
from research_platform.persistence.migrations import apply_migrations

TEST_DATABASE_URL = os.environ.get("RESEARCH_PLATFORM_TEST_DATABASE_URL")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not TEST_DATABASE_URL,
        reason="requires the dedicated disposable PostgreSQL service",
    ),
]


def test_load_connects_and_checks_the_schema_version(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert TEST_DATABASE_URL is not None
    assert urlparse(TEST_DATABASE_URL).path.removeprefix("/") == "research_test"
    asyncio.run(apply_migrations(TEST_DATABASE_URL))
    monkeypatch.setenv("RESEARCH_PLATFORM_DATABASE_URL", TEST_DATABASE_URL)
    attribution = tmp_path / "ATTRIBUTION.md"
    attribution.write_text("# Attribution\n", encoding="utf-8")
    write_manifest(
        tmp_path / "manifest.json",
        {
            "format": BUNDLE_FORMAT,
            "schema_version": "000_not_a_migration",
            "attribution": {
                "path": "ATTRIBUTION.md",
                "sha256": file_sha256(attribution),
            },
            "postgres": [],
            "qdrant": [],
            "runs": [],
        },
    )

    with pytest.raises(SystemExit) as exit_info:
        main(["load", "--bundle", str(tmp_path)])

    assert exit_info.value.code == 1
    assert "schema version differs" in capsys.readouterr().err
