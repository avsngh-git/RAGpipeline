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
class EvidenceSourceSpan:
    """A chunk-local character range mapped to one extracted source section."""

    section_ordinal: int
    start_offset: int
    end_offset: int
    chunk_start_offset: int
    chunk_end_offset: int
    heading_path: tuple[str, ...]
    source_location: SourceLocation = SourceLocation()

    def __post_init__(self) -> None:
        for name in (
            "section_ordinal",
            "start_offset",
            "end_offset",
            "chunk_start_offset",
            "chunk_end_offset",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if self.end_offset <= self.start_offset:
            raise ValueError("source span must be a non-empty half-open range")
        if self.chunk_end_offset <= self.chunk_start_offset:
            raise ValueError("chunk span must be a non-empty half-open range")
        if not isinstance(self.heading_path, tuple) or any(
            not isinstance(title, str) or not title.strip()
            for title in self.heading_path
        ):
            raise ValueError("heading_path must contain non-empty strings")
        if not isinstance(self.source_location, SourceLocation):
            raise ValueError("source_location must be a SourceLocation")

    def to_dict(self) -> dict[str, object]:
        return {
            "section_ordinal": self.section_ordinal,
            "start_offset": self.start_offset,
            "end_offset": self.end_offset,
            "chunk_start_offset": self.chunk_start_offset,
            "chunk_end_offset": self.chunk_end_offset,
            "heading_path": list(self.heading_path),
            "source_location": self.source_location.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> EvidenceSourceSpan:
        expected = {
            "section_ordinal",
            "start_offset",
            "end_offset",
            "chunk_start_offset",
            "chunk_end_offset",
            "heading_path",
            "source_location",
        }
        if set(value) != expected:
            raise ValueError("source span metadata fields are invalid")
        return cls(
            section_ordinal=_metadata_nonnegative_int(value["section_ordinal"]),
            start_offset=_metadata_nonnegative_int(value["start_offset"]),
            end_offset=_metadata_nonnegative_int(value["end_offset"]),
            chunk_start_offset=_metadata_nonnegative_int(value["chunk_start_offset"]),
            chunk_end_offset=_metadata_nonnegative_int(value["chunk_end_offset"]),
            heading_path=_validated_heading_path(value["heading_path"]),
            source_location=_source_location_from_mapping(value["source_location"]),
        )


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
    strategy: Literal["section-aware", "fixed-window"] = "section-aware"

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
        if not isinstance(self.strategy, str) or self.strategy not in {
            "section-aware",
            "fixed-window",
        }:
            raise ValueError("unsupported prose chunking strategy")

    def to_dict(self) -> dict[str, int | str]:
        if self.strategy == "section-aware":
            # Preserve existing section-aware configuration IDs exactly.
            return {
                "schema_version": 1,
                "maximum_text_tokens": self.maximum_text_tokens,
                "overlapping_text_tokens": self.overlapping_text_tokens,
                "maximum_table_rows_per_group": self.maximum_table_rows_per_group,
            }
        return {
            "schema_version": 2,
            "strategy": self.strategy,
            "maximum_text_tokens": self.maximum_text_tokens,
            "overlapping_text_tokens": self.overlapping_text_tokens,
            "maximum_table_rows_per_group": self.maximum_table_rows_per_group,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> ChunkingConfig:
        legacy_fields = {
            "schema_version",
            "maximum_text_tokens",
            "overlapping_text_tokens",
            "maximum_table_rows_per_group",
        }
        version = data.get("schema_version")
        if (
            version == 1
            and not isinstance(version, bool)
            and set(data) == legacy_fields
        ):
            strategy: Literal["section-aware", "fixed-window"] = "section-aware"
        elif (
            version == 2
            and not isinstance(version, bool)
            and set(data) == legacy_fields | {"strategy"}
            and data.get("strategy") == "fixed-window"
        ):
            strategy = "fixed-window"
        else:
            raise ValueError(
                "chunking configuration fields are unknown or version is unsupported"
            )
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
            strategy=strategy,
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


def chunk_sections_fixed_window(
    sections: Sequence[ExtractedSection],
    *,
    document_id: UUID,
    extraction_id: UUID,
    config: ChunkingConfig,
    tokenizer: OffsetTokenizer,
    chunking_configuration_id: str | None = None,
) -> tuple[EvidenceUnit, ...]:
    """Chunk normalized prose in ordinal reading order, crossing section joins.

    Two newlines separate extracted sections in the flattened text. They are
    reading-order separators and have no source mapping. Every intersected source
    range is recorded; multi-section chunks have no fabricated single location.
    """
    if config.strategy != "fixed-window":
        raise ValueError("fixed-window chunking requires the fixed-window strategy")
    if any(not isinstance(section, ExtractedSection) for section in sections):
        raise TypeError("sections must contain ExtractedSection values")
    ordered = tuple(sorted(sections, key=lambda section: section.ordinal))
    if len({section.ordinal for section in ordered}) != len(ordered):
        raise ValueError("section ordinals must be unique")

    pieces: list[str] = []
    section_ranges: list[tuple[ExtractedSection, int, int]] = []
    cursor = 0
    for section in ordered:
        if not section.text:
            continue
        if pieces:
            pieces.append("\n\n")
            cursor += 2
        start = cursor
        pieces.append(section.text)
        cursor += len(section.text)
        section_ranges.append((section, start, cursor))
    flattened = "".join(pieces)
    token_spans = tuple(tokenizer.token_spans(flattened))
    _validate_token_spans(token_spans, len(flattened))
    if not token_spans:
        return ()

    effective_configuration_id = chunking_configuration_id or config.config_id
    units: list[EvidenceUnit] = []
    step = config.maximum_text_tokens - config.overlapping_text_tokens
    token_start = 0
    while token_start < len(token_spans):
        token_end = min(token_start + config.maximum_text_tokens, len(token_spans))
        flat_start = token_spans[token_start].start
        flat_end = token_spans[token_end - 1].end
        content = flattened[flat_start:flat_end]
        source_spans: list[EvidenceSourceSpan] = []
        for section, section_start, section_end in section_ranges:
            mapped_start = max(flat_start, section_start)
            mapped_end = min(flat_end, section_end)
            if mapped_end <= mapped_start:
                continue
            source_spans.append(
                EvidenceSourceSpan(
                    section_ordinal=section.ordinal,
                    start_offset=mapped_start - section_start,
                    end_offset=mapped_end - section_start,
                    chunk_start_offset=mapped_start - flat_start,
                    chunk_end_offset=mapped_end - flat_start,
                    heading_path=section.heading_path,
                    source_location=section.source_location,
                )
            )
        if not source_spans:
            if token_end == len(token_spans):
                break
            token_start += step
            continue

        single_source = source_spans[0] if len(source_spans) == 1 else None
        units.append(
            EvidenceUnit.create(
                document_id=document_id,
                extraction_id=extraction_id,
                section_ordinal=(
                    single_source.section_ordinal if single_source is not None else None
                ),
                ordinal=len(units),
                kind="text",
                content=content,
                start_offset=(single_source.start_offset if single_source else None),
                end_offset=(single_source.end_offset if single_source else None),
                source_location=(
                    single_source.source_location if single_source else SourceLocation()
                ),
                identity_context={
                    "chunking_configuration_id": effective_configuration_id,
                    "chunking_strategy": "fixed-window",
                },
                metadata={
                    "heading_path": (
                        list(source_spans[0].heading_path)
                        if single_source is not None
                        else []
                    ),
                    "heading_paths": [list(span.heading_path) for span in source_spans],
                    "chunking_configuration_id": effective_configuration_id,
                    "chunking_strategy": "fixed-window",
                    "token_start": token_start,
                    "token_end_exclusive": token_end,
                    "source_spans": [span.to_dict() for span in source_spans],
                },
            )
        )
        if token_end == len(token_spans):
            break
        token_start += step
    return tuple(units)


def source_spans_for_evidence_unit(
    unit: EvidenceUnit,
) -> tuple[EvidenceSourceSpan, ...]:
    """Read validated per-section spans, falling back to the legacy single span."""
    raw_spans = unit.metadata.get("source_spans")
    if raw_spans is None:
        if (
            unit.kind != "text"
            or unit.section_ordinal is None
            or unit.start_offset is None
            or unit.end_offset is None
            or unit.end_offset <= unit.start_offset
        ):
            return ()
        raw_heading_path = unit.metadata.get("heading_path", [])
        heading_path = _validated_heading_path(raw_heading_path)
        return (
            EvidenceSourceSpan(
                section_ordinal=unit.section_ordinal,
                start_offset=unit.start_offset,
                end_offset=unit.end_offset,
                chunk_start_offset=0,
                chunk_end_offset=len(unit.content),
                heading_path=heading_path,
                source_location=unit.source_location,
            ),
        )
    if not isinstance(raw_spans, list) or not raw_spans:
        raise ValueError("source_spans metadata must be a non-empty list")
    spans: list[EvidenceSourceSpan] = []
    for raw in raw_spans:
        if not isinstance(raw, Mapping):
            raise ValueError("source span metadata entries must be objects")
        span = EvidenceSourceSpan.from_dict(raw)
        if span.chunk_end_offset > len(unit.content):
            raise ValueError("source span exceeds its evidence chunk text")
        spans.append(span)
    previous_chunk_end = 0
    for span in spans:
        if span.chunk_start_offset < previous_chunk_end:
            raise ValueError("source spans overlap or are out of chunk reading order")
        previous_chunk_end = span.chunk_end_offset
    return tuple(spans)


def _validate_token_spans(spans: Sequence[TokenSpan], text_length: int) -> None:
    previous_end = 0
    for span in spans:
        if span.end > text_length or span.start < previous_end:
            raise ValueError("tokenizer returned invalid or overlapping source offsets")
        previous_end = span.end


def _validated_heading_path(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise ValueError("source span heading_path must be a list")
    if any(not isinstance(title, str) or not title.strip() for title in value):
        raise ValueError("source span heading_path contains an invalid title")
    return tuple(value)


def _metadata_nonnegative_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("source span coordinates must be non-negative integers")
    return value


def _source_location_from_mapping(value: object) -> SourceLocation:
    expected = {
        "page_index_zero_based",
        "printed_page_label",
        "bounding_box",
        "coordinate_system",
    }
    if not isinstance(value, Mapping) or set(value) != expected:
        raise ValueError("source span location is malformed")
    page = value["page_index_zero_based"]
    printed = value["printed_page_label"]
    box = value["bounding_box"]
    coordinates = value["coordinate_system"]
    if page is not None and (isinstance(page, bool) or not isinstance(page, int)):
        raise ValueError("source span page index is invalid")
    if printed is not None and not isinstance(printed, str):
        raise ValueError("source span printed page label is invalid")
    if box is not None and (
        not isinstance(box, list)
        or len(box) != 4
        or any(
            isinstance(part, bool) or not isinstance(part, (int, float)) for part in box
        )
    ):
        raise ValueError("source span bounding box is invalid")
    if coordinates is not None and not isinstance(coordinates, str):
        raise ValueError("source span coordinate system is invalid")
    return SourceLocation(
        page_index_zero_based=page,
        printed_page_label=printed,
        bounding_box=tuple(box) if box is not None else None,
        coordinate_system=coordinates,
    )


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
