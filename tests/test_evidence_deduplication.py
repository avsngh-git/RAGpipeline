"""Conservative, source-resolvable deduplication of ranked evidence hits."""

from dataclasses import replace
from uuid import UUID

import pytest

from research_platform.ingestion.evidence import (
    EvidenceKind,
    EvidenceUnit,
    SourceLocation,
)
from research_platform.search.contracts import ComponentScores, EvidenceHit
from research_platform.search.evidence_deduplication import (
    EvidenceDeduplicationError,
    deduplicate_evidence_hits,
)

DOCUMENT_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
OTHER_DOCUMENT_ID = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")
EXTRACTION_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
OTHER_EXTRACTION_ID = UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd")


def _unit(
    unit_id: str,
    *,
    kind: EvidenceKind = "text",
    start: int | None = 0,
    end: int | None = 10,
    section: int | None = 2,
    extraction_id: UUID = EXTRACTION_ID,
    document_id: UUID = DOCUMENT_ID,
    metadata: dict[str, object] | None = None,
) -> EvidenceUnit:
    return EvidenceUnit(
        id=unit_id,
        document_id=document_id,
        extraction_id=extraction_id,
        section_ordinal=section,
        ordinal=0,
        kind=kind,
        content=f"source {unit_id}",
        start_offset=start,
        end_offset=end,
        source_location=SourceLocation(page_index_zero_based=4),
        metadata=metadata or {},
    )


def _text_unit(
    unit_id: str,
    start: int,
    end: int,
    *,
    section: int = 2,
    extraction_id: UUID = EXTRACTION_ID,
    document_id: UUID = DOCUMENT_ID,
) -> EvidenceUnit:
    return _unit(
        unit_id,
        start=start,
        end=end,
        section=section,
        extraction_id=extraction_id,
        document_id=document_id,
    )


def _row_unit(unit_id: str, start_row: int, end_row: int) -> EvidenceUnit:
    return _unit(
        unit_id,
        kind="table_row_group",
        start=None,
        end=None,
        section=None,
        metadata={
            "table_ordinal": 3,
            "row_start_inclusive": start_row,
            "row_end_exclusive": end_row,
            "header_rows_repeated": 1,
        },
    )


def _cell_unit(unit_id: str, start_token: int, end_token: int) -> EvidenceUnit:
    return _unit(
        unit_id,
        kind="table_row_group",
        start=None,
        end=None,
        section=None,
        metadata={
            "table_ordinal": 3,
            "row_start_inclusive": 2,
            "row_end_exclusive": 3,
            "header_rows_repeated": 1,
            "cell_row": 2,
            "cell_column": 1,
            "cell_token_start": start_token,
            "cell_token_end_exclusive": end_token,
        },
    )


def _hit(
    source_ids: tuple[str, ...],
    rank: int,
    *,
    chunk_id: str | None = None,
    paper_id: str = "W100",
    extraction_id: UUID = EXTRACTION_ID,
    document_id: UUID = DOCUMENT_ID,
    text: str = "evidence text",
    kind: EvidenceKind = "text",
) -> EvidenceHit:
    return EvidenceHit(
        chunk_id=chunk_id or f"chunk-{rank}",
        source_evidence_ids=source_ids,
        paper_id=paper_id,
        document_id=document_id,
        document_version="published-2025",
        document_version_kind="published",
        extraction_id=extraction_id,
        chunking_configuration_id=None,
        kind=kind,
        source_location=SourceLocation(page_index_zero_based=4),
        rank=rank,
        component_scores=ComponentScores(),
        text=text,
    )


def _deduplicate(hits: tuple[EvidenceHit, ...], units: tuple[EvidenceUnit, ...]):
    return deduplicate_evidence_hits(
        hits, source_units_by_id={unit.id: unit for unit in units}
    )


def test_contained_text_span_is_omitted_with_covering_hit_reference() -> None:
    outer = _text_unit("outer", 10, 40)
    inner = _text_unit("inner", 18, 25)
    result = _deduplicate(
        (_hit(("inner",), 2), _hit(("outer",), 1)),
        (outer, inner),
    )

    assert [hit.chunk_id for hit in result.hits] == ["chunk-1"]
    assert result.omissions[0].chunk_id == "chunk-2"
    assert result.omissions[0].reason == "source_coverage_subsumed"
    assert result.omissions[0].covered_by_chunk_ids == ("chunk-1",)


def test_partial_text_overlap_preserves_both_hits() -> None:
    first = _text_unit("first", 0, 12)
    second = _text_unit("second", 8, 20)

    result = _deduplicate(
        (_hit(("first",), 1), _hit(("second",), 2)),
        (first, second),
    )

    assert [hit.chunk_id for hit in result.hits] == ["chunk-1", "chunk-2"]
    assert result.omissions == ()


def test_union_of_retained_spans_can_cover_a_candidate() -> None:
    left = _text_unit("left", 0, 5)
    right = _text_unit("right", 5, 10)
    combined = _text_unit("combined", 0, 10)
    result = _deduplicate(
        (
            _hit(("left",), 1),
            _hit(("right",), 2),
            _hit(("combined",), 3),
        ),
        (left, right, combined),
    )

    assert [hit.chunk_id for hit in result.hits] == ["chunk-1", "chunk-2"]
    assert result.omissions[0].covered_by_chunk_ids == ("chunk-1", "chunk-2")


def test_equal_offsets_in_another_section_are_distinct_source() -> None:
    first = _text_unit("first", 0, 10, section=1)
    second = _text_unit("second", 0, 10, section=2)
    result = _deduplicate(
        (_hit(("first",), 1), _hit(("second",), 2)),
        (first, second),
    )

    assert len(result.hits) == 2


def test_repeated_table_headers_do_not_make_body_rows_overlap() -> None:
    first_rows = _row_unit("first-rows", 1, 3)
    second_rows = _row_unit("second-rows", 3, 5)
    result = _deduplicate(
        (
            _hit(("first-rows",), 1, kind="table_row_group"),
            _hit(("second-rows",), 2, kind="table_row_group"),
        ),
        (first_rows, second_rows),
    )

    assert len(result.hits) == 2
    assert result.omissions == ()


def test_table_row_containment_is_deduplicated() -> None:
    outer = _row_unit("outer-rows", 1, 8)
    inner = _row_unit("inner-rows", 3, 5)
    result = _deduplicate(
        (
            _hit(("outer-rows",), 1, kind="table_row_group"),
            _hit(("inner-rows",), 2, kind="table_row_group"),
        ),
        (outer, inner),
    )

    assert len(result.hits) == 1
    assert result.omissions[0].covered_by_chunk_ids == ("chunk-1",)


def test_overlapping_cell_segments_are_removed_only_when_fully_covered() -> None:
    first = _cell_unit("first-cell", 0, 6)
    contained = _cell_unit("contained-cell", 2, 5)
    partial = _cell_unit("partial-cell", 5, 9)
    result = _deduplicate(
        (
            _hit(("first-cell",), 1, kind="table_row_group"),
            _hit(("contained-cell",), 2, kind="table_row_group"),
            _hit(("partial-cell",), 3, kind="table_row_group"),
        ),
        (first, contained, partial),
    )

    assert [hit.chunk_id for hit in result.hits] == ["chunk-1", "chunk-3"]
    assert result.omissions[0].covered_by_chunk_ids == ("chunk-1",)


def test_full_row_group_covers_a_cell_but_cell_does_not_cover_a_row() -> None:
    row = _row_unit("whole-row", 2, 3)
    cell = _cell_unit("cell", 0, 5)
    row_result = _deduplicate(
        (
            _hit(("whole-row",), 1, kind="table_row_group"),
            _hit(("cell",), 2, kind="table_row_group"),
        ),
        (row, cell),
    )
    cell_first_result = _deduplicate(
        (
            _hit(("cell",), 1, kind="table_row_group"),
            _hit(("whole-row",), 2, kind="table_row_group"),
        ),
        (row, cell),
    )

    assert len(row_result.hits) == 1
    assert row_result.omissions[0].covered_by_chunk_ids == ("chunk-1",)
    assert len(cell_first_result.hits) == 2


def test_similar_cross_paper_evidence_is_not_source_deduplicated() -> None:
    first = _text_unit("first", 0, 10)
    second = _text_unit(
        "second",
        0,
        10,
        extraction_id=OTHER_EXTRACTION_ID,
        document_id=OTHER_DOCUMENT_ID,
    )
    result = _deduplicate(
        (
            _hit(("first",), 1, paper_id="W100", text="same wording"),
            _hit(
                ("second",),
                2,
                paper_id="W200",
                extraction_id=OTHER_EXTRACTION_ID,
                document_id=OTHER_DOCUMENT_ID,
                text="same wording",
            ),
        ),
        (first, second),
    )

    assert len(result.hits) == 2


def test_unknown_source_identity_prevents_source_overlap_omission() -> None:
    known = _text_unit("known", 0, 10)
    result = _deduplicate(
        (
            _hit(("known",), 1),
            _hit(("known", "not-loaded"), 2),
        ),
        (known,),
    )

    assert len(result.hits) == 2
    assert result.unresolved_source_evidence_ids == ("not-loaded",)


def test_exact_chunk_repeat_is_removed_and_points_to_retained_hit() -> None:
    unit = _text_unit("source", 0, 10)
    first = _hit(("source",), 1, chunk_id="same-chunk")
    duplicate = replace(first, rank=2)
    result = _deduplicate((first, duplicate), (unit,))

    assert len(result.hits) == 1
    assert result.omissions[0].reason == "duplicate_chunk_id"
    assert result.omissions[0].covered_by_chunk_ids == ("same-chunk",)


def test_exact_chunk_repeat_after_source_omission_resolves_to_retained_hit() -> None:
    broad = _text_unit("broad", 0, 10)
    narrow = _text_unit("narrow", 2, 5)
    first_narrow = _hit(("narrow",), 2, chunk_id="same-chunk")
    repeat_narrow = replace(first_narrow, rank=3)
    result = _deduplicate(
        (
            _hit(("broad",), 1, chunk_id="broad-chunk"),
            first_narrow,
            repeat_narrow,
        ),
        (broad, narrow),
    )

    assert [hit.chunk_id for hit in result.hits] == ["broad-chunk"]
    assert result.omissions[0].covered_by_chunk_ids == ("broad-chunk",)
    assert result.omissions[1].covered_by_chunk_ids == ("broad-chunk",)


def test_conflicting_source_payload_for_same_chunk_id_fails_closed() -> None:
    first = _hit(("source",), 1, chunk_id="same-chunk", text="first")
    conflict = _hit(("source",), 2, chunk_id="same-chunk", text="changed")

    with pytest.raises(EvidenceDeduplicationError, match="conflicting"):
        _deduplicate((first, conflict), (_text_unit("source", 0, 10),))


def test_source_unit_from_another_document_is_rejected() -> None:
    unit = _text_unit("source", 0, 10, section=2)
    hit = _hit(("source",), 1, document_id=OTHER_DOCUMENT_ID)

    with pytest.raises(EvidenceDeduplicationError, match="document"):
        _deduplicate((hit,), (unit,))


def test_candidate_ranks_must_be_unique() -> None:
    hits = (_hit(("first",), 1), _hit(("second",), 1))

    with pytest.raises(EvidenceDeduplicationError, match="ranks must be unique"):
        _deduplicate(
            hits,
            (_text_unit("first", 0, 5), _text_unit("second", 5, 10)),
        )
