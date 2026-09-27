"""Checks structured table context remains linked to selected evidence units."""

import re
from dataclasses import replace
from uuid import UUID

import pytest

from research_platform.api.schemas.search import EvidenceHitModel
from research_platform.ingestion.evidence import (
    ChunkingConfig,
    ExtractedTable,
    SourceLocation,
    TableCell,
    TokenSpan,
    chunk_table_rows,
)
from research_platform.search.contracts import ComponentScores, EvidenceHit
from research_platform.search.table_context import (
    TableContextResolutionError,
    attach_table_context,
)

DOCUMENT_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
EXTRACTION_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
LOCATION = SourceLocation(page_index_zero_based=6, printed_page_label="7")


class WhitespaceTokenizer:
    def token_spans(self, text: str) -> tuple[TokenSpan, ...]:
        return tuple(
            TokenSpan(match.start(), match.end()) for match in re.finditer(r"\S+", text)
        )


def _table() -> ExtractedTable:
    return ExtractedTable(
        ordinal=3,
        caption="Mortality by age",
        units="percent",
        footnotes=("Adjusted for baseline risk.",),
        header_rows=2,
        source_location=LOCATION,
        cells=(
            TableCell(0, 0, "Population"),
            TableCell(0, 1, "Outcome group"),
            TableCell(1, 0, "Age"),
            TableCell(1, 1, "Mortality"),
            TableCell(
                2,
                0,
                "Adults",
                row_header_cells=((2, 0),),
            ),
            TableCell(
                2,
                1,
                "42.1",
                row_header_cells=((2, 0),),
                column_header_cells=((0, 1), (1, 1)),
            ),
        ),
        section_ordinal=4,
    )


def _hit(unit, table: ExtractedTable) -> EvidenceHit:
    return EvidenceHit(
        chunk_id="chunk-table",
        source_evidence_ids=(unit.id,),
        paper_id="W123",
        document_id=DOCUMENT_ID,
        document_version="published-2025",
        document_version_kind="published",
        extraction_id=EXTRACTION_ID,
        chunking_configuration_id=unit.metadata.get("chunking_configuration_id"),
        kind="table_row_group",
        source_location=table.source_location,
        rank=1,
        component_scores=ComponentScores(),
        text=unit.content,
    )


def _chunk(table: ExtractedTable, config: ChunkingConfig):
    return chunk_table_rows(
        table,
        document_id=DOCUMENT_ID,
        extraction_id=EXTRACTION_ID,
        config=config,
        tokenizer=WhitespaceTokenizer(),
    )


def test_row_group_context_keeps_caption_units_footnotes_headers_and_values() -> None:
    table = _table()
    (unit,) = _chunk(table, ChunkingConfig(120, 0, 3))

    enriched = attach_table_context(
        _hit(unit, table),
        source_units_by_id={unit.id: unit},
        tables_by_extraction_and_ordinal={(EXTRACTION_ID, table.ordinal): table},
    )

    assert enriched.text == unit.content
    assert enriched.table_context is not None
    context = enriched.table_context
    assert context.table_ordinal == 3
    assert context.header_row_count == 2
    assert context.caption == "Mortality by age"
    assert context.units == "percent"
    assert context.footnotes == ("Adjusted for baseline risk.",)
    assert [row.row_index for row in context.header_rows] == [0, 1]
    assert [row.row_index for row in context.selected_rows] == [2]
    outcome = context.selected_rows[0].cells[1]
    assert (outcome.row_index, outcome.column_index, outcome.value) == (2, 1, "42.1")
    assert outcome.row_headers == ("Adults",)
    assert outcome.column_headers == ("Outcome group", "Mortality")
    assert outcome.column_header_references == ((0, 1), (1, 1))
    assert context.source_evidence_ids == (unit.id,)


def test_multiple_row_groups_return_only_their_source_rows_in_table_order() -> None:
    table = replace(
        _table(),
        cells=_table().cells
        + (
            TableCell(3, 0, "Seniors", row_header_cells=((3, 0),)),
            TableCell(
                3,
                1,
                "9.9",
                row_header_cells=((3, 0),),
                column_header_cells=((0, 1), (1, 1)),
            ),
        ),
    )
    units = _chunk(table, ChunkingConfig(120, 0, 1))
    hit = replace(
        _hit(units[0], table),
        source_evidence_ids=tuple(unit.id for unit in units),
        text="\n".join(unit.content for unit in units),
    )

    enriched = attach_table_context(
        hit,
        source_units_by_id={unit.id: unit for unit in units},
        tables_by_extraction_and_ordinal={(EXTRACTION_ID, table.ordinal): table},
    )

    assert enriched.table_context is not None
    assert [row.row_index for row in enriched.table_context.selected_rows] == [2, 3]
    assert enriched.table_context.selected_rows[1].cells[1].value == "9.9"


def test_typed_evidence_response_serializes_structured_table_context() -> None:
    table = _table()
    (unit,) = _chunk(table, ChunkingConfig(120, 0, 3))
    enriched = attach_table_context(
        _hit(unit, table),
        source_units_by_id={unit.id: unit},
        tables_by_extraction_and_ordinal={(EXTRACTION_ID, table.ordinal): table},
    )

    response = EvidenceHitModel.from_contract(enriched)

    assert response.table_context is not None
    assert response.table_context.caption == "Mortality by age"
    assert response.table_context.selected_rows[0].cells[1].value == "42.1"
    assert response.table_context.selected_rows[0].cells[1].column_headers == (
        "Outcome group",
        "Mortality",
    )


def test_oversized_cell_context_returns_exact_segment_and_token_coordinates() -> None:
    table = ExtractedTable(
        ordinal=3,
        caption=None,
        units=None,
        footnotes=("Direction is favorable.",),
        header_rows=1,
        source_location=LOCATION,
        cells=(
            TableCell(0, 0, "Group"),
            TableCell(0, 1, "Value"),
            TableCell(1, 0, "Adults"),
            TableCell(
                1,
                1,
                "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu nu xi omicron pi rho sigma tau upsilon phi chi psi omega alpha beta gamma delta epsilon zeta eta theta",
                row_header_cells=((1, 0),),
                column_header_cells=((0, 1),),
            ),
        ),
    )
    units = _chunk(table, ChunkingConfig(22, 2, 1))
    segmented = tuple(
        unit
        for unit in units
        if "cell_token_start" in unit.metadata and unit.metadata["cell_column"] == 1
    )
    assert segmented

    unit = segmented[0]
    enriched = attach_table_context(
        _hit(unit, table),
        source_units_by_id={unit.id: unit},
        tables_by_extraction_and_ordinal={(EXTRACTION_ID, table.ordinal): table},
    )

    assert enriched.table_context is not None
    assert enriched.table_context.footnotes == ("Direction is favorable.",)
    assert enriched.table_context.header_row_count == 1
    assert [
        cell.column_index for cell in enriched.table_context.header_rows[0].cells
    ] == [1]
    (cell,) = enriched.table_context.selected_cells
    assert cell.value_scope == "segment"
    assert cell.value in table.cells[-1].text
    assert cell.row_headers == ("Adults",)
    assert cell.column_headers == ("Value",)
    assert cell.token_start == unit.metadata["cell_token_start"]
    assert cell.token_end_exclusive == unit.metadata["cell_token_end_exclusive"]
    assert enriched.text == unit.content


def test_non_table_hit_is_returned_unchanged() -> None:
    table = _table()
    (unit,) = _chunk(table, ChunkingConfig(120, 0, 3))
    hit = EvidenceHit(
        **{
            **_hit(unit, table).__dict__,
            "kind": "text",
        }
    )

    result = attach_table_context(
        hit, source_units_by_id={}, tables_by_extraction_and_ordinal={}
    )

    assert result is hit
    assert result.table_context is None


def test_unresolved_or_inconsistent_table_lineage_fails_closed() -> None:
    table = _table()
    (unit,) = _chunk(table, ChunkingConfig(120, 0, 3))
    hit = _hit(unit, table)

    with pytest.raises(TableContextResolutionError, match="unresolved"):
        attach_table_context(
            hit,
            source_units_by_id={},
            tables_by_extraction_and_ordinal={(EXTRACTION_ID, table.ordinal): table},
        )

    with pytest.raises(TableContextResolutionError, match="source table is unresolved"):
        attach_table_context(
            hit,
            source_units_by_id={unit.id: unit},
            tables_by_extraction_and_ordinal={},
        )


def test_inconsistent_header_count_or_row_range_fails_closed() -> None:
    table = _table()
    (unit,) = _chunk(table, ChunkingConfig(120, 0, 3))
    wrong_header_unit = type(unit)(
        **{
            **unit.__dict__,
            "metadata": {**unit.metadata, "header_rows_repeated": 1},
        }
    )
    hit = _hit(unit, table)

    with pytest.raises(TableContextResolutionError, match="header rows"):
        attach_table_context(
            hit,
            source_units_by_id={unit.id: wrong_header_unit},
            tables_by_extraction_and_ordinal={(EXTRACTION_ID, table.ordinal): table},
        )


def test_table_context_cannot_be_attached_to_non_table_evidence() -> None:
    table = _table()
    (unit,) = _chunk(table, ChunkingConfig(120, 0, 3))
    context_hit = attach_table_context(
        _hit(unit, table),
        source_units_by_id={unit.id: unit},
        tables_by_extraction_and_ordinal={(EXTRACTION_ID, table.ordinal): table},
    )
    with pytest.raises(ValueError, match="only table hits"):
        EvidenceHit(**{**context_hit.__dict__, "kind": "text"})
