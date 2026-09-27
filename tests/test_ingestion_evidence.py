"""Tests for source locations, evidence identities and chunk boundaries."""

from pathlib import Path
from uuid import UUID

import pytest
import tomllib

from research_platform.evaluation.matching import region_from_evidence_unit
from research_platform.ingestion.evidence import (
    ChunkingConfig,
    ExtractedSection,
    ExtractedTable,
    SourceLocation,
    TableCell,
    TokenSpan,
    chunk_section,
    chunk_sections_fixed_window,
    chunk_table_rows,
    source_spans_for_evidence_unit,
)

DOCUMENT_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
EXTRACTION_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")


class WhitespaceTokenizer:
    def token_spans(self, text: str) -> tuple[TokenSpan, ...]:
        return tuple(TokenSpan(start, end) for start, end in _word_offsets(text))


def _word_offsets(text: str):
    start: int | None = None
    for index, character in enumerate(text):
        if character.isspace():
            if start is not None:
                yield start, index
                start = None
        elif start is None:
            start = index
    if start is not None:
        yield start, len(text)


def test_source_location_keeps_pdf_and_printed_page_numbering_separate() -> None:
    location = SourceLocation(page_index_zero_based=4, printed_page_label="5")

    assert location.to_dict() == {
        "page_index_zero_based": 4,
        "printed_page_label": "5",
        "bounding_box": None,
        "coordinate_system": None,
    }


def test_source_location_rejects_fabricated_or_ambiguous_coordinates() -> None:
    with pytest.raises(ValueError, match="normalized"):
        SourceLocation(bounding_box=(0.8, 0.1, 0.2, 0.9), coordinate_system="page")
    with pytest.raises(ValueError, match="coordinate_system"):
        SourceLocation(bounding_box=(0.1, 0.1, 0.8, 0.9))
    with pytest.raises(ValueError, match="non-negative"):
        SourceLocation(page_index_zero_based=-1)


def test_text_chunks_keep_offsets_and_repeat_identically() -> None:
    section = ExtractedSection(
        ordinal=3,
        heading_path=("4", "Results"),
        text="alpha beta gamma delta epsilon",
        source_location=SourceLocation(page_index_zero_based=2),
    )
    config = ChunkingConfig(
        maximum_text_tokens=3,
        overlapping_text_tokens=1,
        maximum_table_rows_per_group=2,
    )

    chunks = chunk_section(
        section,
        document_id=DOCUMENT_ID,
        extraction_id=EXTRACTION_ID,
        config=config,
        tokenizer=WhitespaceTokenizer(),
    )
    retries = chunk_section(
        section,
        document_id=DOCUMENT_ID,
        extraction_id=EXTRACTION_ID,
        config=config,
        tokenizer=WhitespaceTokenizer(),
    )

    assert [chunk.content for chunk in chunks] == [
        "alpha beta gamma",
        "gamma delta epsilon",
    ]
    assert [(chunk.start_offset, chunk.end_offset) for chunk in chunks] == [
        (0, 16),
        (11, 30),
    ]
    assert [chunk.id for chunk in retries] == [chunk.id for chunk in chunks]
    assert chunks[0].section_ordinal == 3


def test_fixed_windows_cross_sections_and_keep_each_source_locator() -> None:
    sections = (
        ExtractedSection(
            ordinal=1,
            heading_path=("Results", "Second"),
            text="gamma delta epsilon",
            source_location=SourceLocation(
                page_index_zero_based=4,
                bounding_box=(0.1, 0.2, 0.8, 0.7),
                coordinate_system="top-left-normalized-0-1",
            ),
        ),
        ExtractedSection(
            ordinal=0,
            heading_path=("Methods",),
            text="alpha beta",
            source_location=SourceLocation(page_index_zero_based=2),
        ),
    )
    config = ChunkingConfig(3, 1, 2, strategy="fixed-window")

    chunks = chunk_sections_fixed_window(
        sections,
        document_id=DOCUMENT_ID,
        extraction_id=EXTRACTION_ID,
        config=config,
        tokenizer=WhitespaceTokenizer(),
    )

    assert chunks[0].content == "alpha beta\n\ngamma"
    assert chunks[0].section_ordinal is None
    assert chunks[0].start_offset is None
    assert chunks[0].end_offset is None
    assert chunks[0].source_location == SourceLocation()
    spans = source_spans_for_evidence_unit(chunks[0])
    assert [
        (span.section_ordinal, span.start_offset, span.end_offset) for span in spans
    ] == [
        (0, 0, 10),
        (1, 0, 5),
    ]
    assert spans[0].source_location.page_index_zero_based == 2
    assert spans[1].source_location.bounding_box == (0.1, 0.2, 0.8, 0.7)
    assert spans[1].chunk_start_offset == 12
    region = region_from_evidence_unit(chunks[0])
    assert region.section_ordinal == 0
    assert [
        (span.section_ordinal, span.start_offset, span.end_offset)
        for span in region.additional_spans
    ] == [(1, 0, 5)]
    assert config == ChunkingConfig.from_dict(config.to_dict())
    assert config.config_id != ChunkingConfig(3, 1, 2).config_id


def test_changed_content_has_a_different_evidence_identity() -> None:
    section = ExtractedSection(ordinal=0, heading_path=("Results",), text="value 1")
    changed = ExtractedSection(ordinal=0, heading_path=("Results",), text="value 2")
    config = ChunkingConfig(3, 0, 2)

    first = chunk_section(
        section,
        document_id=DOCUMENT_ID,
        extraction_id=EXTRACTION_ID,
        config=config,
        tokenizer=WhitespaceTokenizer(),
    )[0]
    second = chunk_section(
        changed,
        document_id=DOCUMENT_ID,
        extraction_id=EXTRACTION_ID,
        config=config,
        tokenizer=WhitespaceTokenizer(),
    )[0]

    assert first.id != second.id


def test_table_row_groups_repeat_headers_and_keep_context() -> None:
    table = ExtractedTable(
        ordinal=1,
        caption="Latency by method",
        units="milliseconds",
        footnotes=("Lower is better.",),
        header_rows=1,
        cells=(
            TableCell(0, 0, "Method"),
            TableCell(0, 1, "Latency"),
            TableCell(1, 0, "A"),
            TableCell(
                1, 1, "42.1", row_header_cells=((1, 0),), column_header_cells=((0, 1),)
            ),
            TableCell(2, 0, "B"),
            TableCell(
                2, 1, "38.4", row_header_cells=((2, 0),), column_header_cells=((0, 1),)
            ),
        ),
        source_location=SourceLocation(page_index_zero_based=7),
    )

    groups = chunk_table_rows(
        table,
        document_id=DOCUMENT_ID,
        extraction_id=EXTRACTION_ID,
        config=ChunkingConfig(10, 0, 1),
    )

    assert len(groups) == 2
    assert all("Method | Latency" in group.content for group in groups)
    assert all("Caption: Latency by method" in group.content for group in groups)
    assert all("Units: milliseconds" in group.content for group in groups)
    assert all("Footnotes: Lower is better." in group.content for group in groups)
    assert "A | 42.1" in groups[0].content
    assert "B | 38.4" in groups[1].content
    assert groups[0].metadata["header_rows_repeated"] == 1


def test_table_groups_split_to_fit_the_selected_token_budget() -> None:
    table = ExtractedTable(
        ordinal=0,
        caption=None,
        units=None,
        footnotes=(),
        header_rows=1,
        cells=(
            TableCell(0, 0, "Method"),
            TableCell(0, 1, "Score"),
            TableCell(1, 0, "Dense"),
            TableCell(1, 1, "0.81"),
            TableCell(2, 0, "Hybrid"),
            TableCell(2, 1, "0.88"),
        ),
    )
    config = ChunkingConfig(7, 0, 10)

    groups = chunk_table_rows(
        table,
        document_id=DOCUMENT_ID,
        extraction_id=EXTRACTION_ID,
        config=config,
        tokenizer=WhitespaceTokenizer(),
    )

    assert len(groups) == 2
    assert all("Method | Score" in group.content for group in groups)
    assert "Dense | 0.81" in groups[0].content
    assert "Hybrid | 0.88" in groups[1].content


def test_oversized_table_row_splits_cells_and_repeats_header_context() -> None:
    table = ExtractedTable(
        ordinal=0,
        caption=None,
        units=None,
        footnotes=(),
        header_rows=1,
        cells=(
            TableCell(0, 0, "Method"),
            TableCell(0, 1, "Description"),
            TableCell(1, 0, "Problem"),
            TableCell(
                1,
                1,
                "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda "
                "mu nu xi omicron pi rho sigma tau upsilon phi chi psi omega",
                row_header_cells=((1, 0),),
                column_header_cells=((0, 1),),
            ),
        ),
    )

    groups = chunk_table_rows(
        table,
        document_id=DOCUMENT_ID,
        extraction_id=EXTRACTION_ID,
        config=ChunkingConfig(18, 2, 10),
        tokenizer=WhitespaceTokenizer(),
    )

    assert len(groups) > 1
    assert all(
        len(WhitespaceTokenizer().token_spans("passage: " + group.content)) <= 18
        for group in groups
    )
    long_cell_groups = [
        group for group in groups if group.metadata.get("cell_column") == 1
    ]
    assert len(long_cell_groups) > 1
    assert all(
        "Column headers: Description" in group.content for group in long_cell_groups
    )
    assert all("Row headers: Problem" in group.content for group in long_cell_groups)
    recovered = " ".join(
        group.content.split("Cell value: ", maxsplit=1)[1] for group in long_cell_groups
    )
    assert all(
        word in recovered
        for word in (
            "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda "
            "mu nu xi omicron pi rho sigma tau upsilon phi chi psi omega"
        ).split()
    )


def test_table_rejects_missing_header_relationships() -> None:
    with pytest.raises(ValueError, match="missing table cell"):
        ExtractedTable(
            ordinal=0,
            caption=None,
            units=None,
            footnotes=(),
            header_rows=1,
            cells=(TableCell(1, 1, "value", column_header_cells=((0, 0),)),),
        )


def test_chunking_configuration_round_trips_with_stable_id() -> None:
    config = ChunkingConfig(256, 32, 10)

    assert ChunkingConfig.from_dict(config.to_dict()) == config
    assert ChunkingConfig.from_dict(config.to_dict()).config_id == config.config_id


def test_chunking_configuration_rejects_unknown_fields_and_invalid_ranges() -> None:
    config = ChunkingConfig(256, 32, 10)
    with pytest.raises(ValueError, match="unknown"):
        ChunkingConfig.from_dict({**config.to_dict(), "extra": True})
    with pytest.raises(ValueError, match="overlap"):
        ChunkingConfig(256, 256, 10)


def test_identical_table_text_keeps_table_identity_distinct() -> None:
    first = ExtractedTable(
        ordinal=0,
        caption="Same",
        units=None,
        footnotes=(),
        header_rows=1,
        cells=(TableCell(0, 0, "Column"), TableCell(1, 0, "Value")),
    )
    second = ExtractedTable(
        ordinal=1,
        caption="Same",
        units=None,
        footnotes=(),
        header_rows=1,
        cells=(TableCell(0, 0, "Column"), TableCell(1, 0, "Value")),
    )
    config = ChunkingConfig(4, 0, 4)

    first_unit = chunk_table_rows(
        first,
        document_id=DOCUMENT_ID,
        extraction_id=EXTRACTION_ID,
        config=config,
    )[0]
    second_unit = chunk_table_rows(
        second,
        document_id=DOCUMENT_ID,
        extraction_id=EXTRACTION_ID,
        config=config,
    )[0]

    assert first_unit.content == second_unit.content
    assert first_unit.id != second_unit.id


def test_evidence_contracts_reject_non_integer_or_non_finite_coordinates() -> None:
    with pytest.raises(ValueError, match="bounding_box"):
        SourceLocation(
            bounding_box=(0.1, 0.1, float("nan"), 0.9),
            coordinate_system="top-left-normalized-0-1",
        )
    with pytest.raises(ValueError, match="coordinates"):
        TableCell(0.5, 0, "invalid row")
    with pytest.raises(ValueError, match="cell coordinates"):
        TableCell(0, 0, "invalid reference", row_header_cells=((True, 1),))
    with pytest.raises(ValueError, match="integer ranges"):
        TokenSpan(0.0, 2)


def test_fixed_window_configuration_leaves_table_rendering_unchanged() -> None:
    table = ExtractedTable(
        ordinal=0,
        caption="Results",
        units=None,
        footnotes=(),
        header_rows=1,
        cells=(TableCell(0, 0, "Method"), TableCell(1, 0, "A")),
    )
    section_aware = chunk_table_rows(
        table,
        document_id=DOCUMENT_ID,
        extraction_id=EXTRACTION_ID,
        config=ChunkingConfig(20, 0, 2),
    )
    fixed_window = chunk_table_rows(
        table,
        document_id=DOCUMENT_ID,
        extraction_id=EXTRACTION_ID,
        config=ChunkingConfig(20, 0, 2, strategy="fixed-window"),
    )

    assert [unit.content for unit in fixed_window] == [
        unit.content for unit in section_aware
    ]


def test_phase2_fixed_window_example_config_is_versioned_and_loadable() -> None:
    data = tomllib.loads(
        Path("configs/phase2-fixed-window-chunking-v1.example.toml").read_text(
            encoding="utf-8"
        )
    )

    configuration = ChunkingConfig.from_dict(data)

    assert configuration.strategy == "fixed-window"
    assert configuration.maximum_text_tokens == 480
    assert configuration.overlapping_text_tokens == 64
    assert configuration.maximum_table_rows_per_group == 6
