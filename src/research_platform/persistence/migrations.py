"""Apply pending PostgreSQL migrations safely and exactly once."""

import asyncio
import os
from pathlib import Path
from typing import Final

import asyncpg  # type: ignore[import-untyped]

from research_platform.config import Settings
from research_platform.runs.checkpointing import setup_checkpoints

MIGRATIONS_DIR = Path(__file__).resolve().parents[3] / "migrations"
MIGRATIONS_DIR_ENV: Final = "RESEARCH_PLATFORM_MIGRATIONS_DIR"
_MIGRATION_ADVISORY_LOCK_ID = 726194021


class MigrationsNotFound(RuntimeError):
    """The migrations directory holds no SQL files."""


def default_migrations_dir() -> Path:
    """The configured migrations directory, else the source checkout's."""
    configured_directory = os.environ.get(MIGRATIONS_DIR_ENV)
    if configured_directory is not None and configured_directory.strip():
        return Path(configured_directory)
    return MIGRATIONS_DIR


async def apply_migrations(
    database_url: str, migrations_dir: Path | None = None
) -> None:
    """Apply pending SQL files, serializing runners and recording atomically."""
    directory = (
        migrations_dir if migrations_dir is not None else default_migrations_dir()
    )
    files = sorted(directory.glob("*.sql"))
    if not files:
        raise MigrationsNotFound(f"no migration files in {directory}")

    connection = await asyncpg.connect(database_url)
    lock_acquired = False
    try:
        await connection.execute(
            "SELECT pg_advisory_lock($1)", _MIGRATION_ADVISORY_LOCK_ID
        )
        lock_acquired = True
        await connection.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version TEXT PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )

        for migration in files:
            version = migration.stem
            applied = await connection.fetchval(
                "SELECT 1 FROM schema_migrations WHERE version = $1",
                version,
            )
            if applied is not None:
                continue

            async with connection.transaction():
                await connection.execute(migration.read_text(encoding="utf-8"))
                await connection.execute(
                    "INSERT INTO schema_migrations (version) VALUES ($1)",
                    version,
                )
        await setup_checkpoints(database_url)
    finally:
        if lock_acquired:
            await connection.execute(
                "SELECT pg_advisory_unlock($1)", _MIGRATION_ADVISORY_LOCK_ID
            )
        await connection.close()


def main() -> None:
    """Run migrations using the configured database URL."""
    asyncio.run(apply_migrations(Settings().database_url))


if __name__ == "__main__":
    main()
