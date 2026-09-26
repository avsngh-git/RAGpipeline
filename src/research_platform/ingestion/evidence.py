"""Source-linked extraction contracts and deterministic evidence chunking."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal, Protocol
from uuid import UUID

EvidenceKind = Literal[
    "text", "table", "table_row_group", "caption", "figure", "equation"
]
ExtractionStatus = Literal["completed", "partial", "failed"]
COORDINATE_SYSTEM = "top-left-normalized-0-1"


class EvidenceChunkingError(ValueError):
    """A valid evidence item cannot fit the configured searchable token limit."""


@dataclass(frozen=True)
class SourceLocation:
    """Location within the exact selected document version."""

    page_index_zero_based: int | None = None
    printed_page_label: str | None = None
    bounding_box: tuple[float, float, float, float] | None = None
    coordinate_system: str | None = None

    def __post_init__(self) -> None:
        if self.page_index_zero_based is not None and (
            isinstance(self.page_index_zero_based, bool)
            or not isinstance(self.page_index_zero_based, int)
            or self.page_index_zero_based < 0
        ):
            raise ValueError("page_index_zero_based must be a non-negative integer")
        if self.printed_page_label is not None and (
            not isinstance(self.printed_page_label, str)
            or not self.printed_page_label.strip()
        ):
            raise ValueError("printed_page_label must be a non-empty string or null")
        if self.bounding_box is None:
            if self.coordinate_system is not None:
                raise ValueError("coordinate_system requires a bounding_box")
            return
        if (
            not isinstance(self.bounding_box, tuple)
            or len(self.bounding_box) != 4
            or any(
                isinstance(coordinate, bool)
                or not isinstance(coordinate, (int, float))
                or not math.isfinite(coordinate)
                or not 0.0 <= coordinate <= 1.0
                for coordinate in self.bounding_box
            )
            or self.bounding_box[0] >= self.bounding_box[2]
            or self.bounding_box[1] >= self.bounding_box[3]
        ):
            raise ValueError("bounding_box must be a normalized x1,y1,x2,y2 rectangle")
        if self.coordinate_system != COORDINATE_SYSTEM:
            raise ValueError("coordinate_system must be top-left-normalized-0-1")

    def to_dict(self) -> dict[str, object]:
        return {
            "page_index_zero_based": self.page_index_zero_based,
            "printed_page_label": self.printed_page_label,
            "bounding_box": list(self.bounding_box) if self.bounding_box else None,
            "coordinate_system": self.coordinate_system,
        }


@dataclass(frozen=True)
class ExtractedSection:
    ordinal: int
    heading_path: tuple[str, ...]
    text: str
    source_location: SourceLocation = SourceLocation()

    def __post_init__(self) -> None:
        if (
            isinstance(self.ordinal, bool)
            or not isinstance(self.ordinal, int)
            or self.ordinal < 0
        ):
            raise ValueError("section ordinal must be a non-negative integer")
        if any(
            not isinstance(title, str) or not title.strip()
            for title in self.heading_path
        ):
            raise ValueError("section headings must be non-empty strings")
        if not isinstance(self.text, str):
            raise ValueError("section text must be a string")


@dataclass(frozen=True)
class TableCell:
    row: int
    column: int
    text: str
    row_header_cells: tuple[tuple[int, int], ...] = ()
    column_header_cells: tuple[tuple[int, int], ...] = ()
    merged_range: tuple[int, int, int, int] | None = None

    def __post_init__(self) -> None:
        if (
            isinstance(self.row, bool)
            or not isinstance(self.row, int)
            or isinstance(self.column, bool)
            or not isinstance(self.column, int)
            or self.row < 0
            or self.column < 0
        ):
            raise ValueError("table cell coordinates must be non-negative integers")
        if not isinstance(self.text, str):
            raise ValueError("table cell text must be a string")
        for name, references in (
            ("row_header_cells", self.row_header_cells),
            ("column_header_cells", self.column_header_cells),
        ):
            if not isinstance(references, tuple) or any(
                not isinstance(reference, tuple)
                or len(reference) != 2
                or any(
                    isinstance(value, bool) or not isinstance(value, int) or value < 0
                    for value in reference
                )
                for reference in references
            ):
                raise ValueError(f"{name} must contain non-negative cell coordinates")
        if self.merged_range is not None:
            if (
                not isinstance(self.merged_range, tuple)
                or len(self.merged_range) != 4
                or any(
                    isinstance(value, bool) or not isinstance(value, int)
                    for value in self.merged_range
                )
            ):
                raise ValueError("merged_range must contain four integer indices")
            row_start, column_start, row_end, column_end = self.merged_range
            if (
                row_start < 0
                or column_start < 0
                or row_end < row_start
                or column_end < column_start
                or not row_start <= self.row <= row_end
                or not column_start <= self.column <= column_end
            ):
                raise ValueError("merged_range must contain the cell coordinates")


@dataclass(frozen=True)
class ExtractedTable:
    ordinal: int
    caption: str | None
    units: str | None
    footnotes: tuple[str, ...]
    header_rows: int
    cells: tuple[TableCell, ...]
    source_location: SourceLocation = SourceLocation()
    section_ordinal: int | None = None
    requires_vision_review: bool = False

    def __post_init__(self) -> None:
        if (
            isinstance(self.ordinal, bool)
            or not isinstance(self.ordinal, int)
            or self.ordinal < 0
        ):
            raise ValueError("table ordinal must be a non-negative integer")
        if (
            isinstance(self.header_rows, bool)
            or not isinstance(self.header_rows, int)
            or self.header_rows < 0
        ):
            raise ValueError("header_rows must be a non-negative integer")
        if self.caption is not None and not isinstance(self.caption, str):
            raise ValueError("table caption must be a string or null")
        if self.units is not None and not isinstance(self.units, str):
            raise ValueError("table units must be a string or null")
        if not isinstance(self.footnotes, tuple) or any(
            not isinstance(note, str) for note in self.footnotes
        ):
            raise ValueError("table footnotes must be a tuple of strings")
        if not isinstance(self.cells, tuple) or any(
            not isinstance(cell, TableCell) for cell in self.cells
        ):
            raise ValueError("table cells must be a tuple of TableCell values")
        coordinates = {(cell.row, cell.column) for cell in self.cells}
        if not isinstance(self.requires_vision_review, bool):
            raise ValueError("requires_vision_review must be a boolean")
        if self.section_ordinal is not None and (
            isinstance(self.section_ordinal, bool)
            or not isinstance(self.section_ordinal, int)
            or self.section_ordinal < 0
        ):
            raise ValueError("table section_ordinal must be non-negative or null")
        if self.header_rows > self.row_count:
            raise ValueError("header_rows cannot exceed the table row count")
        if len(coordinates) != len(self.cells):
            raise ValueError("table cell coordinates must be unique")
        for cell in self.cells:
            if any(reference not in coordinates for reference in cell.row_header_cells):
                raise ValueError(
                    "row header relationship points to a missing table cell"
                )
            if any(
                reference not in coordinates for reference in cell.column_header_cells
            ):
                raise ValueError(
                    "column header relationship points to a missing table cell"
                )

    @property
    def row_count(self) -> int:
        return max((cell.row for cell in self.cells), default=-1) + 1

    @property
    def column_count(self) -> int:
        return max((cell.column for cell in self.cells), default=-1) + 1

    def cell_text(self, row: int, column: int) -> str:
        return next(
            (
                cell.text
                for cell in self.cells
                if cell.row == row and cell.column == column
            ),
            "",
        )


@dataclass(frozen=True)
class ExtractionResult:
    document_id: UUID
    extraction_id: UUID
    extractor_name: str
    extractor_revision: str
    configuration_id: str
    status: ExtractionStatus
    source_artifact_id: UUID | None = None
    sections: tuple[ExtractedSection, ...] = ()
    tables: tuple[ExtractedTable, ...] = ()
    failure_category: str | None = None
    configuration: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.status not in {"completed", "partial", "failed"}:
            raise ValueError("extraction status must be completed, partial or failed")
        if self.source_artifact_id is not None and not isinstance(
            self.source_artifact_id, UUID
        ):
            raise ValueError("source_artifact_id must be a UUID or null")
        if (
            not isinstance(self.extractor_name, str)
            or not self.extractor_name.strip()
            or not isinstance(self.extractor_revision, str)
            or not self.extractor_revision.strip()
        ):
            raise ValueError("extractor name and revision must be non-empty")
        if (
            not isinstance(self.configuration_id, str)
            or not self.configuration_id.strip()
        ):
            raise ValueError("extraction configuration ID must be non-empty")
        if self.status == "completed" and not (self.sections or self.tables):
            raise ValueError("completed extraction must contain usable text or tables")
        if self.status == "failed" and not self.failure_category:
            raise ValueError("failed extraction must include a failure category")
        if self.status == "failed" and (self.sections or self.tables):
            raise ValueError("failed extraction must not publish partial evidence")


@dataclass(frozen=True)
class EvidenceUnit:
    id: str
    document_id: UUID
    extraction_id: UUID
    section_ordinal: int | None
    ordinal: int
    kind: EvidenceKind
    content: str
    start_offset: int | None
    end_offset: int | None
    source_location: SourceLocation
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.content, str):
            raise ValueError("evidence content must be a string")
        if not isinstance(self.id, str) or not self.id.strip():
            raise ValueError("evidence unit ID must be a non-empty string")
        if self.kind not in {
            "text",
            "table",
            "table_row_group",
            "caption",
            "figure",
            "equation",
        }:
            raise ValueError("unsupported evidence kind")
        if (
            isinstance(self.ordinal, bool)
            or not isinstance(self.ordinal, int)
            or self.ordinal < 0
            or (
                self.section_ordinal is not None
                and (
                    isinstance(self.section_ordinal, bool)
                    or not isinstance(self.section_ordinal, int)
                    or self.section_ordinal < 0
                )
            )
        ):
            raise ValueError("evidence ordinals must be non-negative integers")
        if (self.start_offset is None) != (self.end_offset is None):
            raise ValueError("evidence offsets must both be present or both be absent")
        if (
            self.start_offset is not None
            and self.end_offset is not None
            and (self.start_offset < 0 or self.end_offset < self.start_offset)
        ):
            raise ValueError("evidence offsets must be an ordered non-negative range")

    @classmethod
    def create(
        cls,
        *,
        document_id: UUID,
        extraction_id: UUID,
        section_ordinal: int | None,
        ordinal: int,
        kind: EvidenceKind,
        content: str,
        start_offset: int | None,
        end_offset: int | None,
        source_location: SourceLocation,
        metadata: Mapping[str, object] | None = None,
        identity_context: Mapping[str, object] | None = None,
    ) -> EvidenceUnit:
        identity_payload = {
            "document_id": str(document_id),
            "extraction_id": str(extraction_id),
            "section_ordinal": section_ordinal,
            "ordinal": ordinal,
            "kind": kind,
            "content_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
            "start_offset": start_offset,
            "end_offset": end_offset,
            "source_location": source_location.to_dict(),
            "identity_context": dict(identity_context or {}),
        }
        canonical = json.dumps(
            identity_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        unit_id = "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return cls(
            id=unit_id,
            document_id=document_id,
            extraction_id=extraction_id,
            section_ordinal=section_ordinal,
            ordinal=ordinal,
            kind=kind,
            content=content,
            start_offset=start_offset,
            end_offset=end_offset,
            source_location=source_location,
            metadata=dict(metadata or {}),
        )


@dataclass(frozen=True)
class TokenSpan:
    start: int
    end: int

    def __post_init__(self) -> None:
        if (
            isinstance(self.start, bool)
            or not isinstance(self.start, int)
            or isinstance(self.end, bool)
            or not isinstance(self.end, int)
            or self.start < 0
            or self.end <= self.start
        ):
            raise ValueError("token spans must be positive, non-empty integer ranges")


class OffsetTokenizer(Protocol):
    """Provide token start/end offsets from the selected model tokenizer."""

    def token_spans(self, text: str) -> Sequence[TokenSpan]: ...


@dataclass(frozen=True)
class ChunkingConfig:
    maximum_text_tokens: int
    overlapping_text_tokens: int
    maximum_table_rows_per_group: int

    def __post_init__(self) -> None:
        for name, value in (
            ("maximum_text_tokens", self.maximum_text_tokens),
            ("overlapping_text_tokens", self.overlapping_text_tokens),
            ("maximum_table_rows_per_group", self.maximum_table_rows_per_group),
        ):
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{name} must be an integer")
        if self.maximum_text_tokens <= 0 or self.maximum_table_rows_per_group <= 0:
            raise ValueError("text and table chunk limits must be positive")
        if not 0 <= self.overlapping_text_tokens < self.maximum_text_tokens:
            raise ValueError("text overlap must be non-negative and below the maximum")

    def to_dict(self) -> dict[str, int]:
        return {
            "schema_version": 1,
            "maximum_text_tokens": self.maximum_text_tokens,
            "overlapping_text_tokens": self.overlapping_text_tokens,
            "maximum_table_rows_per_group": self.maximum_table_rows_per_group,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> ChunkingConfig:
        expected = {
            "schema_version",
            "maximum_text_tokens",
            "overlapping_text_tokens",
            "maximum_table_rows_per_group",
        }
        if set(data) != expected:
            raise ValueError("chunking configuration fields are incomplete or unknown")
        if data["schema_version"] != 1 or isinstance(data["schema_version"], bool):
            raise ValueError("unsupported chunking configuration schema version")
        integer_fields = (
            "maximum_text_tokens",
            "overlapping_text_tokens",
            "maximum_table_rows_per_group",
        )
        if any(
            isinstance(data[name], bool) or not isinstance(data[name], int)
            for name in integer_fields
        ):
            raise ValueError("chunking limits must be integers")
        return cls(
            maximum_text_tokens=data["maximum_text_tokens"],  # type: ignore[arg-type]
            overlapping_text_tokens=data["overlapping_text_tokens"],  # type: ignore[arg-type]
            maximum_table_rows_per_group=data["maximum_table_rows_per_group"],  # type: ignore[arg-type]
        )

    @property
    def config_id(self) -> str:
        canonical = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))
        return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def chunk_section(
    section: ExtractedSection,
    *,
    document_id: UUID,
    extraction_id: UUID,
    config: ChunkingConfig,
    tokenizer: OffsetTokenizer,
    chunking_configuration_id: str | None = None,
) -> tuple[EvidenceUnit, ...]:
    """Split one section by the selected tokenizer while retaining text offsets."""
    effective_configuration_id = chunking_configuration_id or config.config_id
    spans = tuple(tokenizer.token_spans(section.text))
    previous_end = 0
    for span in spans:
        if span.end > len(section.text) or span.start < previous_end:
            raise ValueError("tokenizer returned invalid or overlapping source offsets")
        previous_end = span.end
    if not spans:
        return ()

    units: list[EvidenceUnit] = []
    start_token = 0
    step = config.maximum_text_tokens - config.overlapping_text_tokens
    while start_token < len(spans):
        end_token = min(start_token + config.maximum_text_tokens, len(spans))
        start_offset = spans[start_token].start
        end_offset = spans[end_token - 1].end
        content = section.text[start_offset:end_offset]
        units.append(
            EvidenceUnit.create(
                document_id=document_id,
                extraction_id=extraction_id,
                section_ordinal=section.ordinal,
                ordinal=len(units),
                kind="text",
                content=content,
                start_offset=start_offset,
                end_offset=end_offset,
                source_location=section.source_location,
                identity_context={
                    "chunking_configuration_id": effective_configuration_id,
                },
                metadata={
                    "heading_path": list(section.heading_path),
                    "chunking_configuration_id": effective_configuration_id,
                    "token_start": start_token,
                    "token_end_exclusive": end_token,
                },
            )
        )
        if end_token == len(spans):
            break
        start_token += step
    return tuple(units)


def chunk_table_rows(
    table: ExtractedTable,
    *,
    document_id: UUID,
    extraction_id: UUID,
    config: ChunkingConfig,
    tokenizer: OffsetTokenizer | None = None,
    chunking_configuration_id: str | None = None,
) -> tuple[EvidenceUnit, ...]:
    """Render bounded row groups, splitting oversized rows into labeled cells.

    Normal groups retain their original row layout. If one row is too long, the
    fallback creates bounded cell chunks with the applicable row/column headers
    repeated, so text stays searchable without truncating or detaching values.
    """
    effective_configuration_id = chunking_configuration_id or config.config_id
    if table.row_count <= table.header_rows:
        return ()
    header_lines = [
        " | ".join(table.cell_text(row, column) for column in range(table.column_count))
        for row in range(table.header_rows)
    ]

    def render_rows(start: int, end: int) -> str:
        lines: list[str] = []
        if table.caption:
            lines.append(f"Caption: {table.caption}")
        if table.units:
            lines.append(f"Units: {table.units}")
        lines.extend(header_lines)
        for row in range(start, end):
            lines.append(
                " | ".join(
                    table.cell_text(row, column) for column in range(table.column_count)
                )
            )
        if table.footnotes:
            lines.append("Footnotes: " + " | ".join(table.footnotes))
        return "\n".join(lines)

    units: list[EvidenceUnit] = []
    first_data_row = table.header_rows
    while first_data_row < table.row_count:
        end_data_row = min(
            first_data_row + config.maximum_table_rows_per_group, table.row_count
        )
        if tokenizer is not None:
            while end_data_row > first_data_row:
                content = render_rows(first_data_row, end_data_row)
                if (
                    len(tokenizer.token_spans("passage: " + content))
                    <= config.maximum_text_tokens
                ):
                    break
                end_data_row -= 1
            if end_data_row == first_data_row:
                units.extend(
                    _chunk_oversized_table_row(
                        table,
                        row=first_data_row,
                        document_id=document_id,
                        extraction_id=extraction_id,
                        config=config,
                        tokenizer=tokenizer,
                        ordinal_start=len(units),
                        chunking_configuration_id=effective_configuration_id,
                    )
                )
                first_data_row += 1
                continue
        content = render_rows(first_data_row, end_data_row)
        units.append(
            EvidenceUnit.create(
                document_id=document_id,
                extraction_id=extraction_id,
                section_ordinal=table.section_ordinal,
                ordinal=len(units),
                kind="table_row_group",
                content=content,
                start_offset=None,
                end_offset=None,
                source_location=table.source_location,
                identity_context={
                    "table_ordinal": table.ordinal,
                    "chunking_configuration_id": effective_configuration_id,
                },
                metadata={
                    "table_ordinal": table.ordinal,
                    "row_start_inclusive": first_data_row,
                    "row_end_exclusive": end_data_row,
                    "header_rows_repeated": table.header_rows,
                    "caption": table.caption,
                    "units": table.units,
                    "footnotes": list(table.footnotes),
                    "chunking_configuration_id": effective_configuration_id,
                },
            )
        )
        first_data_row = end_data_row
    return tuple(units)


def _chunk_oversized_table_row(
    table: ExtractedTable,
    *,
    row: int,
    document_id: UUID,
    extraction_id: UUID,
    config: ChunkingConfig,
    tokenizer: OffsetTokenizer,
    ordinal_start: int,
    chunking_configuration_id: str,
) -> tuple[EvidenceUnit, ...]:
    cells_by_coordinate = {(cell.row, cell.column): cell for cell in table.cells}
    units: list[EvidenceUnit] = []

    for cell in sorted(
        (cell for cell in table.cells if cell.row == row and cell.text.strip()),
        key=lambda value: value.column,
    ):
        column_header_refs = cell.column_header_cells or tuple(
            (header_row, cell.column)
            for header_row in range(table.header_rows)
            if table.cell_text(header_row, cell.column).strip()
        )
        column_headers = tuple(
            dict.fromkeys(
                cells_by_coordinate[coordinate].text.strip()
                for coordinate in column_header_refs
                if cells_by_coordinate[coordinate].text.strip()
            )
        )
        row_header_refs = cell.row_header_cells
        if not row_header_refs and cell.column > 0:
            row_header_refs = ((row, 0),)
        row_headers = tuple(
            dict.fromkeys(
                cells_by_coordinate[coordinate].text.strip()
                for coordinate in row_header_refs
                if cells_by_coordinate[coordinate].text.strip()
            )
        )

        context_lines: list[str] = []
        if table.caption:
            context_lines.append(f"Caption: {table.caption}")
        if table.units:
            context_lines.append(f"Units: {table.units}")
        if column_headers:
            context_lines.append("Column headers: " + " > ".join(column_headers))
        if row_headers:
            context_lines.append("Row headers: " + " > ".join(row_headers))
        context_lines.append(f"Table row: {row + 1}; column: {cell.column + 1}")
        context = "\n".join(context_lines)

        spans = tuple(tokenizer.token_spans(cell.text))
        previous_end = 0
        for span in spans:
            if span.start < previous_end or span.end > len(cell.text):
                raise ValueError(
                    "tokenizer returned invalid or overlapping cell offsets"
                )
            previous_end = span.end
        if not spans:
            continue

        start_token = 0
        segment_index = 0
        while start_token < len(spans):
            end_token = min(start_token + config.maximum_text_tokens, len(spans))
            content = ""
            while end_token > start_token:
                value = cell.text[spans[start_token].start : spans[end_token - 1].end]
                content = context + "\nCell value: " + value
                if (
                    len(tokenizer.token_spans("passage: " + content))
                    <= config.maximum_text_tokens
                ):
                    break
                end_token -= 1
            if end_token == start_token:
                raise EvidenceChunkingError(
                    "table cell header context exceeds the configured searchable token limit"
                )

            units.append(
                EvidenceUnit.create(
                    document_id=document_id,
                    extraction_id=extraction_id,
                    section_ordinal=table.section_ordinal,
                    ordinal=ordinal_start + len(units),
                    kind="table_row_group",
                    content=content,
                    start_offset=None,
                    end_offset=None,
                    source_location=table.source_location,
                    identity_context={
                        "table_ordinal": table.ordinal,
                        "cell_row": row,
                        "cell_column": cell.column,
                        "segment_index": segment_index,
                        "chunking_configuration_id": chunking_configuration_id,
                    },
                    metadata={
                        "table_ordinal": table.ordinal,
                        "row_start_inclusive": row,
                        "row_end_exclusive": row + 1,
                        "header_rows_repeated": table.header_rows,
                        "cell_row": row,
                        "cell_column": cell.column,
                        "cell_token_start": start_token,
                        "cell_token_end_exclusive": end_token,
                        "segment_index": segment_index,
                        "oversized_row_segmented": True,
                        "caption": table.caption,
                        "units": table.units,
                        "footnotes": list(table.footnotes),
                        "chunking_configuration_id": chunking_configuration_id,
                    },
                )
            )
            segment_index += 1
            if end_token == len(spans):
                break
            start_token = max(
                start_token + 1,
                end_token - config.overlapping_text_tokens,
            )

    return tuple(units)
