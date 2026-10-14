"""Attribution and integrity metadata for public demo bundles."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final
from uuid import UUID

import asyncpg  # type: ignore[import-untyped]

from research_platform.demo.database import DemoLoadRefused

BUNDLE_FORMAT: Final = "research-demo-bundle-v1"
LICENSE_URLS: Final = {
    "cc-by": "https://creativecommons.org/licenses/by/4.0/",
    "cc0": "https://creativecommons.org/publicdomain/zero/1.0/",
    "public-domain": "",
}


@dataclass(frozen=True)
class AttributionRow:
    """Paper metadata and the permission evidence used by a demo bundle."""

    paper_id: str
    title: str
    authors: tuple[str, ...]
    year: int | None
    source: str
    license_id: str


async def attribution_rows(
    connection: asyncpg.Connection, snapshot_id: UUID
) -> tuple[AttributionRow, ...]:
    """Return one ordered attribution row for every snapshot paper."""
    records = await connection.fetch(
        """
        WITH paper_permissions AS (
            SELECT DISTINCT ON (document.paper_id)
                document.paper_id,
                permission.source_url,
                permission.license_id
            FROM snapshot_items AS item
            JOIN documents AS document ON document.id = item.document_id
            JOIN extractions AS extraction ON extraction.id = item.extraction_id
            LEFT JOIN document_artifacts AS artifact
              ON artifact.id = extraction.source_artifact_id
            LEFT JOIN document_permission_evidence AS permission
              ON permission.id = artifact.permission_evidence_id
            WHERE item.snapshot_id = $1
            ORDER BY document.paper_id, document.id
        )
        SELECT paper.id AS paper_id,
               COALESCE(paper.title, '(untitled)') AS title,
               paper.publication_year AS year,
               COALESCE(doi.source, permission.source_url, '') AS source,
               COALESCE(permission.license_id, '') AS license_id,
               COALESCE(author_list.names, ARRAY[]::text[]) AS authors
        FROM paper_permissions AS permission
        JOIN papers AS paper ON paper.id = permission.paper_id
        LEFT JOIN LATERAL (
            SELECT 'https://doi.org/' || identifier.normalized_identifier AS source
            FROM paper_identifiers AS identifier
            WHERE identifier.paper_id = paper.id AND identifier.namespace = 'doi'
            ORDER BY identifier.normalized_identifier
            LIMIT 1
        ) AS doi ON true
        LEFT JOIN LATERAL (
            SELECT array_agg(author.display_name ORDER BY paper_author.author_position)
                FILTER (WHERE author.display_name IS NOT NULL) AS names
            FROM paper_authors AS paper_author
            JOIN authors AS author ON author.id = paper_author.author_id
            WHERE paper_author.paper_id = paper.id
        ) AS author_list ON true
        ORDER BY COALESCE(paper.title, '(untitled)'), paper.id
        """,
        snapshot_id,
    )
    return tuple(
        AttributionRow(
            paper_id=str(record["paper_id"]),
            title=str(record["title"]),
            authors=tuple(record["authors"]),
            year=record["year"],
            source=str(record["source"]),
            license_id=str(record["license_id"]),
        )
        for record in records
    )


def render_attribution(rows: Sequence[AttributionRow]) -> str:
    """Render the card's public attribution table."""
    lines = [
        "# Attribution",
        "",
        "The passages, tables and research answers in this bundle are excerpts extracted from the",
        "papers below. Text was extracted from the original PDFs, split into sections and chunks, and",
        "tables were converted to rows; no other change was made. Each paper is used under the",
        "licence shown. Paper metadata comes from OpenAlex (CC0).",
        "",
        "| Paper | Authors | Year | Source | Licence |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        authors = list(row.authors[:3])
        if len(row.authors) > 3:
            authors.append("et al.")
        author_text = ", ".join(authors)
        year = str(row.year) if row.year is not None else "n.d."
        source = f"[{row.source}]({row.source})" if row.source else ""
        if row.license_id == "cc-by":
            license_text = f"[CC BY 4.0]({LICENSE_URLS['cc-by']})"
        elif row.license_id == "cc0":
            license_text = f"[CC0 1.0]({LICENSE_URLS['cc0']})"
        elif row.license_id == "public-domain":
            license_text = "Public domain"
        else:
            raise ValueError("unsupported attribution licence")
        cells = (row.title, author_text, year, source, license_text)
        lines.append("| " + " | ".join(_escape_cell(cell) for cell in cells) + " |")
    return "\n".join(lines) + "\n"


def write_manifest(path: Path, manifest: Mapping[str, object]) -> None:
    """Write a stable, human-readable bundle manifest."""
    path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def read_manifest(path: Path) -> dict[str, object]:
    """Read a supported demo bundle manifest."""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise DemoLoadRefused("bundle manifest is missing or invalid") from None
    if not isinstance(value, dict) or value.get("format") != BUNDLE_FORMAT:
        raise DemoLoadRefused("unsupported demo bundle format")
    return value


def file_sha256(path: Path) -> str:
    """Return the prefixed SHA-256 digest of a file."""
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def _escape_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ").replace("\r", " ")
