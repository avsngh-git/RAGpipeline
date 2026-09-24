"""Tests for the optional, source-linked Docling PDF adapter."""

from types import SimpleNamespace
from uuid import UUID

import pytest

from research_platform.ingestion.pdf_extraction import (
    DoclingPdfConfig,
    DoclingPdfExtractor,
    PdfExtractionError,
    tables_requiring_vision_review,
)

DOCUMENT_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
EXTRACTION_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")


def _cell(
    text: str,
    row: int,
    column: int,
    *,
    row_end: int | None = None,
    column_end: int | None = None,
    column_header: bool = False,
    row_header: bool = False,
) -> SimpleNamespace:
    return SimpleNamespace(
        text=text,
        start_row_offset_idx=row,
        end_row_offset_idx=row_end or row + 1,
        start_col_offset_idx=column,
        end_col_offset_idx=column_end or column + 1,
        column_header=column_header,
        row_header=row_header,
    )


def _located(page_no: int = 3) -> list[SimpleNamespace]:
    return [
        SimpleNamespace(
            page_no=page_no,
            bbox=SimpleNamespace(
                l=100.0,
                t=1800.0,
                r=700.0,
                b=1200.0,
                coord_origin=SimpleNamespace(value="BOTTOMLEFT"),
            ),
        )
    ]


class _FakeTable:
    label = "table"
    prov = _located()

    def __init__(self) -> None:
        top = _cell("Dataset", 0, 0, column_end=2, column_header=True)
        self.data = SimpleNamespace(
            num_rows=3,
            num_cols=3,
            grid=[
                [top, top, _cell("Score", 0, 2, column_header=True)],
                [
                    _cell("Dense", 1, 0, column_header=True),
                    _cell("Hybrid", 1, 1, column_header=True),
                    _cell("NDCG", 1, 2, column_header=True),
                ],
                [
                    _cell("RAG", 2, 0, row_header=True),
                    None,
                    _cell("0.81", 2, 2),
                ],
            ],
        )

    def caption_text(self, _document: object) -> str:
        return "Reviewed result table"

    def footnote_text(self, _document: object) -> str:
        return "Higher is better."


class _FakeDocument:
    pages = {3: SimpleNamespace(size=SimpleNamespace(width=1000.0, height=2000.0))}

    def __init__(self) -> None:
        self.table = _FakeTable()
        self.items = [
            SimpleNamespace(
                label="section_header", text="Results", level=1, prov=_located()
            ),
            SimpleNamespace(
                label="text", text="Dense and hybrid results.", prov=_located()
            ),
            self.table,
            SimpleNamespace(
                label="picture",
                text="",
                prov=_located(),
                caption_text=lambda _document: "Figure caption preserved.",
            ),
            SimpleNamespace(label="formula", text="x = y", prov=_located()),
        ]

    def iterate_items(self, *, with_groups: bool, traverse_pictures: bool):
        assert with_groups is True
        assert traverse_pictures is True
        return ((item, 1) for item in self.items)


def test_docling_output_maps_headings_tables_and_locations() -> None:
    extraction = DoclingPdfExtractor().result_from_document(
        _FakeDocument(),
        document_id=DOCUMENT_ID,
        extraction_id=EXTRACTION_ID,
    )

    assert extraction.status == "completed"
    assert [section.text for section in extraction.sections] == [
        "Results",
        "Dense and hybrid results.",
        "Figure caption preserved.",
        "x = y",
    ]
    assert extraction.sections[1].heading_path == ("Results",)
    assert extraction.sections[3].heading_path == ("Results", "Equation")
    assert extraction.sections[0].source_location.page_index_zero_based == 2
    assert extraction.sections[0].source_location.bounding_box == pytest.approx(
        (0.1, 0.1, 0.7, 0.4)
    )

    table = extraction.tables[0]
    assert table.caption == "Reviewed result table"
    assert table.footnotes == ("Higher is better.",)
    assert table.header_rows == 2
    assert (table.row_count, table.column_count) == (3, 3)
    assert table.cell_text(0, 1) == ""
    assert table.cells[0].merged_range == (0, 0, 0, 1)
    value_cell = next(cell for cell in table.cells if (cell.row, cell.column) == (2, 2))
    assert value_cell.column_header_cells == ((0, 2), (1, 2))
    assert table.section_ordinal == 0
    assert tables_requiring_vision_review(extraction) == (0,)


def test_docling_adapter_removes_nul_from_all_extracted_text_fields() -> None:
    document = _FakeDocument()
    document.items[0].text = "\x00Results\x00"
    document.items[1].text = "Dense\x00 and hybrid results."
    document.table.data.grid[2][0].text = "RAG\x00"
    document.table.caption_text = lambda _document: "Reviewed\x00 result table"
    document.table.footnote_text = lambda _document: "Higher\x00 is better."

    extraction = DoclingPdfExtractor().result_from_document(
        document,
        document_id=DOCUMENT_ID,
        extraction_id=EXTRACTION_ID,
    )

    strings = [section.text for section in extraction.sections]
    strings.extend(
        title for section in extraction.sections for title in section.heading_path
    )
    table = extraction.tables[0]
    strings.extend((table.caption or "", *table.footnotes))
    strings.extend(cell.text for cell in table.cells)
    assert all("\x00" not in text for text in strings)
    assert extraction.sections[0].text == "Results"
    assert extraction.sections[1].text == "Dense and hybrid results."
    assert table.cell_text(2, 0) == "RAG"
    assert table.caption == "Reviewed result table"
    assert table.footnotes == ("Higher is better.",)


def test_docling_adapter_resolves_caption_and_footnote_reference_items() -> None:
    document = _FakeDocument()
    table = document.table
    table.caption_text = None
    table.captions = (
        SimpleNamespace(
            resolve=lambda *, doc: SimpleNamespace(text="Referenced table caption")
        ),
    )
    table.footnote_text = None
    table.footnotes = (
        SimpleNamespace(
            resolve=lambda *, doc: SimpleNamespace(text="Referenced footnote")
        ),
    )

    extraction = DoclingPdfExtractor().result_from_document(
        document,
        document_id=DOCUMENT_ID,
        extraction_id=EXTRACTION_ID,
    )

    assert extraction.tables[0].caption == "Referenced table caption"
    assert extraction.tables[0].footnotes == ("Referenced footnote",)


def test_docling_configuration_is_stable_and_pipeline_specific() -> None:
    standard = DoclingPdfConfig()
    repeated = DoclingPdfConfig()
    vlm = DoclingPdfConfig(pipeline="granite-vlm")

    assert standard.configuration_id == repeated.configuration_id
    assert standard.configuration_id != vlm.configuration_id
    assert standard.to_dict()["remote_services_enabled"] is False
    assert standard.to_dict()["model_revisions"]["layout"] == {
        "repo_id": "docling-project/docling-layout-heron",
        "revision": "8f39ad3c0b4c58e9c2d2c84a38465abf757272d8",
    }
    assert vlm.to_dict()["model_revisions"]["vision_language_model"] == {
        "repo_id": "ibm-granite/granite-docling-258M",
        "revision": "982fe3b40f2fa73c365bdb1bcacf6c81b7184bfe",
        "license": "Apache-2.0",
    }


def test_docling_config_rejects_invalid_runtime_limits() -> None:
    with pytest.raises(ValueError, match="device"):
        DoclingPdfConfig(device="tpu")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="positive integer"):
        DoclingPdfConfig(num_threads=0)


def test_pdf_adapter_errors_do_not_expose_paths_or_parser_text(tmp_path) -> None:
    missing = tmp_path / "contains-sensitive-title.pdf"

    with pytest.raises(PdfExtractionError) as error:
        DoclingPdfExtractor().extract(
            missing,
            document_id=DOCUMENT_ID,
            extraction_id=EXTRACTION_ID,
        )

    assert error.value.category == "source_artifact_missing"
    assert "sensitive-title" not in str(error.value)
