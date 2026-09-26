"""Draft snapshot membership, validation and explicit immutable finalization."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

import asyncpg  # type: ignore[import-untyped]

from research_platform.ingestion.membership import MembershipDecision
from research_platform.ingestion.snapshot_selection import (
    SnapshotChunkSelection,
    compute_chunk_selection_id,
)

_SHA256_ID = re.compile(r"^sha256:[0-9a-f]{64}$")
_MAX_EVIDENCE_INSPECTION_LIMIT = 100
_CONTENT_PREVIEW_CHARACTERS = 2000
_TABLE_PREVIEW_CELLS = 50
_TABLE_CELL_PREVIEW_CHARACTERS = 500


@dataclass(frozen=True)
class SnapshotIssue:
    code: str
    detail: str
    paper_id: str | None = None


@dataclass(frozen=True)
class SnapshotValidationReport:
    snapshot_id: UUID
    snapshot_status: str
    member_count: int
    expected_chunk_count: int
    index_configuration_id: str | None
    issues: tuple[SnapshotIssue, ...]

    @property
    def valid(self) -> bool:
        return not self.issues


@dataclass(frozen=True)
class FinalizedSnapshot:
    id: UUID
    name: str
    configuration_id: str
    finalized_at: datetime
    finalized_by: str
    member_count: int
    index_configuration_id: str


@dataclass(frozen=True)
class SnapshotMemberInspection:
    paper_id: str
    title: str
    publication_year: int | None
    document_id: UUID
    document_version: str
    document_status: str
    extraction_id: UUID | None
    extraction_status: str | None
    source_artifact_id: UUID | None
    storage_permitted: bool
    indexing_permitted: bool
    chunk_count: int
    table_count: int
    selection_reason: str


class SnapshotValidationError(ValueError):
    def __init__(self, report: SnapshotValidationReport) -> None:
        self.report = report
        codes = ", ".join(issue.code for issue in report.issues)
        super().__init__(f"snapshot cannot be finalized: {codes}")


class SnapshotRepository:
    """A draft is editable; a finalized snapshot is an immutable evidence set."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def create_draft(
        self,
        *,
        name: str,
        configuration_id: str,
        configuration: Mapping[str, object],
        code_revision: str,
    ) -> UUID:
        for field_name, value in (
            ("name", name),
            ("code_revision", code_revision),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must be a non-empty string")
        _validate_sha256(configuration_id, "configuration_id")
        serialized = json.dumps(dict(configuration), sort_keys=True, ensure_ascii=False)
        async with self._pool.acquire() as connection:
            snapshot_id = await connection.fetchval(
                """
                INSERT INTO snapshots (name, configuration_id, configuration, code_revision)
                VALUES ($1, $2, $3::jsonb, $4)
                RETURNING id
                """,
                name,
                configuration_id,
                serialized,
                code_revision,
            )
        if not isinstance(snapshot_id, UUID):
            raise RuntimeError("database did not return a snapshot ID")
        return snapshot_id

    async def create_variant_draft(
        self,
        parent_snapshot_id: UUID,
        *,
        name: str,
        configuration_id: str,
        configuration: Mapping[str, object],
        code_revision: str,
    ) -> UUID:
        """Create a draft variant inheriting a finalized snapshot's exact evidence."""
        for field_name, value in (("name", name), ("code_revision", code_revision)):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must be a non-empty string")
        _validate_sha256(configuration_id, "configuration_id")
        serialized = json.dumps(dict(configuration), sort_keys=True, ensure_ascii=False)
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                parent = await connection.fetchrow(
                    """
                    SELECT status, configuration_id
                    FROM snapshots WHERE id = $1 FOR SHARE
                    """,
                    parent_snapshot_id,
                )
                if parent is None:
                    raise ValueError("parent snapshot does not exist")
                if parent["status"] != "finalized":
                    raise ValueError("snapshot variants require a finalized parent")
                rows = await connection.fetch(
                    """
                    SELECT item.paper_id, item.document_id, item.extraction_id,
                           item.chunking_configuration_id, selected.chunk_id
                    FROM snapshot_items item
                    LEFT JOIN snapshot_item_chunks selected
                      ON selected.snapshot_id = item.snapshot_id
                     AND selected.paper_id = item.paper_id
                    WHERE item.snapshot_id = $1
                    ORDER BY item.paper_id, selected.chunk_id
                    """,
                    parent_snapshot_id,
                )
                members: list[SnapshotChunkSelection] = []
                member_keys: set[tuple[str, UUID, UUID]] = set()
                selected_chunk_ids: list[str] = []
                for row in rows:
                    paper_id = row["paper_id"]
                    document_id = row["document_id"]
                    extraction_id = row["extraction_id"]
                    chunk_id = row["chunk_id"]
                    if not isinstance(extraction_id, UUID) or not isinstance(
                        chunk_id, str
                    ):
                        raise ValueError(
                            "finalized parent lacks an exact searchable chunk selection"
                        )
                    key = (paper_id, document_id, extraction_id)
                    if key not in member_keys:
                        members.append(
                            SnapshotChunkSelection(
                                paper_id=paper_id,
                                document_id=document_id,
                                extraction_id=extraction_id,
                                chunking_configuration_id=row[
                                    "chunking_configuration_id"
                                ],
                            )
                        )
                        member_keys.add(key)
                    selected_chunk_ids.append(chunk_id)
                parent_selection_id = compute_chunk_selection_id(
                    snapshot_id=parent_snapshot_id,
                    snapshot_configuration_id=parent["configuration_id"],
                    members=members,
                    selected_chunk_ids=selected_chunk_ids,
                )
                variant_id = await connection.fetchval(
                    """
                    INSERT INTO snapshots (name, configuration_id, configuration, code_revision)
                    VALUES ($1, $2, $3::jsonb, $4)
                    RETURNING id
                    """,
                    name,
                    configuration_id,
                    serialized,
                    code_revision,
                )
                if not isinstance(variant_id, UUID):
                    raise RuntimeError("database did not return a snapshot ID")
                await connection.execute(
                    """
                    INSERT INTO snapshot_variant_lineage
                        (snapshot_id, parent_snapshot_id, parent_chunk_selection_id)
                    VALUES ($1, $2, $3)
                    """,
                    variant_id,
                    parent_snapshot_id,
                    parent_selection_id,
                )
                await connection.execute(
                    """
                    INSERT INTO snapshot_items (
                        snapshot_id, paper_id, document_id, extraction_id,
                        selection_reason, chunking_configuration_id
                    )
                    SELECT $2, paper_id, document_id, extraction_id,
                           selection_reason, chunking_configuration_id
                    FROM snapshot_items WHERE snapshot_id = $1
                    """,
                    parent_snapshot_id,
                    variant_id,
                )
                await connection.execute(
                    """
                    INSERT INTO snapshot_item_chunks (
                        snapshot_id, paper_id, document_id, extraction_id, chunk_id
                    )
                    SELECT $2, paper_id, document_id, extraction_id, chunk_id
                    FROM snapshot_item_chunks WHERE snapshot_id = $1
                    """,
                    parent_snapshot_id,
                    variant_id,
                )
        return variant_id

    async def configuration_for(self, snapshot_id: UUID) -> dict[str, object]:
        """Return the immutable configuration recorded when a snapshot was created."""
        async with self._pool.acquire() as connection:
            row = await connection.fetchrow(
                "SELECT configuration FROM snapshots WHERE id = $1", snapshot_id
            )
        if row is None:
            raise ValueError("snapshot does not exist")
        return _json_object(row["configuration"])

    async def document_ids_for_processing(self, snapshot_id: UUID) -> tuple[UUID, ...]:
        """Return a fixed draft's document membership for an extraction job."""
        async with self._pool.acquire() as connection:
            status = await connection.fetchval(
                "SELECT status FROM snapshots WHERE id = $1", snapshot_id
            )
            if status != "draft":
                raise ValueError("only a draft snapshot can start ingestion")
            rows = await connection.fetch(
                """
                SELECT document_id FROM snapshot_items
                WHERE snapshot_id = $1 ORDER BY paper_id
                """,
                snapshot_id,
            )
        if not rows:
            raise ValueError("cannot start ingestion for an empty snapshot")
        return tuple(row["document_id"] for row in rows)

    async def draft_member_extractions(
        self, snapshot_id: UUID
    ) -> dict[UUID, UUID | None]:
        """Return a draft's current document/extraction pairs for safe preflight."""
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                status = await connection.fetchval(
                    "SELECT status FROM snapshots WHERE id = $1 FOR SHARE",
                    snapshot_id,
                )
                if status is None:
                    raise ValueError("snapshot does not exist")
                if status != "draft":
                    raise ValueError("only draft snapshots can receive corrections")
                rows = await connection.fetch(
                    """
                    SELECT document_id, extraction_id
                    FROM snapshot_items
                    WHERE snapshot_id = $1
                    """,
                    snapshot_id,
                )
        return {row["document_id"]: row["extraction_id"] for row in rows}

    async def replace_extraction(
        self,
        snapshot_id: UUID,
        document_id: UUID,
        source_extraction_id: UUID,
        replacement_extraction_id: UUID,
    ) -> None:
        """Swap a draft member only if it still references the reviewed source."""
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                await self._require_draft(connection, snapshot_id)
                await connection.execute(
                    """
                    DELETE FROM snapshot_item_chunks
                    WHERE snapshot_id = $1 AND document_id = $2
                      AND EXISTS (
                          SELECT 1 FROM snapshot_items item
                          WHERE item.snapshot_id = $1 AND item.document_id = $2
                            AND item.extraction_id = $3
                      )
                    """,
                    snapshot_id,
                    document_id,
                    source_extraction_id,
                )
                updated = await connection.fetchval(
                    """
                    UPDATE snapshot_items
                    SET extraction_id = $4, chunking_configuration_id = NULL
                    WHERE snapshot_id = $1 AND document_id = $2
                      AND extraction_id = $3
                    RETURNING paper_id
                    """,
                    snapshot_id,
                    document_id,
                    source_extraction_id,
                    replacement_extraction_id,
                )
        if updated is None:
            raise ValueError(
                "draft member changed since the correction source was inspected"
            )

    async def set_extraction(
        self, snapshot_id: UUID, document_id: UUID, extraction_id: UUID
    ) -> None:
        """Attach completed evidence to the matching member of a draft snapshot."""
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                await self._require_draft(connection, snapshot_id)
                await connection.execute(
                    """
                    DELETE FROM snapshot_item_chunks
                    WHERE snapshot_id = $1 AND document_id = $2
                      AND EXISTS (
                          SELECT 1 FROM snapshot_items item
                          WHERE item.snapshot_id = $1 AND item.document_id = $2
                            AND item.extraction_id IS DISTINCT FROM $3
                      )
                    """,
                    snapshot_id,
                    document_id,
                    extraction_id,
                )
                updated = await connection.fetchval(
                    """
                    UPDATE snapshot_items
                    SET chunking_configuration_id = CASE
                            WHEN extraction_id IS DISTINCT FROM $3 THEN NULL
                            ELSE chunking_configuration_id
                        END,
                        extraction_id = $3
                    WHERE snapshot_id = $1 AND document_id = $2
                    RETURNING paper_id
                    """,
                    snapshot_id,
                    document_id,
                    extraction_id,
                )
        if updated is None:
            raise ValueError("document is not a member of the draft snapshot")

    async def set_chunking_configuration(
        self,
        snapshot_id: UUID,
        document_id: UUID,
        extraction_id: UUID,
        configuration_id: str,
    ) -> None:
        """Select and freeze the configured searchable chunks for one draft member."""
        if not isinstance(configuration_id, str) or not _SHA256_ID.fullmatch(
            configuration_id
        ):
            raise ValueError("chunking configuration ID must be a SHA-256 identity")
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                await self._require_draft(connection, snapshot_id)
                updated = await connection.fetchval(
                    """
                    UPDATE snapshot_items
                    SET chunking_configuration_id = $4
                    WHERE snapshot_id = $1 AND document_id = $2
                      AND extraction_id = $3
                    RETURNING paper_id
                    """,
                    snapshot_id,
                    document_id,
                    extraction_id,
                    configuration_id,
                )
                if updated is None:
                    raise ValueError(
                        "document extraction is not attached to the draft snapshot"
                    )
                await connection.execute(
                    """
                    DELETE FROM snapshot_item_chunks
                    WHERE snapshot_id = $1 AND document_id = $2
                    """,
                    snapshot_id,
                    document_id,
                )
                await connection.execute(
                    """
                    INSERT INTO snapshot_item_chunks
                        (snapshot_id, paper_id, document_id, extraction_id, chunk_id)
                    SELECT item.snapshot_id, item.paper_id, chunk.document_id,
                           chunk.extraction_id, chunk.id
                    FROM snapshot_items item
                    JOIN chunks chunk
                      ON chunk.document_id = item.document_id
                     AND chunk.extraction_id = item.extraction_id
                    WHERE item.snapshot_id = $1 AND item.document_id = $2
                      AND item.extraction_id = $3
                      AND chunk.metadata ->> 'chunking_configuration_id' = $4
                    """,
                    snapshot_id,
                    document_id,
                    extraction_id,
                    configuration_id,
                )

    async def review_flagged_table(
        self,
        snapshot_id: UUID,
        extraction_id: UUID,
        table_ordinal: int,
        *,
        reviewer: str,
    ) -> None:
        """Record that a reviewer checked a flagged table's PDF associations."""
        if not isinstance(reviewer, str) or not reviewer.strip():
            raise ValueError("table reviewer must be non-empty")
        if (
            isinstance(table_ordinal, bool)
            or not isinstance(table_ordinal, int)
            or table_ordinal < 0
        ):
            raise ValueError("table ordinal must be a non-negative integer")
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                await self._require_draft(connection, snapshot_id)
                updated = await connection.fetchval(
                    """
                    UPDATE evidence_tables AS evidence_table
                    SET metadata = evidence_table.metadata || jsonb_build_object(
                        'review_status', 'passed',
                        'reviewer', $4::text,
                        'reviewed_at', now()
                    )
                    WHERE evidence_table.extraction_id = $2
                      AND evidence_table.ordinal = $3
                      AND evidence_table.metadata ->> 'review_required' = 'true'
                      AND EXISTS (
                          SELECT 1 FROM snapshot_items item
                          WHERE item.snapshot_id = $1
                            AND item.extraction_id = evidence_table.extraction_id
                      )
                    RETURNING evidence_table.ordinal
                    """,
                    snapshot_id,
                    extraction_id,
                    table_ordinal,
                    reviewer.strip(),
                )
        if updated is None:
            raise ValueError("flagged table is not part of this draft snapshot")

    async def add_member(
        self,
        snapshot_id: UUID,
        *,
        paper_id: str,
        document_id: UUID,
        extraction_id: UUID | None,
        selection_reason: str,
    ) -> None:
        if not isinstance(paper_id, str) or not paper_id.strip():
            raise ValueError("paper_id must be a non-empty string")
        if not isinstance(selection_reason, str) or not selection_reason.strip():
            raise ValueError("selection_reason must be a non-empty string")
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                await self._require_draft(connection, snapshot_id)
                await connection.execute(
                    """
                    INSERT INTO snapshot_items
                        (snapshot_id, paper_id, document_id, extraction_id, selection_reason)
                    VALUES ($1, $2, $3, $4, $5)
                    """,
                    snapshot_id,
                    paper_id,
                    document_id,
                    extraction_id,
                    selection_reason,
                )
                if extraction_id is not None:
                    await connection.execute(
                        """
                        INSERT INTO snapshot_item_chunks
                            (snapshot_id, paper_id, document_id, extraction_id, chunk_id)
                        SELECT $1, $2, chunk.document_id, chunk.extraction_id, chunk.id
                        FROM chunks chunk
                        WHERE chunk.document_id = $3 AND chunk.extraction_id = $4
                        """,
                        snapshot_id,
                        paper_id,
                        document_id,
                        extraction_id,
                    )

    async def add_reviewed_membership(
        self,
        snapshot_id: UUID,
        membership: MembershipDecision,
        document_ids: Mapping[str, UUID],
    ) -> None:
        """Add the exact reviewed 100-paper selection to a bound draft snapshot."""
        if set(document_ids) != set(membership.selected_openalex_ids):
            raise ValueError(
                "selected document map does not match the 100-paper decision"
            )
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                snapshot = await connection.fetchrow(
                    "SELECT status, configuration FROM snapshots WHERE id = $1 FOR UPDATE",
                    snapshot_id,
                )
                if snapshot is None:
                    raise ValueError("snapshot does not exist")
                if snapshot["status"] != "draft":
                    raise ValueError("only a draft snapshot can receive membership")
                configuration = _json_object(snapshot["configuration"])
                if (
                    configuration.get("membership_decision_sha256")
                    != membership.identity
                    or configuration.get("membership_target_count") != 100
                ):
                    raise ValueError(
                        "snapshot configuration is not bound to this 100-paper decision"
                    )
                existing = await connection.fetch(
                    """
                    SELECT paper_id, document_id, selection_reason
                    FROM snapshot_items WHERE snapshot_id = $1
                    """,
                    snapshot_id,
                )
                if existing:
                    existing_map = {
                        row["paper_id"]: (row["document_id"], row["selection_reason"])
                        for row in existing
                    }
                    expected_map = {
                        openalex_id: (
                            document_ids[openalex_id],
                            membership.selection_reasons[openalex_id],
                        )
                        for openalex_id in membership.selected_openalex_ids
                    }
                    if existing_map != expected_map:
                        raise ValueError(
                            "draft already has a different or partial membership"
                        )
                    return
                for openalex_id in sorted(membership.selected_openalex_ids):
                    await connection.execute(
                        """
                        INSERT INTO snapshot_items
                            (snapshot_id, paper_id, document_id, extraction_id, selection_reason)
                        VALUES ($1, $2, $3, NULL, $4)
                        """,
                        snapshot_id,
                        openalex_id,
                        document_ids[openalex_id],
                        membership.selection_reasons[openalex_id],
                    )

    async def remove_member(self, snapshot_id: UUID, paper_id: str) -> None:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                await self._require_draft(connection, snapshot_id)
                result = await connection.execute(
                    "DELETE FROM snapshot_items WHERE snapshot_id = $1 AND paper_id = $2",
                    snapshot_id,
                    paper_id,
                )
        if result != "DELETE 1":
            raise ValueError("snapshot paper membership does not exist")

    async def inspect_members(
        self, snapshot_id: UUID
    ) -> tuple[SnapshotMemberInspection, ...]:
        """List selected versions, processing outcomes and permission flags."""
        async with self._pool.acquire() as connection:
            exists = await connection.fetchval(
                "SELECT EXISTS (SELECT 1 FROM snapshots WHERE id = $1)",
                snapshot_id,
            )
            if not exists:
                raise ValueError("snapshot does not exist")
            rows = await connection.fetch(
                """
                SELECT item.paper_id, paper.title, paper.publication_year,
                       item.document_id, document.version AS document_version,
                       document.status AS document_status, item.extraction_id,
                       extraction.status AS extraction_status,
                       extraction.source_artifact_id, item.selection_reason,
                       COALESCE(artifact.storage_permitted AND permission.storage_permitted,
                                FALSE) AS storage_permitted,
                       COALESCE(artifact.indexing_permitted AND permission.indexing_permitted,
                                FALSE) AS indexing_permitted,
                       (SELECT count(*) FROM snapshot_item_chunks selected
                        WHERE selected.snapshot_id = item.snapshot_id
                          AND selected.paper_id = item.paper_id) AS chunk_count,
                       (SELECT count(*) FROM evidence_tables evidence_table
                        WHERE evidence_table.extraction_id = item.extraction_id) AS table_count
                FROM snapshot_items item
                JOIN papers paper ON paper.id = item.paper_id
                JOIN documents document
                  ON document.id = item.document_id AND document.paper_id = item.paper_id
                LEFT JOIN extractions extraction
                  ON extraction.id = item.extraction_id
                 AND extraction.document_id = item.document_id
                LEFT JOIN document_artifacts artifact
                  ON artifact.id = extraction.source_artifact_id
                 AND artifact.document_id = item.document_id
                LEFT JOIN document_permission_evidence permission
                  ON permission.id = artifact.permission_evidence_id
                 AND permission.document_id = artifact.document_id
                WHERE item.snapshot_id = $1
                ORDER BY item.paper_id
                """,
                snapshot_id,
            )
        return tuple(
            SnapshotMemberInspection(
                paper_id=row["paper_id"],
                title=row["title"],
                publication_year=row["publication_year"],
                document_id=row["document_id"],
                document_version=row["document_version"],
                document_status=row["document_status"],
                extraction_id=row["extraction_id"],
                extraction_status=row["extraction_status"],
                source_artifact_id=row["source_artifact_id"],
                storage_permitted=row["storage_permitted"],
                indexing_permitted=row["indexing_permitted"],
                chunk_count=row["chunk_count"],
                table_count=row["table_count"],
                selection_reason=row["selection_reason"],
            )
            for row in rows
        )

    async def inspect_draft_evidence(
        self, snapshot_id: UUID, *, limit: int = 20
    ) -> dict[str, object]:
        """Return a bounded local preview of storage-permitted draft evidence."""
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= _MAX_EVIDENCE_INSPECTION_LIMIT
        ):
            raise ValueError("evidence inspection limit must be between 1 and 100")
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                status = await connection.fetchval(
                    "SELECT status FROM snapshots WHERE id = $1 FOR SHARE",
                    snapshot_id,
                )
                if status is None:
                    raise ValueError("snapshot does not exist")
                if status != "draft":
                    raise ValueError(
                        "evidence inspection is restricted to draft snapshots"
                    )

                withheld_document_count = await connection.fetchval(
                    """
                    SELECT count(DISTINCT item.document_id)
                    FROM snapshot_items item
                    JOIN extractions extraction
                      ON extraction.id = item.extraction_id
                     AND extraction.document_id = item.document_id
                    LEFT JOIN document_artifacts artifact
                      ON artifact.id = extraction.source_artifact_id
                     AND artifact.document_id = item.document_id
                    LEFT JOIN document_permission_evidence permission
                      ON permission.id = artifact.permission_evidence_id
                     AND permission.document_id = artifact.document_id
                    WHERE item.snapshot_id = $1
                      AND NOT COALESCE(
                          artifact.storage_permitted AND permission.storage_permitted,
                          FALSE
                      )
                    """,
                    snapshot_id,
                )
                evidence_rows = await connection.fetch(
                    """
                    SELECT count(*) OVER () AS total_count, item.paper_id,
                           paper.title, document.version AS document_version,
                           evidence.id AS evidence_id, evidence.kind, section.title AS section_title,
                           left(evidence.content, $3) AS content_preview,
                           char_length(evidence.content) > $3 AS content_truncated,
                           evidence.start_offset, evidence.end_offset,
                           evidence.source_location, evidence.metadata
                    FROM snapshot_items item
                    JOIN papers paper ON paper.id = item.paper_id
                    JOIN documents document
                      ON document.id = item.document_id AND document.paper_id = item.paper_id
                    JOIN extractions extraction
                      ON extraction.id = item.extraction_id
                     AND extraction.document_id = item.document_id
                    JOIN document_artifacts artifact
                      ON artifact.id = extraction.source_artifact_id
                     AND artifact.document_id = item.document_id
                    JOIN document_permission_evidence permission
                      ON permission.id = artifact.permission_evidence_id
                     AND permission.document_id = artifact.document_id
                    JOIN evidence_units evidence
                      ON evidence.extraction_id = extraction.id
                    LEFT JOIN sections section
                      ON section.id = evidence.section_id
                     AND section.extraction_id = extraction.id
                    WHERE item.snapshot_id = $1
                      AND artifact.storage_permitted
                      AND permission.storage_permitted
                    ORDER BY item.paper_id, evidence.id
                    LIMIT $2
                    """,
                    snapshot_id,
                    limit,
                    _CONTENT_PREVIEW_CHARACTERS,
                )
                table_rows = await connection.fetch(
                    """
                    SELECT count(*) OVER () AS total_count, item.paper_id,
                           paper.title, document.version AS document_version,
                           evidence_table.ordinal, evidence_table.caption,
                           evidence_table.units, evidence_table.footnotes,
                           evidence_table.source_location,
                           COALESCE(
                               (evidence_table.table_data->>'row_count')::integer, 0
                           ) AS row_count,
                           COALESCE(
                               (evidence_table.table_data->>'column_count')::integer, 0
                           ) AS column_count,
                           COALESCE(
                               (evidence_table.table_data->>'header_rows')::integer, 0
                           ) AS header_rows,
                           CASE
                               WHEN jsonb_typeof(evidence_table.table_data->'cells') = 'array'
                               THEN jsonb_array_length(evidence_table.table_data->'cells')
                               ELSE 0
                           END AS cells_total,
                           COALESCE((
                               SELECT jsonb_agg(preview.cell ORDER BY preview.ordinal)
                               FROM jsonb_array_elements(
                                   CASE
                                       WHEN jsonb_typeof(evidence_table.table_data->'cells') = 'array'
                                       THEN evidence_table.table_data->'cells'
                                       ELSE '[]'::jsonb
                                   END
                               ) WITH ORDINALITY AS preview(cell, ordinal)
                               WHERE preview.ordinal <= $3
                           ), '[]'::jsonb) AS cells_preview
                    FROM snapshot_items item
                    JOIN papers paper ON paper.id = item.paper_id
                    JOIN documents document
                      ON document.id = item.document_id AND document.paper_id = item.paper_id
                    JOIN extractions extraction
                      ON extraction.id = item.extraction_id
                     AND extraction.document_id = item.document_id
                    JOIN document_artifacts artifact
                      ON artifact.id = extraction.source_artifact_id
                     AND artifact.document_id = item.document_id
                    JOIN document_permission_evidence permission
                      ON permission.id = artifact.permission_evidence_id
                     AND permission.document_id = artifact.document_id
                    JOIN evidence_tables evidence_table
                      ON evidence_table.extraction_id = extraction.id
                    WHERE item.snapshot_id = $1
                      AND artifact.storage_permitted
                      AND permission.storage_permitted
                    ORDER BY item.paper_id, evidence_table.ordinal
                    LIMIT $2
                    """,
                    snapshot_id,
                    limit,
                    _TABLE_PREVIEW_CELLS,
                )

        evidence_total = int(evidence_rows[0]["total_count"]) if evidence_rows else 0
        table_total = int(table_rows[0]["total_count"]) if table_rows else 0
        tables = []
        for row in table_rows:
            cells = _json_array(row["cells_preview"], "table cell preview")
            tables.append(
                {
                    "paper_id": row["paper_id"],
                    "title": row["title"],
                    "document_version": row["document_version"],
                    "table_ordinal": row["ordinal"],
                    "caption": row["caption"],
                    "units": row["units"],
                    "footnotes": _json_array(row["footnotes"], "table footnotes"),
                    "source_location": _json_object(row["source_location"]),
                    "row_count": row["row_count"],
                    "column_count": row["column_count"],
                    "header_rows": row["header_rows"],
                    "cells_preview": [_preview_table_cell(cell) for cell in cells],
                    "cells_total": row["cells_total"],
                    "cells_truncated": row["cells_total"] > len(cells),
                }
            )

        return {
            "snapshot_id": str(snapshot_id),
            "snapshot_status": "draft",
            "limit_per_type": limit,
            "content_preview_characters": _CONTENT_PREVIEW_CHARACTERS,
            "table_preview_cells": _TABLE_PREVIEW_CELLS,
            "table_cell_preview_characters": _TABLE_CELL_PREVIEW_CHARACTERS,
            "withheld_document_count": withheld_document_count,
            "evidence_unit_total": evidence_total,
            "evidence_units_truncated": evidence_total > len(evidence_rows),
            "evidence_units": [
                {
                    "paper_id": row["paper_id"],
                    "title": row["title"],
                    "document_version": row["document_version"],
                    "evidence_id": row["evidence_id"],
                    "kind": row["kind"],
                    "section_title": row["section_title"],
                    "content_preview": row["content_preview"],
                    "content_truncated": row["content_truncated"],
                    "start_offset": row["start_offset"],
                    "end_offset": row["end_offset"],
                    "source_location": _json_object(row["source_location"]),
                    "metadata": _json_object(row["metadata"]),
                }
                for row in evidence_rows
            ],
            "table_total": table_total,
            "tables_truncated": table_total > len(table_rows),
            "tables": tables,
        }

    async def validate(
        self, snapshot_id: UUID, *, minimum_papers: int = 100
    ) -> SnapshotValidationReport:
        _validate_minimum(minimum_papers)
        async with self._pool.acquire() as connection:
            snapshot = await connection.fetchrow(
                "SELECT id, status, configuration FROM snapshots WHERE id = $1",
                snapshot_id,
            )
            if snapshot is None:
                raise ValueError("snapshot does not exist")
            return await self._validate_on_connection(
                connection, snapshot, minimum_papers=minimum_papers
            )

    async def finalize(
        self,
        snapshot_id: UUID,
        *,
        reviewer: str,
        minimum_papers: int = 100,
    ) -> FinalizedSnapshot:
        _validate_minimum(minimum_papers)
        if not isinstance(reviewer, str) or not reviewer.strip():
            raise ValueError("reviewer must be a non-empty string")
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                snapshot = await connection.fetchrow(
                    """
                    SELECT id, name, status, configuration_id, configuration
                    FROM snapshots WHERE id = $1 FOR UPDATE
                    """,
                    snapshot_id,
                )
                if snapshot is None:
                    raise ValueError("snapshot does not exist")
                if snapshot["status"] != "draft":
                    raise ValueError("only draft snapshots can be finalized")
                report = await self._validate_on_connection(
                    connection, snapshot, minimum_papers=minimum_papers
                )
                if not report.valid:
                    raise SnapshotValidationError(report)
                row = await connection.fetchrow(
                    """
                    UPDATE snapshots
                    SET status = 'finalized', finalized_at = now(), finalized_by = $2
                    WHERE id = $1
                    RETURNING finalized_at
                    """,
                    snapshot_id,
                    reviewer.strip(),
                )
                if row is None or not isinstance(row["finalized_at"], datetime):
                    raise RuntimeError(
                        "database did not return snapshot finalization time"
                    )
                return FinalizedSnapshot(
                    id=snapshot_id,
                    name=snapshot["name"],
                    configuration_id=snapshot["configuration_id"],
                    finalized_at=row["finalized_at"],
                    finalized_by=reviewer.strip(),
                    member_count=report.member_count,
                    index_configuration_id=report.index_configuration_id or "",
                )

    async def require_finalized(self, snapshot_id: UUID) -> FinalizedSnapshot:
        async with self._pool.acquire() as connection:
            row = await connection.fetchrow(
                """
                SELECT id, name, status, configuration_id, configuration,
                       finalized_at, finalized_by
                FROM snapshots WHERE id = $1
                """,
                snapshot_id,
            )
        if row is None or row["status"] != "finalized":
            raise ValueError("research requires a finalized snapshot")
        config = _json_object(row["configuration"])
        index_configuration_id = config.get("index_configuration_id")
        if not isinstance(index_configuration_id, str):
            raise ValueError("finalized snapshot has no index configuration identity")
        member_count = await self._pool.fetchval(
            "SELECT count(*) FROM snapshot_items WHERE snapshot_id = $1", snapshot_id
        )
        return FinalizedSnapshot(
            id=row["id"],
            name=row["name"],
            configuration_id=row["configuration_id"],
            finalized_at=row["finalized_at"],
            finalized_by=row["finalized_by"],
            member_count=member_count,
            index_configuration_id=index_configuration_id,
        )

    async def _require_draft(
        self, connection: asyncpg.Connection, snapshot_id: UUID
    ) -> None:
        status = await connection.fetchval(
            "SELECT status FROM snapshots WHERE id = $1 FOR UPDATE", snapshot_id
        )
        if status is None:
            raise ValueError("snapshot does not exist")
        if status != "draft":
            raise ValueError("only draft snapshots can change membership")

    async def _validate_on_connection(
        self,
        connection: asyncpg.Connection,
        snapshot: Mapping[str, object],
        *,
        minimum_papers: int,
    ) -> SnapshotValidationReport:
        snapshot_id = snapshot["id"]
        if not isinstance(snapshot_id, UUID):
            raise RuntimeError("database returned an invalid snapshot ID")
        items = await connection.fetch(
            """
            SELECT item.paper_id, extraction.status AS extraction_status,
                   extraction.output_sha256, extraction.source_artifact_id,
                   (SELECT count(*) FROM snapshot_item_chunks selected
                    WHERE selected.snapshot_id = item.snapshot_id
                      AND selected.paper_id = item.paper_id) AS chunk_count,
                   (SELECT count(*) FROM evidence_tables evidence_table
                    WHERE evidence_table.extraction_id = extraction.id
                      AND evidence_table.metadata ->> 'review_required' = 'true'
                      AND COALESCE(evidence_table.metadata ->> 'review_status', '') != 'passed'
                   ) AS unreviewed_flagged_tables,
                   EXISTS (
                       SELECT 1
                       FROM document_artifacts artifact
                       JOIN document_permission_evidence permission
                         ON permission.id = artifact.permission_evidence_id
                        AND permission.document_id = artifact.document_id
                       WHERE artifact.id = extraction.source_artifact_id
                         AND artifact.document_id = item.document_id
                         AND artifact.storage_permitted
                         AND artifact.indexing_permitted
                         AND permission.storage_permitted
                         AND permission.indexing_permitted
                   ) AS indexing_permitted
            FROM snapshot_items item
            LEFT JOIN extractions extraction
              ON extraction.id = item.extraction_id
             AND extraction.document_id = item.document_id
            WHERE item.snapshot_id = $1
            ORDER BY item.paper_id
            """,
            snapshot_id,
        )
        member_count = len(items)
        expected_chunks = 0
        issues: list[SnapshotIssue] = []
        if member_count < minimum_papers:
            issues.append(
                SnapshotIssue(
                    "below_minimum_membership",
                    f"snapshot has {member_count} papers; at least {minimum_papers} are required",
                )
            )
        if member_count == 0:
            issues.append(SnapshotIssue("empty_snapshot", "snapshot has no members"))
        for item in items:
            paper_id = item["paper_id"]
            if item["extraction_status"] not in {"completed", "partial"}:
                issues.append(
                    SnapshotIssue(
                        "missing_usable_extraction",
                        "selected document has no completed or partial extraction",
                        paper_id,
                    )
                )
                continue
            if item["output_sha256"] is None:
                issues.append(
                    SnapshotIssue(
                        "missing_extraction_fingerprint",
                        "extraction output has no retry fingerprint",
                        paper_id,
                    )
                )
            if item["source_artifact_id"] is None or not item["indexing_permitted"]:
                issues.append(
                    SnapshotIssue(
                        "indexing_permission_missing",
                        "the exact extraction source artifact lacks storage and indexing permission",
                        paper_id,
                    )
                )
            if item["unreviewed_flagged_tables"]:
                issues.append(
                    SnapshotIssue(
                        "flagged_table_review_pending",
                        f"{item['unreviewed_flagged_tables']} flagged table(s) need PDF association review",
                        paper_id,
                    )
                )
            chunk_count = item["chunk_count"]
            if not isinstance(chunk_count, int) or chunk_count <= 0:
                issues.append(
                    SnapshotIssue(
                        "missing_searchable_evidence",
                        "selected extraction has no searchable evidence chunks",
                        paper_id,
                    )
                )
            else:
                expected_chunks += chunk_count

        snapshot_configuration = _json_object(snapshot["configuration"])
        index_configuration_id = snapshot_configuration.get("index_configuration_id")
        if not isinstance(index_configuration_id, str) or not _SHA256_ID.fullmatch(
            index_configuration_id
        ):
            index_configuration_id = None
            issues.append(
                SnapshotIssue(
                    "missing_index_configuration",
                    "snapshot configuration must name an index_configuration_id",
                )
            )
        else:
            index_state = await connection.fetchrow(
                """
                SELECT status, expected_count, indexed_count
                FROM snapshot_index_states
                WHERE snapshot_id = $1 AND configuration_id = $2
                """,
                snapshot_id,
                index_configuration_id,
            )
            if index_state is None:
                issues.append(
                    SnapshotIssue(
                        "index_not_built", "snapshot has no recorded Qdrant index state"
                    )
                )
            elif index_state["status"] != "ready":
                issues.append(
                    SnapshotIssue(
                        "index_not_ready",
                        f"snapshot index state is {index_state['status']}",
                    )
                )
            elif (
                index_state["expected_count"] != expected_chunks
                or index_state["indexed_count"] != expected_chunks
            ):
                issues.append(
                    SnapshotIssue(
                        "index_count_mismatch",
                        "PostgreSQL evidence count and reconciled Qdrant count differ",
                    )
                )
            else:
                evidence_ids = await connection.fetch(
                    """
                    SELECT selected.chunk_id AS id
                    FROM snapshot_item_chunks selected
                    WHERE selected.snapshot_id = $1
                    ORDER BY selected.chunk_id
                    """,
                    snapshot_id,
                )
                expected_ids_sha256 = hashlib.sha256(
                    "\n".join(row["id"] for row in evidence_ids).encode("utf-8")
                ).hexdigest()
                index_state_details = await connection.fetchval(
                    """
                    SELECT details FROM snapshot_index_states
                    WHERE snapshot_id = $1 AND configuration_id = $2
                    """,
                    snapshot_id,
                    index_configuration_id,
                )
                details = _json_object(index_state_details)
                if (
                    details.get("evidence_ids_sha256") != expected_ids_sha256
                    or details.get("qdrant_evidence_ids_sha256") != expected_ids_sha256
                ):
                    issues.append(
                        SnapshotIssue(
                            "index_identity_mismatch",
                            "recorded Qdrant evidence identities do not match PostgreSQL",
                        )
                    )
        return SnapshotValidationReport(
            snapshot_id=snapshot_id,
            snapshot_status=str(snapshot["status"]),
            member_count=member_count,
            expected_chunk_count=expected_chunks,
            index_configuration_id=index_configuration_id,
            issues=tuple(issues),
        )


def _validate_sha256(value: str, name: str) -> None:
    if not isinstance(value, str) or not _SHA256_ID.fullmatch(value):
        raise ValueError(f"{name} must be a SHA-256 identity")


def _validate_minimum(minimum_papers: int) -> None:
    if (
        isinstance(minimum_papers, bool)
        or not isinstance(minimum_papers, int)
        or minimum_papers <= 0
    ):
        raise ValueError("minimum_papers must be a positive integer")


def _preview_table_cell(value: object) -> dict[str, object]:
    cell = _json_object(value)
    text = cell.get("text")
    if isinstance(text, str):
        cell["text"] = text[:_TABLE_CELL_PREVIEW_CHARACTERS]
        cell["text_truncated"] = len(text) > _TABLE_CELL_PREVIEW_CHARACTERS
    return cell


def _json_array(value: object, name: str) -> list[object]:
    if isinstance(value, str):
        parsed = json.loads(value)
    else:
        parsed = value
    if not isinstance(parsed, list):
        raise ValueError(f"stored {name} is not a JSON array")
    return parsed


def _json_object(value: object) -> dict[str, object]:
    if isinstance(value, str):
        parsed = json.loads(value)
    else:
        parsed = value
    if not isinstance(parsed, dict):
        raise ValueError("stored snapshot configuration is not a JSON object")
    return parsed
