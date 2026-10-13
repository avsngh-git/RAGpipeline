from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
import tomllib

from research_platform.persistence.migrations import (
    MIGRATIONS_DIR,
    MIGRATIONS_DIR_ENV,
    MigrationsNotFound,
    apply_migrations,
    default_migrations_dir,
)


def test_default_is_the_source_checkout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(MIGRATIONS_DIR_ENV, raising=False)

    assert default_migrations_dir() == MIGRATIONS_DIR
    assert (MIGRATIONS_DIR / "028_run_ingestion_permission.sql").is_file()


def test_environment_overrides_the_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(MIGRATIONS_DIR_ENV, str(tmp_path))

    assert default_migrations_dir() == tmp_path


def test_empty_directory_refuses_before_connecting(tmp_path: Path) -> None:
    with pytest.raises(MigrationsNotFound):
        asyncio.run(apply_migrations("postgresql://unused.invalid/x", tmp_path))


def test_research_migrate_script_is_declared() -> None:
    project_root = Path(__file__).resolve().parents[1]
    pyproject = tomllib.loads((project_root / "pyproject.toml").read_text())

    assert (
        pyproject["project"]["scripts"]["research-migrate"]
        == "research_platform.persistence.migrations:main"
    )


def test_dockerfile_ships_migrations() -> None:
    project_root = Path(__file__).resolve().parents[1]
    dockerfile = (project_root / "Dockerfile").read_text()

    assert "COPY migrations ./migrations" in dockerfile
    assert "ENV RESEARCH_PLATFORM_MIGRATIONS_DIR=/app/migrations" in dockerfile
