"""Versioned alignment between judged source anchors and canonical coordinates."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast
from uuid import UUID

import tomllib

from research_platform.evaluation.calibration import (
    CalibrationDataset,
    CalibrationSourceAnchor,
    CalibrationSourceDocument,
)

_RECORD_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_TABLE_CONTEXT = {"caption", "units", "footnotes"}
_TEXT_COVERAGE_THRESHOLDS = {0.8, 1.0}


class SourceAlignmentLoadError(ValueError):
    """A source alignment manifest is malformed or mismatches its dataset."""


@dataclass(frozen=True, order=True)
class CellCoordinate:
    """Zero-based source table cell coordinate."""

    row: int
    column: int

    def __post_init__(self) -> None:
        if (
            isinstance(self.row, bool)
            or not isinstance(self.row, int)
            or self.row < 0
            or isinstance(self.column, bool)
            or not isinstance(self.column, int)
            or self.column < 0
        ):
            raise ValueError("cell coordinates must be non-negative integers")


@dataclass(frozen=True)
class TableCellRequirement:
    """A required value cell and its row/column header cells."""

    cell: CellCoordinate
    context_cells: tuple[CellCoordinate, ...]


@dataclass(frozen=True)
class TableAnchorAlignment:
    """Source table coordinates needed to support one judged table anchor."""

    anchor_id: str
    document_id: UUID
    extraction_id: UUID
    table_ordinal: int
    cell_requirements: tuple[TableCellRequirement, ...]
    required_context: tuple[Literal["caption", "units", "footnotes"], ...]


@dataclass(frozen=True)
class TextSpanRequirement:
    """One annotated prose span with a required character-coverage fraction."""

    section_ordinal: int
    start_offset: int
    end_offset: int
    minimum_coverage: float

    def __post_init__(self) -> None:
        for name, value in (
            ("section_ordinal", self.section_ordinal),
            ("start_offset", self.start_offset),
            ("end_offset", self.end_offset),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if self.end_offset <= self.start_offset:
            raise ValueError("text span end_offset must exceed start_offset")
        if (
            isinstance(self.minimum_coverage, bool)
            or not isinstance(self.minimum_coverage, (int, float))
            or not math.isfinite(self.minimum_coverage)
            or not 0 < self.minimum_coverage <= 1
        ):
            raise ValueError("minimum_coverage must be finite and in (0, 1]")


@dataclass(frozen=True)
class TextAnchorAlignment:
    """Canonical extraction spans for a prose anchor."""

    anchor_id: str
    document_id: UUID
    extraction_id: UUID
    spans: tuple[TextSpanRequirement, ...]


@dataclass(frozen=True)
class SourceAlignmentDataset:
    """Validated source-coordinate map tied to one calibration and snapshot."""

    schema_version: int
    alignment_id: str
    calibration_dataset_id: str
    snapshot_id: UUID
    policy_id: str
    table_alignments: tuple[TableAnchorAlignment, ...]
    text_alignments: tuple[TextAnchorAlignment, ...]

    @property
    def by_anchor_id(self) -> dict[str, TableAnchorAlignment | TextAnchorAlignment]:
        """Return a fresh anchor-to-alignment lookup."""
        alignments: tuple[TableAnchorAlignment | TextAnchorAlignment, ...] = (
            *self.table_alignments,
            *self.text_alignments,
        )
        return {alignment.anchor_id: alignment for alignment in alignments}


def load_source_alignment(
    path: str | Path, calibration: CalibrationDataset
) -> SourceAlignmentDataset:
    """Load a source alignment manifest and verify its calibration references."""
    source_path = Path(path)
    try:
        contents = source_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SourceAlignmentLoadError(
            f"cannot read source alignment file {source_path}"
        ) from exc
    try:
        return parse_source_alignment(contents, calibration)
    except SourceAlignmentLoadError as exc:
        raise SourceAlignmentLoadError(f"{source_path}: {exc}") from exc


def parse_source_alignment(
    contents: str, calibration: CalibrationDataset
) -> SourceAlignmentDataset:
    """Parse and cross-check versioned prose/table source geometry."""
    try:
        raw = tomllib.loads(contents)
    except tomllib.TOMLDecodeError as exc:
        raise SourceAlignmentLoadError(f"invalid TOML: {exc}") from exc
    record = _mapping(
        raw,
        "source_alignment",
        required={
            "schema_version",
            "alignment_id",
            "calibration_dataset_id",
            "snapshot_id",
            "policy_id",
            "table_alignments",
            "text_alignments",
        },
    )
    if _integer(record["schema_version"], "schema_version", minimum=1) != 1:
        raise SourceAlignmentLoadError("schema_version must be 1")
    alignment_id = _record_id(record["alignment_id"], "alignment_id")
    calibration_id = _record_id(
        record["calibration_dataset_id"], "calibration_dataset_id"
    )
    if calibration_id != calibration.dataset_id:
        raise SourceAlignmentLoadError(
            "calibration_dataset_id does not match the loaded calibration"
        )
    snapshot_id = _uuid(record["snapshot_id"], "snapshot_id")
    if snapshot_id != calibration.snapshot_id:
        raise SourceAlignmentLoadError("snapshot_id does not match the calibration")
    policy_id = _record_id(record["policy_id"], "policy_id")
    if policy_id != "source-match-policy-v1":
        raise SourceAlignmentLoadError("policy_id must be source-match-policy-v1")

    anchors: dict[str, CalibrationSourceAnchor] = {
        anchor.id: anchor for anchor in calibration.source_anchors
    }
    documents: dict[UUID, CalibrationSourceDocument] = {
        document.document_id: document for document in calibration.source_documents
    }
    table_alignments = tuple(
        _parse_table_alignment(item, index, anchors, documents)
        for index, item in enumerate(
            _records(record["table_alignments"], "table_alignments")
        )
    )
    text_alignments = tuple(
        _parse_text_alignment(item, index, anchors, documents)
        for index, item in enumerate(
            _records(record["text_alignments"], "text_alignments")
        )
    )
    all_alignments: tuple[TableAnchorAlignment | TextAnchorAlignment, ...] = (
        *table_alignments,
        *text_alignments,
    )
    _unique(
        tuple(alignment.anchor_id for alignment in all_alignments), "aligned anchor ID"
    )
    aligned_anchor_ids = {alignment.anchor_id for alignment in all_alignments}
    positive_anchor_ids = {
        judgment.source_anchor_id
        for family in calibration.families
        for judgment in family.evidence_judgments
        if judgment.label == 2
    }
    missing_positive_alignments = sorted(positive_anchor_ids - aligned_anchor_ids)
    if missing_positive_alignments:
        raise SourceAlignmentLoadError(
            "label-2 source anchors have no coordinate alignment: "
            + ", ".join(missing_positive_alignments)
        )
    return SourceAlignmentDataset(
        schema_version=1,
        alignment_id=alignment_id,
        calibration_dataset_id=calibration_id,
        snapshot_id=snapshot_id,
        policy_id=policy_id,
        table_alignments=table_alignments,
        text_alignments=text_alignments,
    )


def _parse_table_alignment(
    raw: object,
    index: int,
    anchors: dict[str, CalibrationSourceAnchor],
    documents: dict[UUID, CalibrationSourceDocument],
) -> TableAnchorAlignment:
    path = f"table_alignments[{index}]"
    record = _mapping(
        raw,
        path,
        required={
            "anchor_id",
            "document_id",
            "extraction_id",
            "table_ordinal",
            "required_context",
            "cell_requirements",
        },
    )
    anchor_id = _record_id(record["anchor_id"], f"{path}.anchor_id")
    anchor = anchors.get(anchor_id)
    if anchor is None or anchor.region_type != "table":
        raise SourceAlignmentLoadError(
            f"{path}.anchor_id must reference a calibration table anchor"
        )
    document_id, extraction_id = _source_identity(record, path, anchor, documents)
    table_ordinal = _integer(record["table_ordinal"], f"{path}.table_ordinal")
    raw_context = _string_array(record["required_context"], f"{path}.required_context")
    if len(set(raw_context)) != len(raw_context) or any(
        value not in _TABLE_CONTEXT for value in raw_context
    ):
        raise SourceAlignmentLoadError(
            f"{path}.required_context contains duplicate or unknown context types"
        )
    raw_requirements = _records(
        record["cell_requirements"], f"{path}.cell_requirements"
    )
    requirements: list[TableCellRequirement] = []
    for cell_index, raw_requirement in enumerate(raw_requirements):
        cell_path = f"{path}.cell_requirements[{cell_index}]"
        requirement = _mapping(
            raw_requirement,
            cell_path,
            required={"cell", "context_cells"},
        )
        cell = _coordinate(requirement["cell"], f"{cell_path}.cell")
        context_cells = tuple(
            _coordinate(value, f"{cell_path}.context_cells[{context_index}]")
            for context_index, value in enumerate(
                _arrays(requirement["context_cells"], f"{cell_path}.context_cells")
            )
        )
        _unique(context_cells, f"context cell in {anchor_id}:{cell}")
        if cell in context_cells:
            raise SourceAlignmentLoadError(
                f"{cell_path}.context_cells must not contain the target cell"
            )
        requirements.append(
            TableCellRequirement(cell=cell, context_cells=context_cells)
        )
    if not requirements:
        raise SourceAlignmentLoadError(f"{path}.cell_requirements must not be empty")
    _unique(
        tuple(requirement.cell for requirement in requirements),
        f"target cell in {anchor_id}",
    )
    return TableAnchorAlignment(
        anchor_id=anchor_id,
        document_id=document_id,
        extraction_id=extraction_id,
        table_ordinal=table_ordinal,
        cell_requirements=tuple(requirements),
        required_context=cast(
            tuple[Literal["caption", "units", "footnotes"], ...], raw_context
        ),
    )


def _parse_text_alignment(
    raw: object,
    index: int,
    anchors: dict[str, CalibrationSourceAnchor],
    documents: dict[UUID, CalibrationSourceDocument],
) -> TextAnchorAlignment:
    path = f"text_alignments[{index}]"
    record = _mapping(
        raw,
        path,
        required={"anchor_id", "document_id", "extraction_id", "spans"},
    )
    anchor_id = _record_id(record["anchor_id"], f"{path}.anchor_id")
    anchor = anchors.get(anchor_id)
    if anchor is None or anchor.region_type != "prose":
        raise SourceAlignmentLoadError(
            f"{path}.anchor_id must reference a calibration prose anchor"
        )
    document_id, extraction_id = _source_identity(record, path, anchor, documents)
    spans: list[TextSpanRequirement] = []
    for span_index, raw_span in enumerate(_records(record["spans"], f"{path}.spans")):
        span_path = f"{path}.spans[{span_index}]"
        span = _mapping(
            raw_span,
            span_path,
            required={
                "section_ordinal",
                "start_offset",
                "end_offset",
                "minimum_coverage",
            },
        )
        raw_minimum = span["minimum_coverage"]
        if isinstance(raw_minimum, bool) or not isinstance(raw_minimum, (int, float)):
            raise SourceAlignmentLoadError(
                f"{span_path}.minimum_coverage must be numeric"
            )
        if float(raw_minimum) not in _TEXT_COVERAGE_THRESHOLDS:
            raise SourceAlignmentLoadError(
                f"{span_path}.minimum_coverage must be 0.8 or 1.0 under policy v1"
            )
        try:
            spans.append(
                TextSpanRequirement(
                    section_ordinal=_integer(
                        span["section_ordinal"], f"{span_path}.section_ordinal"
                    ),
                    start_offset=_integer(
                        span["start_offset"], f"{span_path}.start_offset"
                    ),
                    end_offset=_integer(span["end_offset"], f"{span_path}.end_offset"),
                    minimum_coverage=float(raw_minimum),
                )
            )
        except ValueError as exc:
            raise SourceAlignmentLoadError(f"{span_path}: {exc}") from exc
    if not spans:
        raise SourceAlignmentLoadError(f"{path}.spans must not be empty")
    return TextAnchorAlignment(
        anchor_id=anchor_id,
        document_id=document_id,
        extraction_id=extraction_id,
        spans=tuple(spans),
    )


def _source_identity(
    record: dict[str, object],
    path: str,
    anchor: CalibrationSourceAnchor,
    documents: dict[UUID, CalibrationSourceDocument],
) -> tuple[UUID, UUID]:
    document_id = _uuid(record["document_id"], f"{path}.document_id")
    extraction_id = _uuid(record["extraction_id"], f"{path}.extraction_id")
    if document_id != anchor.document_id:
        raise SourceAlignmentLoadError(f"{path}.document_id does not match its anchor")
    document = documents.get(document_id)
    if document is None or extraction_id != document.extraction_id:
        raise SourceAlignmentLoadError(
            f"{path}.extraction_id does not match the anchor's accepted extraction"
        )
    return document_id, extraction_id


def _mapping(
    raw: object,
    path: str,
    *,
    required: set[str],
) -> dict[str, object]:
    if not isinstance(raw, dict) or any(not isinstance(key, str) for key in raw):
        raise SourceAlignmentLoadError(f"{path} must be a TOML table")
    missing = sorted(required - raw.keys())
    unknown = sorted(raw.keys() - required)
    if missing:
        raise SourceAlignmentLoadError(
            f"{path} is missing fields: {', '.join(missing)}"
        )
    if unknown:
        raise SourceAlignmentLoadError(
            f"{path} has unknown fields: {', '.join(unknown)}"
        )
    return cast(dict[str, object], raw)


def _records(raw: object, path: str) -> list[dict[str, object]]:
    if not isinstance(raw, list) or any(not isinstance(item, dict) for item in raw):
        raise SourceAlignmentLoadError(f"{path} must be an array of tables")
    return cast(list[dict[str, object]], raw)


def _arrays(raw: object, path: str) -> list[object]:
    if not isinstance(raw, list):
        raise SourceAlignmentLoadError(f"{path} must be an array")
    return raw


def _coordinate(raw: object, path: str) -> CellCoordinate:
    values = _arrays(raw, path)
    if len(values) != 2:
        raise SourceAlignmentLoadError(f"{path} must contain row and column")
    try:
        return CellCoordinate(
            row=_integer(values[0], f"{path}[0]"),
            column=_integer(values[1], f"{path}[1]"),
        )
    except ValueError as exc:
        raise SourceAlignmentLoadError(f"{path}: {exc}") from exc


def _integer(raw: object, path: str, *, minimum: int = 0) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < minimum:
        raise SourceAlignmentLoadError(
            f"{path} must be an integer greater than or equal to {minimum}"
        )
    return raw


def _string(raw: object, path: str) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise SourceAlignmentLoadError(f"{path} must be a non-empty string")
    return raw


def _record_id(raw: object, path: str) -> str:
    value = _string(raw, path)
    if not _RECORD_ID.fullmatch(value):
        raise SourceAlignmentLoadError(f"{path} must be a lowercase hyphenated ID")
    return value


def _string_array(raw: object, path: str) -> tuple[str, ...]:
    values = _arrays(raw, path)
    return tuple(
        _string(value, f"{path}[{index}]") for index, value in enumerate(values)
    )


def _uuid(raw: object, path: str) -> UUID:
    if not isinstance(raw, str):
        raise SourceAlignmentLoadError(f"{path} must be a UUID string")
    try:
        return UUID(raw)
    except ValueError as exc:
        raise SourceAlignmentLoadError(f"{path} must be a UUID string") from exc


def _unique(values: object, description: str) -> None:
    if not isinstance(values, (tuple, list)):
        raise SourceAlignmentLoadError("internal validation error: expected a sequence")
    seen: set[object] = set()
    for value in values:
        if value in seen:
            raise SourceAlignmentLoadError(f"duplicate {description}: {value}")
        seen.add(value)
