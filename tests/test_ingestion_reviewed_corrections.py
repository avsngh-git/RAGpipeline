"""Tests for immutable, source-linked extraction corrections."""

from uuid import UUID

import pytest

from research_platform.ingestion.evidence import (
    ChunkingConfig,
    ExtractedSection,
    ExtractedTable,
    ExtractionResult,
    SourceLocation,
    TableCell,
    TokenSpan,
)
from research_platform.ingestion.reviewed_corrections import (
    CorrectionError,
    create_reviewed_extraction,
)

DOCUMENT_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
EXTRACTION_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
ARTIFACT_ID = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")
SOURCE_SHA256 = "1" * 64
CORRECTIONS_SHA256 = "2" * 64


class WhitespaceTokenizer:
    def token_spans(self, text: str) -> tuple[TokenSpan, ...]:
        spans: list[TokenSpan] = []
        start: int | None = None
        for index, character in enumerate(text):
            if character.isspace():
                if start is not None:
                    spans.append(TokenSpan(start, index))
                    start = None
            elif start is None:
                start = index
        if start is not None:
            spans.append(TokenSpan(start, len(text)))
        return tuple(spans)


def _table() -> ExtractedTable:
    return ExtractedTable(
        ordinal=4,
        caption="Results",
        units=None,
        footnotes=(),
        header_rows=1,
        cells=(
            TableCell(0, 0, "Method"),
            TableCell(0, 1, "Score"),
            TableCell(1, 0, "Hybrid"),
            TableCell(
                1,
                1,
                "0.7",
                row_header_cells=((1, 0),),
                column_header_cells=((0, 1),),
            ),
        ),
        source_location=SourceLocation(page_index_zero_based=2),
        section_ordinal=0,
    )


def _original() -> ExtractionResult:
    return ExtractionResult(
        document_id=DOCUMENT_ID,
        extraction_id=EXTRACTION_ID,
        extractor_name="docling",
        extractor_revision="test",
        configuration_id="sha256:source-config",
        status="completed",
        source_artifact_id=ARTIFACT_ID,
        sections=(ExtractedSection(0, ("Results",), "Original body text."),),
        tables=(_table(),),
        configuration={"chunking": {"maximum_text_tokens": 20}},
    )


def _correction(**changes: object) -> dict[str, object]:
    correction: dict[str, object] = {
        "original_extraction_id": str(EXTRACTION_ID),
        "source_pdf_sha256": SOURCE_SHA256,
        "source_pages": [3],
        "table_replacements": [],
        "table_patches": [],
        "figure_reclassifications": [],
    }
    correction.update(changes)
    return correction


def _create(correction: dict[str, object]):
    return create_reviewed_extraction(
        _original(),
        correction,
        reviewer="reviewer",
        corrections_sha256=CORRECTIONS_SHA256,
        source_pdf_sha256=SOURCE_SHA256,
        chunking=ChunkingConfig(20, 0, 2),
        tokenizer=WhitespaceTokenizer(),
    )


def test_cell_patch_creates_new_extraction_and_keeps_parent_unchanged() -> None:
    correction = _correction(
        table_patches=[
            {
                "table_ordinal": 4,
                "page_number_1_based": 3,
                "cell_updates": [
                    {
                        "row": 1,
                        "column": 1,
                        "text": "0.9",
                        "expected_text": "0.7",
                    }
                ],
            }
        ]
    )

    reviewed = _create(correction)

    assert reviewed.result.extraction_id != EXTRACTION_ID
    assert reviewed.result.configuration["reviewed_correction"] == {
        "schema_version": 1,
        "source_extraction_id": str(EXTRACTION_ID),
        "source_configuration_id": "sha256:source-config",
        "source_pdf_sha256": SOURCE_SHA256,
        "corrections_sha256": CORRECTIONS_SHA256,
        "reviewer": "reviewer",
        "source_pages": [3],
    }
    assert _original().tables[0].cells[-1].text == "0.7"
    assert reviewed.result.tables[0].cells[-1].text == "0.9"
    assert any("0.9" in unit.content for unit in reviewed.evidence_units)


def test_cell_patch_rejects_stale_expected_text() -> None:
    correction = _correction(
        table_patches=[
            {
                "table_ordinal": 4,
                "page_number_1_based": 3,
                "cell_updates": [
                    {
                        "row": 1,
                        "column": 1,
                        "text": "0.9",
                        "expected_text": "0.8",
                    }
                ],
            }
        ]
    )

    with pytest.raises(CorrectionError, match="expected text"):
        _create(correction)


def test_replacement_preserves_grouped_header_ranges() -> None:
    correction = _correction(
        table_replacements=[
            {
                "table_ordinal": 4,
                "page_number_1_based": 3,
                "caption": "Corrected results",
                "units": None,
                "footnotes": [],
                "header_rows": 1,
                "rows": [
                    ["Method", "Retrieval method", ""],
                    ["Hybrid", "0.88", "0.92"],
                ],
                "merged_cells": [
                    {"row": 0, "column": 1, "row_span": 1, "column_span": 2}
                ],
            }
        ]
    )

    reviewed = _create(correction)

    table = reviewed.result.tables[0]
    assert table.row_count == 2
    assert table.column_count == 3
    assert table.cells[1].merged_range == (0, 1, 0, 2)
    assert table.cells[4].column_header_cells == ((0, 1),)
    assert table.cells[5].column_header_cells == ((0, 1),)


def test_reclassification_removes_table_and_adds_source_located_figure() -> None:
    correction = _correction(
        figure_reclassifications=[
            {
                "table_ordinal": 4,
                "page_number_1_based": 3,
                "caption": "Figure 2. A sample layout.",
                "section_ordinal": 0,
            }
        ]
    )

    reviewed = _create(correction)

    assert reviewed.result.tables == ()
    assert reviewed.reclassified_table_ordinals == (4,)
    figures = [unit for unit in reviewed.evidence_units if unit.kind == "figure"]
    assert len(figures) == 1
    figure = figures[0]
    assert figure.kind == "figure"
    assert figure.section_ordinal == 0
    assert figure.source_location.page_index_zero_based == 2
    assert figure.content == "Figure 2. A sample layout."


def test_correction_rejects_a_different_source_pdf_checksum() -> None:
    correction = _correction(source_pdf_sha256="3" * 64)

    with pytest.raises(CorrectionError, match="checksum does not match"):
        _create(correction)
