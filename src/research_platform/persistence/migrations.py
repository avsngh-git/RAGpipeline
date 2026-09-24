"""Apply pending PostgreSQL migrations safely and exactly once."""

import asyncio
from pathlib import Path

import asyncpg  # type: ignore[import-untyped]

from research_platform.config import Settings

MIGRATIONS_DIR = Path(__file__).resolve().parents[3] / "migrations"
_MIGRATION_ADVISORY_LOCK_ID = 726194021


async def apply_migrations(
    database_url: str, migrations_dir: Path = MIGRATIONS_DIR
) -> None:
    """Apply pending SQL files, serializing runners and recording atomically."""
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

        for migration in sorted(migrations_dir.glob("*.sql")):
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
