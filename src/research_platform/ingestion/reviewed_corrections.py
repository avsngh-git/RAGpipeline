"""Create immutable, source-linked extractions from reviewed corrections."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import cast
from uuid import UUID, uuid5

from research_platform.ingestion.evidence import (
    ChunkingConfig,
    EvidenceUnit,
    ExtractedTable,
    ExtractionResult,
    OffsetTokenizer,
    SourceLocation,
    TableCell,
    chunk_section,
    chunk_table_rows,
)

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class CorrectionError(ValueError):
    """A correction package does not match the extraction it intends to fix."""


@dataclass(frozen=True)
class ReviewedExtraction:
    result: ExtractionResult
    evidence_units: tuple[EvidenceUnit, ...]
    corrected_table_ordinals: tuple[int, ...]
    reclassified_table_ordinals: tuple[int, ...]


def create_reviewed_extraction(
    original: ExtractionResult,
    correction: Mapping[str, object],
    *,
    reviewer: str,
    corrections_sha256: str,
    source_pdf_sha256: str,
    chunking: ChunkingConfig,
    tokenizer: OffsetTokenizer,
) -> ReviewedExtraction:
    """Apply a reviewed correction as a new extraction and rechunk its evidence.

    The original extraction is never edited. `correction` contains replacement
    tables, cell patches, and tables reclassified as caption-only figure evidence.
    Its SHA-256, reviewer, source PDF checksum, page numbers and parent extraction
    become part of the new extraction configuration and stable identity.
    """
    if not isinstance(reviewer, str) or not reviewer.strip():
        raise CorrectionError("reviewer must be a non-empty string")
    for label, value in (
        ("corrections_sha256", corrections_sha256),
        ("source_pdf_sha256", source_pdf_sha256),
    ):
        if not isinstance(value, str) or not _SHA256.fullmatch(value):
            raise CorrectionError(f"{label} must be a lowercase SHA-256 digest")
    _require_keys(
        correction,
        {
            "original_extraction_id",
            "source_pdf_sha256",
            "source_pages",
            "table_replacements",
            "table_patches",
            "figure_reclassifications",
        },
        "extraction correction",
    )
    if correction["original_extraction_id"] != str(original.extraction_id):
        raise CorrectionError("correction package names a different source extraction")
    if correction["source_pdf_sha256"] != source_pdf_sha256:
        raise CorrectionError("correction package source checksum does not match PDF")
    source_pages = _positive_integer_list(correction["source_pages"], "source_pages")
    if not source_pages:
        raise CorrectionError("source_pages must identify at least one PDF page")

    replacements = _object_list(correction["table_replacements"], "table_replacements")
    patches = _object_list(correction["table_patches"], "table_patches")
    figures = _object_list(
        correction["figure_reclassifications"], "figure_reclassifications"
    )
    original_by_ordinal = {table.ordinal: table for table in original.tables}
    if len(original_by_ordinal) != len(original.tables):
        raise CorrectionError("source extraction has duplicate table ordinals")

    operation_ordinals: list[int] = []
    for item in (*replacements, *patches, *figures):
        ordinal = _non_negative_int(item.get("table_ordinal"), "table_ordinal")
        if ordinal not in original_by_ordinal:
            raise CorrectionError(
                f"table ordinal {ordinal} is not in source extraction"
            )
        operation_ordinals.append(ordinal)
        page_number = _positive_int(item.get("page_number_1_based"), "page number")
        if page_number not in source_pages:
            raise CorrectionError("correction page is absent from source_pages")
        if original_by_ordinal[ordinal].source_location.page_index_zero_based != (
            page_number - 1
        ):
            raise CorrectionError(
                "correction page does not match source table location"
            )
    if len(set(operation_ordinals)) != len(operation_ordinals):
        raise CorrectionError(
            "each source table can have only one correction operation"
        )

    replacement_by_ordinal = {
        _non_negative_int(item["table_ordinal"], "table_ordinal"): item
        for item in replacements
    }
    patch_by_ordinal = {
        _non_negative_int(item["table_ordinal"], "table_ordinal"): item
        for item in patches
    }
    removed_ordinals = {
        _non_negative_int(item["table_ordinal"], "table_ordinal") for item in figures
    }
    corrected_tables: list[ExtractedTable] = []
    corrected_ordinals: list[int] = []
    for table in original.tables:
        if table.ordinal in removed_ordinals:
            continue
        replacement = replacement_by_ordinal.get(table.ordinal)
        if replacement is not None:
            corrected_tables.append(_replacement_table(table, replacement))
            corrected_ordinals.append(table.ordinal)
            continue
        patch = patch_by_ordinal.get(table.ordinal)
        if patch is not None:
            corrected_tables.append(_patched_table(table, patch))
            corrected_ordinals.append(table.ordinal)
            continue
        corrected_tables.append(table)

    configuration = dict(original.configuration)
    configuration["reviewed_correction"] = {
        "schema_version": 1,
        "source_extraction_id": str(original.extraction_id),
        "source_configuration_id": original.configuration_id,
        "source_pdf_sha256": source_pdf_sha256,
        "corrections_sha256": corrections_sha256,
        "reviewer": reviewer.strip(),
        "source_pages": list(source_pages),
    }
    canonical_configuration = json.dumps(
        configuration, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    configuration_id = (
        "sha256:" + hashlib.sha256(canonical_configuration.encode("utf-8")).hexdigest()
    )
    extraction_id = uuid5(original.document_id, configuration_id)
    result = ExtractionResult(
        document_id=original.document_id,
        extraction_id=extraction_id,
        extractor_name="reviewed-correction",
        extractor_revision="source-linked-v1",
        configuration_id=configuration_id,
        status=original.status,
        source_artifact_id=original.source_artifact_id,
        sections=original.sections,
        tables=tuple(corrected_tables),
        failure_category=original.failure_category,
        configuration=configuration,
    )

    units: list[EvidenceUnit] = []
    for section in result.sections:
        units.extend(
            chunk_section(
                section,
                document_id=result.document_id,
                extraction_id=result.extraction_id,
                config=chunking,
                tokenizer=tokenizer,
            )
        )
    for table in result.tables:
        units.extend(
            chunk_table_rows(
                table,
                document_id=result.document_id,
                extraction_id=result.extraction_id,
                config=chunking,
                tokenizer=tokenizer,
            )
        )
    units.extend(
        _figure_units(
            figures,
            document_id=result.document_id,
            extraction_id=result.extraction_id,
            source_pages=set(source_pages),
        )
    )
    return ReviewedExtraction(
        result=result,
        evidence_units=tuple(units),
        corrected_table_ordinals=tuple(sorted(corrected_ordinals)),
        reclassified_table_ordinals=tuple(sorted(removed_ordinals)),
    )


def _replacement_table(
    original: ExtractedTable, correction: Mapping[str, object]
) -> ExtractedTable:
    _require_keys(
        correction,
        {
            "table_ordinal",
            "page_number_1_based",
            "caption",
            "units",
            "footnotes",
            "header_rows",
            "rows",
            "merged_cells",
        },
        "table replacement",
    )
    if correction["table_ordinal"] != original.ordinal:
        raise CorrectionError("replacement table ordinal changed during validation")
    if correction["page_number_1_based"] != (
        original.source_location.page_index_zero_based + 1
        if original.source_location.page_index_zero_based is not None
        else None
    ):
        raise CorrectionError("replacement page does not match source table")
    rows = _string_matrix(correction["rows"])
    header_rows = _non_negative_int(correction["header_rows"], "header_rows")
    if header_rows > len(rows):
        raise CorrectionError("header_rows exceeds corrected table height")
    merged_ranges = _merged_ranges(correction["merged_cells"], rows)
    cells: list[TableCell] = []
    for row_index, row in enumerate(rows):
        for column_index, text in enumerate(row):
            merged_range = merged_ranges.get((row_index, column_index))
            column_headers = tuple(
                (header_row, header_column)
                for header_row in range(header_rows)
                for header_column in range(column_index + 1)
                if _header_applies(
                    header_row,
                    header_column,
                    column_index,
                    rows,
                    merged_ranges,
                )
                and rows[header_row][header_column].strip()
            )
            row_headers = (
                ((row_index, 0),)
                if row_index >= header_rows and column_index > 0 and row[0].strip()
                else ()
            )
            cells.append(
                TableCell(
                    row=row_index,
                    column=column_index,
                    text=text,
                    row_header_cells=row_headers,
                    column_header_cells=column_headers,
                    merged_range=merged_range,
                )
            )
    return ExtractedTable(
        ordinal=original.ordinal,
        caption=_nullable_string(correction["caption"], "caption"),
        units=_nullable_string(correction["units"], "units"),
        footnotes=tuple(_string_list(correction["footnotes"], "footnotes")),
        header_rows=header_rows,
        cells=tuple(cells),
        source_location=original.source_location,
        section_ordinal=original.section_ordinal,
        requires_vision_review=True,
    )


def _patched_table(
    original: ExtractedTable, correction: Mapping[str, object]
) -> ExtractedTable:
    _require_keys(
        correction,
        {"table_ordinal", "page_number_1_based", "cell_updates"},
        "table patch",
        optional={"caption"},
    )
    cells = {(cell.row, cell.column): cell for cell in original.cells}
    updates = _object_list(correction["cell_updates"], "cell_updates")
    if not updates:
        raise CorrectionError("table patch must update at least one cell")
    for update in updates:
        _require_keys(
            update, {"row", "column", "text"}, "cell update", optional={"expected_text"}
        )
        row = _non_negative_int(update["row"], "cell row")
        column = _non_negative_int(update["column"], "cell column")
        cell = cells.get((row, column))
        if cell is None:
            raise CorrectionError("cell update points outside the source table")
        expected_text = update.get("expected_text")
        if expected_text is not None and expected_text != cell.text:
            raise CorrectionError("cell update expected text does not match source")
        cells[(row, column)] = TableCell(
            row=cell.row,
            column=cell.column,
            text=_string(update["text"], "cell text"),
            row_header_cells=cell.row_header_cells,
            column_header_cells=cell.column_header_cells,
            merged_range=cell.merged_range,
        )
    caption = original.caption
    if "caption" in correction:
        caption = _nullable_string(correction["caption"], "caption")
    return ExtractedTable(
        ordinal=original.ordinal,
        caption=caption,
        units=original.units,
        footnotes=original.footnotes,
        header_rows=original.header_rows,
        cells=tuple(cells[key] for key in sorted(cells)),
        source_location=original.source_location,
        section_ordinal=original.section_ordinal,
        requires_vision_review=True,
    )


def _figure_units(
    corrections: Sequence[Mapping[str, object]],
    *,
    document_id: UUID,
    extraction_id: UUID,
    source_pages: set[int],
) -> tuple[EvidenceUnit, ...]:
    units: list[EvidenceUnit] = []
    for ordinal, correction in enumerate(corrections):
        _require_keys(
            correction,
            {
                "table_ordinal",
                "page_number_1_based",
                "caption",
                "section_ordinal",
            },
            "figure reclassification",
        )
        table_ordinal = _non_negative_int(correction["table_ordinal"], "table_ordinal")
        page_number = _positive_int(
            correction["page_number_1_based"], "figure page number"
        )
        if page_number not in source_pages:
            raise CorrectionError("figure page is absent from source_pages")
        section_ordinal = correction["section_ordinal"]
        if section_ordinal is not None:
            section_ordinal = _non_negative_int(section_ordinal, "section_ordinal")
        caption = _string(correction["caption"], "figure caption")
        units.append(
            EvidenceUnit.create(
                document_id=document_id,
                extraction_id=extraction_id,
                section_ordinal=section_ordinal,
                ordinal=ordinal,
                kind="figure",
                content=caption,
                start_offset=None,
                end_offset=None,
                source_location=SourceLocation(page_index_zero_based=page_number - 1),
                identity_context={"reclassified_source_table_ordinal": table_ordinal},
                metadata={
                    "caption": caption,
                    "reviewed_correction": True,
                    "source_table_ordinal": table_ordinal,
                },
            )
        )
    return tuple(units)


def _merged_ranges(
    raw: object, rows: Sequence[Sequence[str]]
) -> dict[tuple[int, int], tuple[int, int, int, int]]:
    ranges: dict[tuple[int, int], tuple[int, int, int, int]] = {}
    for item in _object_list(raw, "merged_cells"):
        _require_keys(item, {"row", "column", "row_span", "column_span"}, "merged cell")
        row = _non_negative_int(item["row"], "merged row")
        column = _non_negative_int(item["column"], "merged column")
        row_span = _positive_int(item["row_span"], "merged row span")
        column_span = _positive_int(item["column_span"], "merged column span")
        row_end = row + row_span - 1
        column_end = column + column_span - 1
        if row_end >= len(rows) or column_end >= len(rows[0]):
            raise CorrectionError("merged cell range exceeds corrected table shape")
        value = (row, column, row_end, column_end)
        for current_row in range(row, row_end + 1):
            for current_column in range(column, column_end + 1):
                coordinate = (current_row, current_column)
                if coordinate in ranges:
                    raise CorrectionError("merged cell ranges overlap")
                ranges[coordinate] = value
    return ranges


def _header_applies(
    header_row: int,
    header_column: int,
    column: int,
    rows: Sequence[Sequence[str]],
    merged_ranges: Mapping[tuple[int, int], tuple[int, int, int, int]],
) -> bool:
    merge = merged_ranges.get((header_row, header_column))
    if merge is not None:
        return merge[1] <= column <= merge[3]
    return header_column == column


def _string_matrix(value: object) -> tuple[tuple[str, ...], ...]:
    if not isinstance(value, list) or not value:
        raise CorrectionError("rows must be a non-empty list of rows")
    rows = tuple(
        tuple(_string(cell, "table cell") for cell in row)
        for row in value
        if isinstance(row, list)
    )
    if len(rows) != len(value) or not rows or not rows[0]:
        raise CorrectionError("rows must contain non-empty lists of string cells")
    width = len(rows[0])
    if any(len(row) != width for row in rows):
        raise CorrectionError("corrected table rows must have a uniform width")
    return rows


def _object_list(value: object, label: str) -> tuple[Mapping[str, object], ...]:
    if not isinstance(value, list) or any(
        not isinstance(item, Mapping) for item in value
    ):
        raise CorrectionError(f"{label} must be a list of objects")
    return tuple(cast(Mapping[str, object], item) for item in value)


def _string_list(value: object, label: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise CorrectionError(f"{label} must be a list of strings")
    return cast(list[str], value)


def _positive_integer_list(value: object, label: str) -> tuple[int, ...]:
    if not isinstance(value, list):
        raise CorrectionError(f"{label} must be a list of positive integers")
    result = tuple(_positive_int(item, label) for item in value)
    if len(set(result)) != len(result):
        raise CorrectionError(f"{label} must not contain duplicates")
    return result


def _require_keys(
    value: Mapping[str, object],
    required: set[str],
    label: str,
    *,
    optional: set[str] | None = None,
) -> None:
    allowed = required | (optional or set())
    if not required <= value.keys() or not value.keys() <= allowed:
        raise CorrectionError(f"{label} fields are incomplete or unknown")


def _non_negative_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise CorrectionError(f"{label} must be a non-negative integer")
    return value


def _positive_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise CorrectionError(f"{label} must be a positive integer")
    return value


def _string(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise CorrectionError(f"{label} must be a string")
    return value


def _nullable_string(value: object, label: str) -> str | None:
    if value is not None and not isinstance(value, str):
        raise CorrectionError(f"{label} must be a string or null")
    return value
