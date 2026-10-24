"""Allowlisted PostgreSQL export and load for public demo bundles."""

from __future__ import annotations

import csv
import gzip
import hashlib
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final
from uuid import UUID

import asyncpg  # type: ignore[import-untyped]


@dataclass(frozen=True)
class TableExport:
    """One allowlisted table and the query selecting its exported rows."""

    name: str
    query: str


@dataclass(frozen=True)
class ExportedTable:
    """One exported table file, relative to the bundle directory."""

    name: str
    path: str
    rows: int
    sha256: str


class DemoExportRefused(RuntimeError):
    """The snapshot may not be published as a demo bundle."""


class DemoLoadRefused(RuntimeError):
    """The bundle files or the target database are not fit for loading."""


OPEN_LICENSES: Final = frozenset({"cc-by", "cc0", "public-domain"})
_RUNS = (
    "SELECT id FROM research_runs WHERE snapshot_id = $1 AND principal = $2 "
    "AND status IN ('completed', 'failed')"
)


def _item_query(table: str, column: str, item_column: str) -> str:
    return (
        f"SELECT * FROM {table} WHERE {column} IN "
        f"(SELECT {item_column} FROM snapshot_items WHERE snapshot_id = $1)"
    )


DEMO_TABLES: Final[tuple[TableExport, ...]] = (
    TableExport("papers", "SELECT * FROM papers"),
    TableExport("authors", "SELECT * FROM authors"),
    TableExport("paper_authors", "SELECT * FROM paper_authors"),
    TableExport("paper_identifiers", "SELECT * FROM paper_identifiers"),
    TableExport("paper_metadata_revisions", "SELECT * FROM paper_metadata_revisions"),
    TableExport("citations", "SELECT * FROM citations"),
    TableExport("unresolved_citations", "SELECT * FROM unresolved_citations"),
    TableExport(
        "unresolved_citation_metadata", "SELECT * FROM unresolved_citation_metadata"
    ),
    TableExport("documents", _item_query("documents", "id", "document_id")),
    TableExport(
        "document_permission_evidence",
        _item_query("document_permission_evidence", "document_id", "document_id"),
    ),
    TableExport(
        "artifacts",
        "SELECT * FROM artifacts WHERE id IN (SELECT artifact_id FROM "
        "document_artifacts WHERE document_id IN "
        "(SELECT document_id FROM snapshot_items WHERE snapshot_id = $1))",
    ),
    TableExport(
        "document_artifacts",
        _item_query("document_artifacts", "document_id", "document_id"),
    ),
    TableExport("extractions", _item_query("extractions", "id", "extraction_id")),
    TableExport("sections", _item_query("sections", "extraction_id", "extraction_id")),
    TableExport(
        "evidence_units",
        _item_query("evidence_units", "extraction_id", "extraction_id"),
    ),
    TableExport(
        "evidence_tables",
        _item_query("evidence_tables", "extraction_id", "extraction_id"),
    ),
    TableExport("chunks", _item_query("chunks", "extraction_id", "extraction_id")),
    TableExport(
        "index_configurations",
        "SELECT * FROM index_configurations WHERE configuration_id IN "
        "(SELECT configuration_id FROM index_generations WHERE snapshot_id = $1 "
        "AND state = 'published' UNION SELECT configuration_id FROM "
        "snapshot_index_states WHERE snapshot_id = $1)",
    ),
    TableExport(
        "collections",
        "SELECT id, name, description, created_at, NULL::uuid AS discovery_manifest_id "
        "FROM collections WHERE id IN (SELECT collection_id FROM index_generations "
        "WHERE snapshot_id = $1 AND state = 'published')",
    ),
    TableExport(
        "snapshots",
        "SELECT id, name, status, configuration_id, configuration, code_revision, "
        "created_at, finalized_at, NULL::uuid AS discovery_manifest_id, finalized_by "
        "FROM snapshots WHERE id = $1",
    ),
    TableExport(
        "snapshot_items", "SELECT * FROM snapshot_items WHERE snapshot_id = $1"
    ),
    TableExport(
        "snapshot_item_chunks",
        "SELECT * FROM snapshot_item_chunks WHERE snapshot_id = $1",
    ),
    TableExport(
        "snapshot_index_states",
        "SELECT * FROM snapshot_index_states WHERE snapshot_id = $1",
    ),
    TableExport(
        "index_generations",
        "SELECT * FROM index_generations WHERE snapshot_id = $1 AND state = 'published'",
    ),
    TableExport(
        "index_generation_pointers",
        "SELECT * FROM index_generation_pointers WHERE (collection_id, configuration_id, "
        "published_generation) IN (SELECT collection_id, configuration_id, generation "
        "FROM index_generations WHERE snapshot_id = $1 AND state = 'published')",
    ),
    TableExport("lexical_vocabularies", "SELECT * FROM lexical_vocabularies"),
    TableExport("lexical_terms", "SELECT * FROM lexical_terms"),
    TableExport(
        "run_configurations",
        f"SELECT * FROM run_configurations WHERE configuration_id IN "
        f"(SELECT configuration_id FROM research_runs WHERE id IN ({_RUNS}))",
    ),
    TableExport("research_runs", f"SELECT * FROM research_runs WHERE id IN ({_RUNS})"),
    TableExport("claims", f"SELECT * FROM claims WHERE run_id IN ({_RUNS})"),
    TableExport(
        "claim_evidence",
        f"SELECT * FROM claim_evidence WHERE claim_id IN "
        f"(SELECT id FROM claims WHERE run_id IN ({_RUNS}))",
    ),
    TableExport(
        "research_run_evidence",
        f"SELECT * FROM research_run_evidence WHERE run_id IN ({_RUNS})",
    ),
    TableExport("tool_calls", f"SELECT * FROM tool_calls WHERE run_id IN ({_RUNS})"),
    TableExport(
        "draft_claims", f"SELECT * FROM draft_claims WHERE run_id IN ({_RUNS})"
    ),
    TableExport("llm_calls", f"SELECT * FROM llm_calls WHERE run_id IN ({_RUNS})"),
    TableExport(
        "llm_call_payloads",
        f"SELECT * FROM llm_call_payloads WHERE run_id IN ({_RUNS})",
    ),
)

EXCLUDED_TABLES: Final[frozenset[str]] = frozenset(
    {
        "api_keys",
        "collection_papers",
        "discovery_candidate_origins",
        "discovery_candidates",
        "discovery_manifest_coverage",
        "discovery_manifest_items",
        "discovery_manifests",
        "discovery_pages",
        "discovery_queries",
        "discovery_runs",
        "discovery_spend",
        "experiments",
        "ingestion_decisions",
        "ingestion_documents",
        "ingestion_job_plan",
        "ingestion_jobs",
        "ingestion_requests",
        "ingestion_stage_attempts",
        "manifest_paper_imports",
        "schema_migrations",
        "snapshot_variant_lineage",
    }
)


async def check_display_permissions(
    connection: asyncpg.Connection, snapshot_id: UUID
) -> None:
    """Refuse unless every snapshot document is displayable under an open licence."""
    snapshot = await connection.fetchrow(
        "SELECT status FROM snapshots WHERE id = $1", snapshot_id
    )
    if snapshot is None or snapshot["status"] != "finalized":
        raise DemoExportRefused("snapshot does not exist or is not finalized")

    rows = await connection.fetch(
        """
        SELECT item.document_id
        FROM snapshot_items AS item
        JOIN extractions AS extraction ON extraction.id = item.extraction_id
        LEFT JOIN document_artifacts AS artifact ON artifact.id = extraction.source_artifact_id
        LEFT JOIN document_permission_evidence AS permission
          ON permission.id = artifact.permission_evidence_id
        WHERE item.snapshot_id = $1
          AND NOT (
            COALESCE(artifact.passage_display_permitted, false)
            AND COALESCE(permission.passage_display_permitted, false)
            AND COALESCE(permission.license_id, '') = ANY($2::text[])
          )
        ORDER BY item.document_id
        """,
        snapshot_id,
        sorted(OPEN_LICENSES),
    )
    if rows:
        ids = ", ".join(str(row["document_id"]) for row in rows[:5])
        raise DemoExportRefused(f"{len(rows)} documents are not displayable: {ids}")


async def export_tables(
    connection: asyncpg.Connection,
    *,
    snapshot_id: UUID,
    run_principal: str,
    bundle_dir: Path,
) -> tuple[ExportedTable, ...]:
    """Write every allowlisted table to bundle_dir/postgres/ and describe the files."""
    output_dir = bundle_dir / "postgres"
    output_dir.mkdir(parents=True, exist_ok=True)
    exported: list[ExportedTable] = []

    async with connection.transaction(isolation="repeatable_read", readonly=True):
        await check_display_permissions(connection, snapshot_id)
        for index, table in enumerate(DEMO_TABLES, start=1):
            path = output_dir / f"{index:02d}_{table.name}.csv.gz"
            args: tuple[object, ...]
            if "$2" in table.query:
                args = (snapshot_id, run_principal)
            elif "$1" in table.query:
                args = (snapshot_id,)
            else:
                args = ()
            with gzip.GzipFile(filename=str(path), mode="wb", mtime=0) as output:
                status = await connection.copy_from_query(
                    table.query,
                    *args,
                    output=output,
                    format="csv",
                    header=True,
                )
            row_count = int(status.split()[-1])
            exported.append(
                ExportedTable(
                    name=table.name,
                    path=path.relative_to(bundle_dir).as_posix(),
                    rows=row_count,
                    sha256=_sha256(path),
                )
            )
    return tuple(exported)


async def load_tables(
    connection: asyncpg.Connection,
    *,
    bundle_dir: Path,
    tables: Sequence[ExportedTable],
) -> None:
    """Verify the files, then load them into an empty migrated database in one transaction."""
    expected_names = tuple(table.name for table in DEMO_TABLES)
    if tuple(table.name for table in tables) != expected_names:
        raise DemoLoadRefused("table names or order do not match the allowlist")

    files: list[tuple[TableExport, Path]] = []
    for table_export, exported in zip(DEMO_TABLES, tables, strict=True):
        path = bundle_dir / exported.path
        if not path.is_file():
            raise DemoLoadRefused(f"missing bundle file for {exported.name}")
        if _sha256(path) != exported.sha256:
            raise DemoLoadRefused(f"checksum mismatch for {exported.name}")
        files.append((table_export, path))

    async with connection.transaction():
        snapshots = await connection.fetchval("SELECT count(*) FROM snapshots")
        papers = await connection.fetchval("SELECT count(*) FROM papers")
        if snapshots or papers:
            raise DemoLoadRefused("target database is not empty")

        await connection.execute(
            "ALTER TABLE snapshot_items DISABLE TRIGGER "
            "snapshot_items_immutable_after_finalize"
        )
        await connection.execute(
            "ALTER TABLE snapshot_item_chunks DISABLE TRIGGER "
            "snapshot_item_chunks_immutable_after_finalize"
        )
        for table, path in files:
            with gzip.open(path, mode="rt", encoding="utf-8", newline="") as source:
                columns = next(csv.reader(source), None)
            if not columns:
                raise DemoLoadRefused(f"missing CSV header for {table.name}")
            with gzip.open(path, mode="rb") as source:
                await connection.copy_to_table(
                    table.name,
                    source=source,
                    columns=columns,
                    format="csv",
                    header=True,
                )

        await connection.execute(
            "ALTER TABLE snapshot_item_chunks ENABLE TRIGGER "
            "snapshot_item_chunks_immutable_after_finalize"
        )
        await connection.execute(
            "ALTER TABLE snapshot_items ENABLE TRIGGER "
            "snapshot_items_immutable_after_finalize"
        )
        serial_columns = await connection.fetch(
            """
            SELECT table_name, column_name
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND column_default LIKE 'nextval(%'
              AND table_name = ANY($1::text[])
            """,
            list(expected_names),
        )
        for row in serial_columns:
            table_name = str(row["table_name"])
            column_name = str(row["column_name"])
            if not re.fullmatch(r"[a-z_][a-z0-9_]*", table_name):
                raise DemoLoadRefused(f"unsafe serial table name: {table_name}")
            if not re.fullmatch(r"[a-z_][a-z0-9_]*", column_name):
                raise DemoLoadRefused(f"unsafe serial column name: {column_name}")
            await connection.execute(
                f"SELECT setval(pg_get_serial_sequence('{table_name}', '{column_name}'), "
                f"COALESCE((SELECT max({column_name}) FROM {table_name}), 0) + 1, false)"
            )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return "sha256:" + digest.hexdigest()
