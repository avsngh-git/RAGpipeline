"""Persist source-linked extraction outputs and searchable evidence."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

import asyncpg  # type: ignore[import-untyped]

from research_platform.ingestion.evidence import (
    EvidenceUnit,
    ExtractedTable,
    ExtractionResult,
)


class EvidenceConflict(ValueError):
    """One extraction configuration produced different stored outputs."""


@dataclass(frozen=True)
class EvidencePersistenceResult:
    extraction_id: UUID
    section_count: int
    table_count: int
    evidence_unit_count: int
    reused_existing: bool


class EvidenceRepository:
    """Store extraction outputs transactionally and make retries idempotent."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def persist(
        self,
        result: ExtractionResult,
        evidence_units: Sequence[EvidenceUnit],
    ) -> EvidencePersistenceResult:
        if any(unit.document_id != result.document_id for unit in evidence_units):
            raise ValueError("evidence units must reference the extraction document")
        if any(unit.extraction_id != result.extraction_id for unit in evidence_units):
            raise ValueError("evidence units must reference the extraction ID")
        if len({unit.id for unit in evidence_units}) != len(evidence_units):
            raise ValueError("evidence unit IDs must be unique")
        if result.status == "failed" and evidence_units:
            raise ValueError("failed extraction must not publish evidence units")
        output_sha256 = _output_fingerprint(result, evidence_units)

        async with self._pool.acquire() as connection:
            async with connection.transaction():
                inserted = await connection.fetchval(
                    """
                    INSERT INTO extractions
                        (id, document_id, source_artifact_id, extractor_name,
                         extractor_revision, configuration_id, configuration, status,
                         created_at, completed_at, output_sha256)
                    VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8, $9, $9, $10)
                    ON CONFLICT (document_id, configuration_id) DO NOTHING
                    RETURNING id
                    """,
                    result.extraction_id,
                    result.document_id,
                    result.source_artifact_id,
                    result.extractor_name,
                    result.extractor_revision,
                    result.configuration_id,
                    json.dumps(dict(result.configuration), sort_keys=True),
                    result.status,
                    datetime.now(timezone.utc),
                    output_sha256,
                )
                if inserted is None:
                    existing = await connection.fetchrow(
                        """
                        SELECT id, output_sha256, status FROM extractions
                        WHERE document_id = $1 AND configuration_id = $2
                        FOR UPDATE
                        """,
                        result.document_id,
                        result.configuration_id,
                    )
                    if existing is None or existing["id"] != result.extraction_id:
                        raise EvidenceConflict(
                            "configuration is already bound to another extraction ID"
                        )
                    if existing["status"] == "failed" and result.status != "failed":
                        prior_outputs = await connection.fetchval(
                            """
                            SELECT EXISTS (
                                SELECT 1 FROM sections
                                WHERE document_id = $1 AND extraction_id = $2
                                UNION ALL
                                SELECT 1 FROM evidence_tables WHERE extraction_id = $2
                                UNION ALL
                                SELECT 1 FROM evidence_units WHERE extraction_id = $2
                            )
                            """,
                            result.document_id,
                            result.extraction_id,
                        )
                        if prior_outputs:
                            raise EvidenceConflict(
                                "failed extraction unexpectedly contains output rows"
                            )
                        await connection.execute(
                            """
                            UPDATE extractions
                            SET status = $2, source_artifact_id = $3,
                                configuration = $4::jsonb,
                                output_sha256 = $5, completed_at = now()
                            WHERE id = $1
                            """,
                            result.extraction_id,
                            result.status,
                            result.source_artifact_id,
                            json.dumps(dict(result.configuration), sort_keys=True),
                            output_sha256,
                        )
                        inserted = result.extraction_id
                    else:
                        if existing["output_sha256"] != output_sha256:
                            raise EvidenceConflict(
                                "same document and configuration produced different outputs"
                            )
                        return _result(result, evidence_units, reused=True)

                section_ids = await self._persist_sections(connection, result)
                await self._persist_tables(connection, result, section_ids)
                await self._persist_units(
                    connection, result, evidence_units, section_ids
                )

        return _result(result, evidence_units, reused=False)

    async def _persist_sections(
        self,
        connection: asyncpg.Connection,
        result: ExtractionResult,
    ) -> dict[int, UUID]:
        section_ids: dict[int, UUID] = {}
        ordinals: set[int] = set()
        for section in result.sections:
            if section.ordinal in ordinals:
                raise ValueError("section ordinals must be unique")
            ordinals.add(section.ordinal)
            location = {
                "location": section.source_location.to_dict(),
                "heading_path": list(section.heading_path),
            }
            section_id = await connection.fetchval(
                """
                INSERT INTO sections
                    (document_id, extraction_id, title, ordinal, source_location)
                VALUES ($1, $2, $3, $4, $5::jsonb) RETURNING id
                """,
                result.document_id,
                result.extraction_id,
                section.heading_path[-1] if section.heading_path else "",
                section.ordinal,
                json.dumps(location, sort_keys=True),
            )
            if not isinstance(section_id, UUID):
                raise RuntimeError("database did not return a section ID")
            section_ids[section.ordinal] = section_id
            await connection.execute(
                """
                INSERT INTO evidence_units
                    (id, extraction_id, section_id, kind, content, source_location, metadata)
                VALUES ($1, $2, $3, 'text', $4, $5::jsonb, $6::jsonb)
                """,
                f"section:{result.extraction_id}:{section.ordinal}",
                result.extraction_id,
                section_id,
                section.text,
                json.dumps(section.source_location.to_dict(), sort_keys=True),
                json.dumps(
                    {"heading_path": list(section.heading_path)}, sort_keys=True
                ),
            )
        return section_ids

    async def _persist_tables(
        self,
        connection: asyncpg.Connection,
        result: ExtractionResult,
        section_ids: Mapping[int, UUID],
    ) -> None:
        ordinals: set[int] = set()
        for table in result.tables:
            if table.ordinal in ordinals:
                raise ValueError("table ordinals must be unique")
            ordinals.add(table.ordinal)
            section_id = _section_id(table.section_ordinal, section_ids)
            await connection.execute(
                """
                INSERT INTO evidence_tables
                    (extraction_id, section_id, ordinal, caption, units, footnotes,
                     table_data, source_location, metadata)
                VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7::jsonb, $8::jsonb, $9::jsonb)
                """,
                result.extraction_id,
                section_id,
                table.ordinal,
                table.caption,
                table.units,
                json.dumps(list(table.footnotes), sort_keys=True),
                json.dumps(_table_data(table), sort_keys=True),
                json.dumps(table.source_location.to_dict(), sort_keys=True),
                json.dumps(
                    {
                        "section_ordinal": table.section_ordinal,
                        "review_required": table.requires_vision_review,
                        "review_status": (
                            "pending"
                            if table.requires_vision_review
                            else "not_required"
                        ),
                    },
                    sort_keys=True,
                ),
            )

    async def _persist_units(
        self,
        connection: asyncpg.Connection,
        result: ExtractionResult,
        units: Sequence[EvidenceUnit],
        section_ids: Mapping[int, UUID],
    ) -> None:
        for unit in units:
            section_id = _section_id(unit.section_ordinal, section_ids)
            location_json = json.dumps(unit.source_location.to_dict(), sort_keys=True)
            metadata_json = json.dumps(dict(unit.metadata), sort_keys=True)
            await connection.execute(
                """
                INSERT INTO evidence_units
                    (id, extraction_id, section_id, kind, content, start_offset,
                     end_offset, source_location, metadata)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, $9::jsonb)
                """,
                unit.id,
                result.extraction_id,
                section_id,
                unit.kind,
                unit.content,
                unit.start_offset,
                unit.end_offset,
                location_json,
                metadata_json,
            )
            await connection.execute(
                """
                INSERT INTO chunks
                    (id, document_id, section_id, text, start_offset, end_offset,
                     metadata, extraction_id, kind, source_location)
                VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8, $9, $10::jsonb)
                """,
                unit.id,
                result.document_id,
                section_id,
                unit.content,
                unit.start_offset,
                unit.end_offset,
                metadata_json,
                result.extraction_id,
                unit.kind,
                location_json,
            )


def _section_id(
    section_ordinal: int | None, section_ids: Mapping[int, UUID]
) -> UUID | None:
    if section_ordinal is None:
        return None
    section_id = section_ids.get(section_ordinal)
    if section_id is None:
        raise ValueError("source section ordinal does not exist in the extraction")
    return section_id


def _table_data(table: ExtractedTable) -> dict[str, object]:
    return {
        "row_count": table.row_count,
        "column_count": table.column_count,
        "header_rows": table.header_rows,
        "cells": [
            {
                "row": cell.row,
                "column": cell.column,
                "text": cell.text,
                "row_header_cells": [
                    list(reference) for reference in cell.row_header_cells
                ],
                "column_header_cells": [
                    list(reference) for reference in cell.column_header_cells
                ],
                "merged_range": list(cell.merged_range) if cell.merged_range else None,
            }
            for cell in table.cells
        ],
    }


def _output_fingerprint(result: ExtractionResult, units: Sequence[EvidenceUnit]) -> str:
    payload: dict[str, object] = {
        "document_id": str(result.document_id),
        "extraction_id": str(result.extraction_id),
        "extractor_name": result.extractor_name,
        "extractor_revision": result.extractor_revision,
        "configuration_id": result.configuration_id,
        "source_artifact_id": (
            str(result.source_artifact_id) if result.source_artifact_id else None
        ),
        "configuration": dict(result.configuration),
        "status": result.status,
        "failure_category": result.failure_category,
        "sections": [
            {
                "ordinal": section.ordinal,
                "heading_path": list(section.heading_path),
                "text": section.text,
                "source_location": section.source_location.to_dict(),
            }
            for section in sorted(result.sections, key=lambda item: item.ordinal)
        ],
        "tables": [
            {
                "ordinal": table.ordinal,
                "caption": table.caption,
                "units": table.units,
                "footnotes": list(table.footnotes),
                "header_rows": table.header_rows,
                "cells": _table_data(table)["cells"],
                "source_location": table.source_location.to_dict(),
                "section_ordinal": table.section_ordinal,
            }
            for table in sorted(result.tables, key=lambda item: item.ordinal)
        ],
        "evidence_units": [
            {
                "id": unit.id,
                "section_ordinal": unit.section_ordinal,
                "ordinal": unit.ordinal,
                "kind": unit.kind,
                "content": unit.content,
                "start_offset": unit.start_offset,
                "end_offset": unit.end_offset,
                "source_location": unit.source_location.to_dict(),
                "metadata": dict(unit.metadata),
            }
            for unit in sorted(units, key=lambda item: item.id)
        ],
    }
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _result(
    extraction: ExtractionResult,
    units: Sequence[EvidenceUnit],
    *,
    reused: bool,
) -> EvidencePersistenceResult:
    return EvidencePersistenceResult(
        extraction_id=extraction.extraction_id,
        section_count=len(extraction.sections),
        table_count=len(extraction.tables),
        evidence_unit_count=len(units),
        reused_existing=reused,
    )
