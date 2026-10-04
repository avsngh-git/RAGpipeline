"""Table evidence is shown to the model with every value labeled by its headers."""

from __future__ import annotations

import re
from dataclasses import replace
from uuid import UUID

from research_platform.ingestion.evidence import (
    ChunkingConfig,
    ExtractedTable,
    SourceLocation,
    TableCell,
    TokenSpan,
    chunk_table_rows,
)
from research_platform.search.contracts import (
    ComponentScores,
    EvidenceHit,
    TableEvidenceContext,
)
from research_platform.search.table_context import attach_table_context
from research_platform.tools.research_tools import _collected_evidence
from research_platform.tools.table_text import render_table_rows

DOCUMENT_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
EXTRACTION_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")


class _WhitespaceTokenizer:
    def token_spans(self, text: str) -> tuple[TokenSpan, ...]:
        return tuple(
            TokenSpan(match.start(), match.end()) for match in re.finditer(r"\S+", text)
        )


def _results_table() -> ExtractedTable:
    """Two header rows; 'Dataset A' spans two columns; one group row; one merged label."""
    group = (0, 1, 0, 2)
    label = (4, 0, 5, 0)
    return ExtractedTable(
        ordinal=7,
        caption="Results on two datasets.",
        units=None,
        footnotes=(),
        header_rows=2,
        source_location=SourceLocation(page_index_zero_based=3),
        cells=(
            TableCell(0, 0, ""),
            TableCell(0, 1, "Dataset A", merged_range=group),
            TableCell(0, 2, "", merged_range=group),
            TableCell(0, 3, "Dataset B"),
            TableCell(1, 0, "Method"),
            TableCell(1, 1, "mAP"),
            TableCell(1, 2, "nDCG@10"),
            TableCell(1, 3, "mAP"),
            TableCell(2, 0, "unsupervised"),
            TableCell(2, 1, ""),
            TableCell(2, 2, ""),
            TableCell(2, 3, ""),
            TableCell(3, 0, "SparseX"),
            TableCell(3, 1, "31.40"),
            TableCell(3, 2, "52.70"),
            TableCell(3, 3, "29.10"),
            TableCell(4, 0, "DenseY", merged_range=label),
            TableCell(4, 1, "24.60"),
            TableCell(4, 2, "45.20"),
            TableCell(4, 3, "24.30"),
            TableCell(5, 0, "", merged_range=label),
            TableCell(5, 1, "24.10"),
            TableCell(5, 2, "45.00"),
            TableCell(5, 3, ""),
        ),
    )


def _context(table: ExtractedTable) -> TableEvidenceContext:
    units = chunk_table_rows(
        table,
        document_id=DOCUMENT_ID,
        extraction_id=EXTRACTION_ID,
        config=ChunkingConfig(400, 0, 10),
        tokenizer=_WhitespaceTokenizer(),
    )
    hit = _hit(units[0].id, units[0].content)
    enriched = attach_table_context(
        hit,
        source_units_by_id={unit.id: unit for unit in units},
        tables_by_extraction_and_ordinal={(EXTRACTION_ID, table.ordinal): table},
    )
    assert enriched.table_context is not None
    return enriched.table_context


def _hit(unit_id: str, text: str) -> EvidenceHit:
    return EvidenceHit(
        chunk_id="chunk-table",
        source_evidence_ids=(unit_id,),
        paper_id="W123",
        document_id=DOCUMENT_ID,
        document_version="published-2025",
        document_version_kind="published",
        extraction_id=EXTRACTION_ID,
        chunking_configuration_id=None,
        kind="table_row_group",
        source_location=SourceLocation(page_index_zero_based=3),
        rank=1,
        component_scores=ComponentScores(),
        text=text,
    )


def test_rows_carry_group_and_column_headers() -> None:
    rendered = render_table_rows(_context(_results_table()))

    assert rendered == (
        "Caption: Results on two datasets.\n"
        "Group: unsupervised\n"
        "Row: Method: SparseX; Dataset A — mAP: 31.40, nDCG@10: 52.70; "
        "Dataset B — mAP: 29.10\n"
        "Row: Method: DenseY; Dataset A — mAP: 24.60, nDCG@10: 45.20; "
        "Dataset B — mAP: 24.30\n"
        "Row: Method: DenseY; Dataset A — mAP: 24.10, nDCG@10: 45.00"
    )


def test_cell_segment_hits_keep_their_indexed_text() -> None:
    context = _context(_results_table())
    segment_only = TableEvidenceContext(
        table_ordinal=context.table_ordinal,
        header_row_count=context.header_row_count,
        caption=context.caption,
        units=context.units,
        footnotes=context.footnotes,
        header_rows=context.header_rows,
        selected_rows=(),
        selected_cells=(
            replace(
                context.selected_rows[1].cells[1],
                value_scope="segment",
                token_start=0,
                token_end_exclusive=1,
            ),
        ),
        source_evidence_ids=context.source_evidence_ids,
    )

    assert render_table_rows(segment_only) is None


def test_collected_table_evidence_uses_labeled_rows() -> None:
    table = _results_table()
    units = chunk_table_rows(
        table,
        document_id=DOCUMENT_ID,
        extraction_id=EXTRACTION_ID,
        config=ChunkingConfig(400, 0, 10),
        tokenizer=_WhitespaceTokenizer(),
    )
    hit = attach_table_context(
        _hit(units[0].id, units[0].content),
        source_units_by_id={unit.id: unit for unit in units},
        tables_by_extraction_and_ordinal={(EXTRACTION_ID, table.ordinal): table},
    )

    collected = _collected_evidence(hit, title="Paper", year=2024)

    assert collected.text.startswith("Caption: Results on two datasets.\nGroup:")
    assert " | " not in collected.text
