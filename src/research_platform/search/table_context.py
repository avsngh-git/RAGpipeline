"""Attach structured, source-resolvable table context to evidence hits."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import Literal
from uuid import UUID

from research_platform.ingestion.evidence import (
    EvidenceUnit,
    ExtractedTable,
    TableCell,
)
from research_platform.search.contracts import (
    EvidenceHit,
    TableCellEvidence,
    TableEvidenceContext,
    TableRowEvidence,
)


class TableContextResolutionError(ValueError):
    """Table provenance is absent, inconsistent or cannot resolve selected cells."""


def attach_table_context(
    hit: EvidenceHit,
    *,
    source_units_by_id: Mapping[str, EvidenceUnit],
    tables_by_extraction_and_ordinal: Mapping[tuple[UUID, int], ExtractedTable],
) -> EvidenceHit:
    """Return a table hit with exact selected cells and the stored source context.

    The hit's text remains the bounded, already-indexed chunk representation. The
    returned structure describes the table headers and only the rows/cell segments
    referenced by the hit's source evidence IDs. No values are clipped.
    """
    if not isinstance(hit, EvidenceHit):
        raise TypeError("hit must be an EvidenceHit")
    if hit.kind not in {"table", "table_row_group"}:
        return hit
    if hit.table_context is not None:
        raise ValueError("evidence hit already has table context")
    if not isinstance(source_units_by_id, Mapping):
        raise ValueError("source_units_by_id must map IDs to EvidenceUnit values")
    if not isinstance(tables_by_extraction_and_ordinal, Mapping):
        raise ValueError("tables mapping must resolve extraction and table ordinal")

    units: list[EvidenceUnit] = []
    for evidence_id in dict.fromkeys(hit.source_evidence_ids):
        unit = source_units_by_id.get(evidence_id)
        if unit is None:
            raise TableContextResolutionError("source evidence unit is unresolved")
        if not isinstance(unit, EvidenceUnit):
            raise TypeError("source_units_by_id must contain EvidenceUnit values")
        if unit.id != evidence_id:
            raise TableContextResolutionError("source evidence ID does not match unit")
        if (
            unit.document_id != hit.document_id
            or unit.extraction_id != hit.extraction_id
        ):
            raise TableContextResolutionError(
                "source evidence document or extraction does not match the hit"
            )
        if unit.kind not in {"table", "table_row_group"}:
            raise TableContextResolutionError(
                "source evidence unit is not a table unit"
            )
        units.append(unit)

    table_ordinals = {_metadata_int(unit, "table_ordinal") for unit in units}
    if len(table_ordinals) != 1:
        raise TableContextResolutionError("one table hit cannot span multiple tables")
    table_ordinal = next(iter(table_ordinals))
    table = tables_by_extraction_and_ordinal.get((hit.extraction_id, table_ordinal))
    if table is None:
        raise TableContextResolutionError("source table is unresolved")
    if not isinstance(table, ExtractedTable) or table.ordinal != table_ordinal:
        raise TableContextResolutionError("resolved table identity does not match")

    cells_by_coordinate = {(cell.row, cell.column): cell for cell in table.cells}
    expected_header_rows = table.header_rows
    selected_row_indexes: set[int] = set()
    selected_cells: list[TableCellEvidence] = []
    for unit in units:
        repeated_headers = _metadata_int(unit, "header_rows_repeated")
        if repeated_headers != expected_header_rows:
            raise TableContextResolutionError(
                "source unit header rows do not match the extracted table"
            )
        cell_row_value = unit.metadata.get("cell_row")
        cell_column_value = unit.metadata.get("cell_column")
        if cell_row_value is not None or cell_column_value is not None:
            row = _metadata_int(unit, "cell_row")
            column = _metadata_int(unit, "cell_column")
            token_start = _metadata_int(unit, "cell_token_start")
            token_end = _metadata_int(unit, "cell_token_end_exclusive")
            source_cell = cells_by_coordinate.get((row, column))
            if (
                source_cell is None
                or row < expected_header_rows
                or token_start < 0
                or token_end <= token_start
            ):
                raise TableContextResolutionError(
                    "selected cell coordinates or token range are invalid"
                )
            segment = _cell_segment(unit.content)
            if not segment or segment not in source_cell.text:
                raise TableContextResolutionError(
                    "selected cell segment does not resolve within its source cell"
                )
            selected_cells.append(
                _cell_evidence(
                    source_cell,
                    table=table,
                    cells_by_coordinate=cells_by_coordinate,
                    value=segment,
                    value_scope="segment",
                    token_start=token_start,
                    token_end_exclusive=token_end,
                    use_oversized_cell_header_fallback=True,
                )
            )
            continue

        start_row = _metadata_int(unit, "row_start_inclusive")
        end_row = _metadata_int(unit, "row_end_exclusive")
        if (
            start_row < expected_header_rows
            or end_row <= start_row
            or end_row > table.row_count
        ):
            raise TableContextResolutionError("selected table row range is invalid")
        selected_row_indexes.update(range(start_row, end_row))

    if not selected_row_indexes and not selected_cells:
        raise TableContextResolutionError("table hit has no selected body cells")

    if selected_row_indexes:
        header_rows = tuple(
            _row_evidence(row_index, table, cells_by_coordinate, is_header=True)
            for row_index in range(expected_header_rows)
        )
    else:
        needed_header_references = {
            reference
            for cell in selected_cells
            for reference in cell.column_header_references
            if reference[0] < expected_header_rows
        }
        header_rows = tuple(
            _row_evidence(
                row_index,
                table,
                cells_by_coordinate,
                is_header=True,
                selected_coordinates=needed_header_references,
            )
            for row_index in sorted({row for row, _ in needed_header_references})
        )
    selected_rows = tuple(
        _row_evidence(row_index, table, cells_by_coordinate)
        for row_index in sorted(selected_row_indexes)
    )
    selected_cells.sort(
        key=lambda cell: (
            cell.row_index,
            cell.column_index,
            cell.token_start if cell.token_start is not None else -1,
            cell.token_end_exclusive if cell.token_end_exclusive is not None else -1,
        )
    )
    context = TableEvidenceContext(
        table_ordinal=table_ordinal,
        header_row_count=table.header_rows,
        caption=table.caption,
        units=table.units,
        footnotes=table.footnotes,
        header_rows=header_rows,
        selected_rows=selected_rows,
        selected_cells=tuple(selected_cells),
        source_evidence_ids=hit.source_evidence_ids,
    )
    return replace(hit, table_context=context)


def _row_evidence(
    row_index: int,
    table: ExtractedTable,
    cells_by_coordinate: Mapping[tuple[int, int], TableCell],
    *,
    is_header: bool = False,
    selected_coordinates: set[tuple[int, int]] | None = None,
) -> TableRowEvidence:
    cells = tuple(
        _cell_evidence(
            cell,
            table=table,
            cells_by_coordinate=cells_by_coordinate,
            value=cell.text,
            value_scope="cell",
            use_column_header_fallback=not is_header,
        )
        for cell in sorted(
            (
                cell
                for cell in table.cells
                if cell.row == row_index
                and (
                    selected_coordinates is None
                    or (cell.row, cell.column) in selected_coordinates
                )
            ),
            key=lambda cell: cell.column,
        )
    )
    return TableRowEvidence(row_index=row_index, cells=cells)


def _cell_evidence(
    cell: TableCell,
    *,
    table: ExtractedTable,
    cells_by_coordinate: Mapping[tuple[int, int], TableCell],
    value: str,
    value_scope: Literal["cell", "segment"],
    token_start: int | None = None,
    token_end_exclusive: int | None = None,
    use_oversized_cell_header_fallback: bool = False,
    use_column_header_fallback: bool = True,
) -> TableCellEvidence:
    column_references = cell.column_header_cells
    if not column_references and use_column_header_fallback:
        column_references = tuple(
            (header_row, cell.column)
            for header_row in range(table.header_rows)
            if table.cell_text(header_row, cell.column).strip()
        )
    row_references = cell.row_header_cells
    if use_oversized_cell_header_fallback and not row_references and cell.column > 0:
        row_references = ((cell.row, 0),)

    row_headers = tuple(
        cells_by_coordinate[reference].text
        for reference in row_references
        if cells_by_coordinate[reference].text.strip()
    )
    column_headers = tuple(
        cells_by_coordinate[reference].text
        for reference in column_references
        if cells_by_coordinate[reference].text.strip()
    )
    return TableCellEvidence(
        row_index=cell.row,
        column_index=cell.column,
        value=value,
        value_scope=value_scope,
        row_header_references=row_references,
        column_header_references=column_references,
        row_headers=row_headers,
        column_headers=column_headers,
        token_start=token_start,
        token_end_exclusive=token_end_exclusive,
        merged_range=cell.merged_range,
    )


def _cell_segment(content: str) -> str:
    marker = chr(10) + "Cell value: "
    _, separator, value = content.partition(marker)
    if not separator:
        raise TableContextResolutionError(
            "selected cell has no source-linked readable value"
        )
    return value


def _metadata_int(unit: EvidenceUnit, name: str) -> int:
    value = unit.metadata.get(name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise TableContextResolutionError(f"source unit has an invalid {name}")
    return value
