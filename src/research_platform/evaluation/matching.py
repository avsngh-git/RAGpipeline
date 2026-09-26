"""Deterministic source-coordinate matching for returned evidence chunks."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TypeAlias
from uuid import UUID

from research_platform.evaluation.source_alignment import (
    CellCoordinate,
    SourceAlignmentDataset,
    TableAnchorAlignment,
    TextAnchorAlignment,
)
from research_platform.ingestion.evidence import EvidenceUnit, ExtractedTable, TableCell
from research_platform.search.contracts import EvidenceHit


class SourceMatchingError(ValueError):
    """Returned evidence cannot be reconciled to its canonical source units."""


@dataclass(frozen=True)
class TextEvidenceRegion:
    """One retrieved unit's character range in an extracted section."""

    evidence_id: str
    document_id: UUID
    extraction_id: UUID
    section_ordinal: int
    start_offset: int
    end_offset: int

    def __post_init__(self) -> None:
        _validate_region_identity(
            self.evidence_id, self.document_id, self.extraction_id
        )
        if (
            isinstance(self.section_ordinal, bool)
            or not isinstance(self.section_ordinal, int)
            or self.section_ordinal < 0
        ):
            raise ValueError("section_ordinal must be a non-negative integer")
        if (
            isinstance(self.start_offset, bool)
            or not isinstance(self.start_offset, int)
            or self.start_offset < 0
            or isinstance(self.end_offset, bool)
            or not isinstance(self.end_offset, int)
            or self.end_offset <= self.start_offset
        ):
            raise ValueError("text source offsets must be an ordered non-empty range")


@dataclass(frozen=True)
class TableCellCoverage:
    """A source cell or token segment represented in one returned unit."""

    cell: CellCoordinate
    start: int
    end: int
    total_units: int

    def __post_init__(self) -> None:
        if not isinstance(self.cell, CellCoordinate):
            raise ValueError("cell must be a CellCoordinate")
        for name, value in (
            ("start", self.start),
            ("end", self.end),
            ("total_units", self.total_units),
        ):
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{name} must be an integer")
        if (
            self.total_units <= 0
            or not 0 <= self.start < self.end <= self.total_units
        ):
            raise ValueError("cell coverage must be a non-empty in-range interval")


@dataclass(frozen=True)
class TableEvidenceRegion:
    """Cells and rendered table context carried by one retrieved unit."""

    evidence_id: str
    document_id: UUID
    extraction_id: UUID
    table_ordinal: int
    cells: tuple[TableCellCoverage, ...]
    context_types: frozenset[str]

    def __post_init__(self) -> None:
        _validate_region_identity(
            self.evidence_id, self.document_id, self.extraction_id
        )
        if (
            isinstance(self.table_ordinal, bool)
            or not isinstance(self.table_ordinal, int)
            or self.table_ordinal < 0
        ):
            raise ValueError("table_ordinal must be a non-negative integer")
        if not isinstance(self.cells, tuple) or any(
            not isinstance(cell, TableCellCoverage) for cell in self.cells
        ):
            raise ValueError("cells must be a tuple of TableCellCoverage values")
        if not isinstance(self.context_types, frozenset) or any(
            context not in {"caption", "units", "footnotes"}
            for context in self.context_types
        ):
            raise ValueError("context_types contains an unsupported table context")


SourceEvidenceRegion: TypeAlias = TextEvidenceRegion | TableEvidenceRegion


@dataclass(frozen=True)
class SourceAnchorMatch:
    """Coverage of one canonical source anchor by returned search evidence."""

    anchor_id: str
    coverage_fraction: float
    fully_supported: bool
    matched_cells: tuple[CellCoordinate, ...] = ()
    span_coverages: tuple[float, ...] = ()
    missing_context: tuple[str, ...] = ()

    @property
    def directly_supported(self) -> bool:
        """Whether it contains direct prose or one target table cell."""
        return self.fully_supported or (
            bool(self.matched_cells) and not self.missing_context
        )


def region_from_evidence_unit(
    unit: EvidenceUnit,
    *,
    table: ExtractedTable | None = None,
    cell_token_counts: Mapping[CellCoordinate, int] | None = None,
) -> SourceEvidenceRegion:
    """Convert persisted source provenance to a matchable canonical region.

    For a long table cell split across token windows, pass the total token count for
    that source cell. Without it, the matcher fails closed instead of calling a
    partial cell a complete result.
    """
    if unit.kind == "text":
        if (
            unit.section_ordinal is None
            or unit.start_offset is None
            or unit.end_offset is None
        ):
            raise SourceMatchingError("text evidence is missing section offsets")
        return TextEvidenceRegion(
            evidence_id=unit.id,
            document_id=unit.document_id,
            extraction_id=unit.extraction_id,
            section_ordinal=unit.section_ordinal,
            start_offset=unit.start_offset,
            end_offset=unit.end_offset,
        )
    if unit.kind not in {"table", "table_row_group"}:
        raise SourceMatchingError(
            f"unsupported evidence kind for source matching: {unit.kind}"
        )
    if table is None:
        raise SourceMatchingError(
            "table evidence requires its canonical ExtractedTable"
        )
    if (
        table.section_ordinal != unit.section_ordinal
        or table.ordinal
        != _metadata_integer(unit.metadata.get("table_ordinal"), "table_ordinal")
    ):
        raise SourceMatchingError("table evidence does not match its canonical table")
    if not unit.document_id or not unit.extraction_id:
        raise SourceMatchingError(
            "table evidence is missing document or extraction identity"
        )

    context_types = _rendered_table_context(unit.metadata, table)
    covered_cells: dict[CellCoordinate, TableCellCoverage] = {}
    cell_row = unit.metadata.get("cell_row")
    cell_column = unit.metadata.get("cell_column")
    if cell_row is not None or cell_column is not None:
        if cell_row is None or cell_column is None:
            raise SourceMatchingError(
                "segmented table evidence has incomplete cell identity"
            )
        coordinate = CellCoordinate(
            _metadata_integer(cell_row, "cell_row"),
            _metadata_integer(cell_column, "cell_column"),
        )
        source_cell = _table_cell(table, coordinate)
        token_start = _metadata_integer(
            unit.metadata.get("cell_token_start"), "cell_token_start"
        )
        token_end = _metadata_integer(
            unit.metadata.get("cell_token_end_exclusive"), "cell_token_end_exclusive"
        )
        total_tokens = (cell_token_counts or {}).get(coordinate)
        if total_tokens is None:
            raise SourceMatchingError(
                f"segmented table cell {coordinate} requires its source token count"
            )
        covered_cells[coordinate] = TableCellCoverage(
            cell=coordinate,
            start=token_start,
            end=token_end,
            total_units=total_tokens,
        )
        for context_cell in _cell_context(source_cell, table):
            covered_cells[context_cell] = TableCellCoverage(
                cell=context_cell, start=0, end=1, total_units=1
            )
    else:
        row_start = _metadata_integer(
            unit.metadata.get("row_start_inclusive"), "row_start_inclusive"
        )
        row_end = _metadata_integer(
            unit.metadata.get("row_end_exclusive"), "row_end_exclusive"
        )
        header_rows = _metadata_integer(
            unit.metadata.get("header_rows_repeated"), "header_rows_repeated"
        )
        if (
            row_start < header_rows
            or row_end <= row_start
            or row_end > table.row_count
            or header_rows != table.header_rows
        ):
            raise SourceMatchingError(
                "table row range or repeated headers are inconsistent"
            )
        for cell in table.cells:
            if row_start <= cell.row < row_end or cell.row < header_rows:
                coordinate = CellCoordinate(cell.row, cell.column)
                covered_cells[coordinate] = TableCellCoverage(
                    cell=coordinate, start=0, end=1, total_units=1
                )
    return TableEvidenceRegion(
        evidence_id=unit.id,
        document_id=unit.document_id,
        extraction_id=unit.extraction_id,
        table_ordinal=table.ordinal,
        cells=tuple(covered_cells[key] for key in sorted(covered_cells)),
        context_types=frozenset(context_types),
    )


def match_evidence_hit(
    hit: EvidenceHit,
    regions_by_evidence_id: Mapping[str, SourceEvidenceRegion],
    alignments: SourceAlignmentDataset,
) -> tuple[SourceAnchorMatch, ...]:
    """Match one hit to canonical spans/cells resolved from its evidence IDs."""
    return match_evidence_hits((hit,), regions_by_evidence_id, alignments)


def match_evidence_hits(
    hits: Sequence[EvidenceHit],
    regions_by_evidence_id: Mapping[str, SourceEvidenceRegion],
    alignments: SourceAlignmentDataset,
) -> tuple[SourceAnchorMatch, ...]:
    """Union source coverage across hits, preserving their distinct lineage.

    This supports evidence split across ranked chunks: callers can evaluate each
    result prefix and credit an anchor when its complete annotated source is present.
    Duplicate source IDs and overlapping coordinates are collapsed.
    """
    resolved_regions: list[SourceEvidenceRegion] = []
    seen_evidence_ids: set[str] = set()
    for hit in hits:
        if not isinstance(hit, EvidenceHit):
            raise SourceMatchingError("hits must contain EvidenceHit values")
        for evidence_id in dict.fromkeys(hit.source_evidence_ids):
            region = regions_by_evidence_id.get(evidence_id)
            if region is None:
                raise SourceMatchingError(
                    f"source evidence ID cannot be resolved: {evidence_id}"
                )
            if region.evidence_id != evidence_id:
                raise SourceMatchingError(
                    "resolved source region has a different evidence ID"
                )
            if (
                region.document_id != hit.document_id
                or region.extraction_id != hit.extraction_id
            ):
                raise SourceMatchingError(
                    "source region does not match hit document lineage"
                )
            if evidence_id not in seen_evidence_ids:
                resolved_regions.append(region)
                seen_evidence_ids.add(evidence_id)

    matches: list[SourceAnchorMatch] = []
    for alignment in alignments.table_alignments:
        table_regions = [
            region
            for region in resolved_regions
            if isinstance(region, TableEvidenceRegion)
            and region.document_id == alignment.document_id
            and region.extraction_id == alignment.extraction_id
            and region.table_ordinal == alignment.table_ordinal
        ]
        if table_regions:
            matches.append(_match_table_anchor(alignment, table_regions))
    for alignment in alignments.text_alignments:
        text_regions = [
            region
            for region in resolved_regions
            if isinstance(region, TextEvidenceRegion)
            and region.document_id == alignment.document_id
            and region.extraction_id == alignment.extraction_id
        ]
        if text_regions:
            matches.append(_match_text_anchor(alignment, text_regions))
    return tuple(matches)


def _match_table_anchor(
    alignment: TableAnchorAlignment,
    regions: list[TableEvidenceRegion],
) -> SourceAnchorMatch:
    intervals: dict[CellCoordinate, list[tuple[int, int, int]]] = {}
    present_context = set[str]()
    for region in regions:
        present_context.update(region.context_types)
        for cell in region.cells:
            intervals.setdefault(cell.cell, []).append(
                (cell.start, cell.end, cell.total_units)
            )
    missing_context = sorted(set(alignment.required_context) - present_context)
    matched_cells: list[CellCoordinate] = []
    for requirement in alignment.cell_requirements:
        required_coordinates = (requirement.cell, *requirement.context_cells)
        if all(
            _cell_coverage(intervals.get(cell, [])) == 1.0
            for cell in required_coordinates
        ):
            matched_cells.append(requirement.cell)
    fraction = len(matched_cells) / len(alignment.cell_requirements)
    return SourceAnchorMatch(
        anchor_id=alignment.anchor_id,
        coverage_fraction=fraction,
        fully_supported=fraction == 1.0 and not missing_context,
        matched_cells=tuple(matched_cells),
        missing_context=tuple(missing_context),
    )


def _match_text_anchor(
    alignment: TextAnchorAlignment,
    regions: list[TextEvidenceRegion],
) -> SourceAnchorMatch:
    span_coverages: list[float] = []
    weighted_covered = 0
    weighted_total = 0
    complete = True
    for span in alignment.spans:
        intervals = [
            (
                max(region.start_offset, span.start_offset),
                min(region.end_offset, span.end_offset),
            )
            for region in regions
            if region.section_ordinal == span.section_ordinal
            and region.start_offset < span.end_offset
            and region.end_offset > span.start_offset
        ]
        covered = _union_length(intervals)
        total = span.end_offset - span.start_offset
        fraction = covered / total
        span_coverages.append(fraction)
        weighted_covered += covered
        weighted_total += total
        if fraction < span.minimum_coverage:
            complete = False
    overall = weighted_covered / weighted_total
    return SourceAnchorMatch(
        anchor_id=alignment.anchor_id,
        coverage_fraction=overall,
        fully_supported=complete,
        span_coverages=tuple(span_coverages),
    )


def _cell_coverage(intervals: list[tuple[int, int, int]]) -> float:
    if not intervals:
        return 0.0
    totals = {total for _, _, total in intervals}
    if len(totals) != 1:
        raise SourceMatchingError("cell segments use incompatible source token counts")
    if any(start == 0 and end == total for start, end, total in intervals):
        return 1.0
    total = next(iter(totals))
    return _union_length([(start, end) for start, end, _ in intervals]) / total


def _union_length(intervals: list[tuple[int, int]]) -> int:
    ordered = sorted((start, end) for start, end in intervals if end > start)
    if not ordered:
        return 0
    total = 0
    current_start, current_end = ordered[0]
    for start, end in ordered[1:]:
        if start > current_end:
            total += current_end - current_start
            current_start, current_end = start, end
        else:
            current_end = max(current_end, end)
    return total + current_end - current_start


def _table_cell(table: ExtractedTable, coordinate: CellCoordinate) -> TableCell:
    cell = next(
        (
            item
            for item in table.cells
            if (item.row, item.column) == (coordinate.row, coordinate.column)
        ),
        None,
    )
    if cell is None:
        raise SourceMatchingError(f"source table has no cell at {coordinate}")
    return cell


def _cell_context(
    cell: TableCell, table: ExtractedTable
) -> tuple[CellCoordinate, ...]:
    row = cell.row
    column = cell.column
    row_headers = cell.row_header_cells
    column_headers = cell.column_header_cells
    cell_coordinates = {(item.row, item.column) for item in table.cells}
    contexts = set(row_headers) | set(column_headers)
    if not row_headers and column > 0 and (row, 0) in cell_coordinates:
        contexts.add((row, 0))
    if not column_headers:
        contexts.update(
            (header_row, column)
            for header_row in range(table.header_rows)
            if (header_row, column) in cell_coordinates
        )
    return tuple(CellCoordinate(r, c) for r, c in sorted(contexts))


def _rendered_table_context(
    metadata: Mapping[str, object], table: ExtractedTable
) -> set[str]:
    contexts: set[str] = set()
    if table.caption and metadata.get("caption") == table.caption:
        contexts.add("caption")
    if table.units and metadata.get("units") == table.units:
        contexts.add("units")
    footnotes = metadata.get("footnotes")
    if (
        table.footnotes
        and isinstance(footnotes, list)
        and tuple(footnotes) == table.footnotes
    ):
        contexts.add("footnotes")
    return contexts


def _metadata_integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise SourceMatchingError(
            f"source metadata {name} must be a non-negative integer"
        )
    return value


def _validate_region_identity(
    evidence_id: str, document_id: UUID, extraction_id: UUID
) -> None:
    if not isinstance(evidence_id, str) or not evidence_id.strip():
        raise ValueError("evidence_id must be non-empty")
    if not isinstance(document_id, UUID) or not isinstance(extraction_id, UUID):
        raise ValueError("source region document and extraction IDs must be UUIDs")
