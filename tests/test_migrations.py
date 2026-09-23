"""Static checks for the initial schema contract."""

from pathlib import Path


def test_initial_migration_contains_required_entities() -> None:
    migration = (
        Path(__file__).parents[1] / "migrations" / "001_initial.sql"
    ).read_text(encoding="utf-8")

    for table in (
        "collections",
        "papers",
        "authors",
        "paper_authors",
        "citations",
        "documents",
        "sections",
        "chunks",
        "ingestion_jobs",
        "research_runs",
        "tool_calls",
        "claims",
        "claim_evidence",
    ):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in migration
