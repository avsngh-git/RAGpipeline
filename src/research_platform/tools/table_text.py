"""Model-facing text for table evidence, with every value labeled by its headers."""

from __future__ import annotations

from dataclasses import replace

from research_platform.search.contracts import (
    TableCellEvidence,
    TableEvidenceContext,
    TableRowEvidence,
)


def render_table_rows(context: TableEvidenceContext) -> str | None:
    """Render selected table rows as one labeled line each, or None for cell segments.

    A row becomes ``Row: Method: SparseX; Dataset A — mAP: 31.0, nDCG@10: 52.0``:
    each value carries its column header, and columns that share a group header are
    listed after that group. A row with only a first-column value is a group label
    (``Group: supervised``). Hits that select segments of one oversized cell keep
    their indexed text, which already names the cell's headers.
    """
    if not context.selected_rows:
        return None
    header_text = _HeaderText(context.header_rows)
    lines: list[str] = []
    if context.caption:
        lines.append(f"Caption: {context.caption}")
    if context.units:
        lines.append(f"Units: {context.units}")
    spans = _vertical_spans(context.selected_rows)
    for row in context.selected_rows:
        lines.append(_render_row(row, header_text, context.header_row_count, spans))
    if context.footnotes:
        lines.append("Footnotes: " + " | ".join(context.footnotes))
    return "\n".join(lines)


class _HeaderText(dict[tuple[int, int], str]):
    """Header text by coordinate, with merged header cells spread over their span.

    ``own`` holds the coordinates whose cell carries the text itself.
    """

    def __init__(self, rows: tuple[TableRowEvidence, ...]) -> None:
        super().__init__()
        self.own: set[tuple[int, int]] = set()
        for row in rows:
            for cell in row.cells:
                value = cell.value.strip()
                if not value:
                    continue
                if cell.merged_range is not None:
                    first_row, first_column, last_row, last_column = cell.merged_range
                    for row_index in range(first_row, last_row + 1):
                        for column_index in range(first_column, last_column + 1):
                            self.setdefault((row_index, column_index), value)
                coordinate = (cell.row_index, cell.column_index)
                self[coordinate] = value
                self.own.add(coordinate)


def _header_path(
    cell: TableCellEvidence,
    header_text: _HeaderText,
    header_row_count: int,
) -> list[str]:
    """Header texts for a cell, ordered by the row each header sits in.

    Follows the cell's header references from extraction, which can point away from
    the cell's own column or below the declared header rows; their texts arrive
    resolved in ``column_headers``, in reference order, without empty headers. Header
    rows the references miss are filled with the merged-aware header above the
    column, because references derived at search time do not follow merged cells.
    """
    resolved = iter(cell.column_headers)
    by_row: dict[int, list[str]] = {}
    for row_index, column_index in cell.column_header_references:
        if row_index < header_row_count:
            text = header_text.get((row_index, column_index), "")
            if (row_index, column_index) in header_text.own:
                next(resolved, None)
        else:
            text = next(resolved, "").strip()
        if text:
            by_row.setdefault(row_index, []).append(text)
    for row_index in range(header_row_count):
        if row_index not in by_row:
            text = header_text.get((row_index, cell.column_index), "")
            if text:
                by_row[row_index] = [text]
    parts = [text for row_index in sorted(by_row) for text in by_row[row_index]]
    return list(dict.fromkeys(parts))


def _vertical_spans(rows: tuple[TableRowEvidence, ...]) -> dict[tuple[int, int], str]:
    """Values of merged body cells for the selected rows below their first row.

    A merged label whose first row precedes the selected rows is not part of the
    evidence hit and stays absent.
    """
    spans: dict[tuple[int, int], str] = {}
    selected = {row.row_index for row in rows}
    for row in rows:
        for cell in row.cells:
            value = cell.value.strip()
            if not value or cell.merged_range is None:
                continue
            first_row, first_column, last_row, last_column = cell.merged_range
            for row_index in range(first_row + 1, last_row + 1):
                if row_index in selected:
                    for column_index in range(first_column, last_column + 1):
                        spans.setdefault((row_index, column_index), value)
    return spans


def _render_row(
    row: TableRowEvidence,
    header_text: _HeaderText,
    header_row_count: int,
    spans: dict[tuple[int, int], str],
) -> str:
    values = {cell.column_index: cell.value.strip() for cell in row.cells}
    for (row_index, column_index), value in spans.items():
        if row_index == row.row_index and not values.get(column_index):
            values[column_index] = value
    cells = sorted(
        (
            replace(cell, value=values[cell.column_index])
            for cell in row.cells
            if values.get(cell.column_index)
        ),
        key=lambda cell: cell.column_index,
    )
    multi_column = any(column > 0 for _, column in header_text)
    if multi_column and len(cells) == 1 and cells[0].column_index == 0:
        return f"Group: {cells[0].value.strip()}"
    groups: list[tuple[str, list[str]]] = []
    for cell in cells:
        path = _header_path(cell, header_text, header_row_count)
        prefix = " > ".join(path[:-1])
        leaf = path[-1] if path else f"column {cell.column_index + 1}"
        item = f"{leaf}: {cell.value.strip()}"
        if groups and groups[-1][0] == prefix:
            groups[-1][1].append(item)
        else:
            groups.append((prefix, [item]))
    rendered = "; ".join(
        f"{prefix} — {', '.join(items)}" if prefix else ", ".join(items)
        for prefix, items in groups
    )
    return f"Row: {rendered}"
