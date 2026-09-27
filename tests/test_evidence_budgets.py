"""Checks complete-hit item, per-paper, character and token budgets."""

from uuid import UUID

import pytest

from research_platform.ingestion.evidence import SourceLocation
from research_platform.search.contracts import (
    ComponentScores,
    EvidenceHit,
    PaperHit,
    TableCellEvidence,
    TableEvidenceContext,
    TableRowEvidence,
)
from research_platform.search.evidence_budgets import (
    apply_evidence_budgets_to_paper_support,
    select_evidence_results,
)
from research_platform.search.profiles import SelectionRules

DOCUMENT_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
EXTRACTION_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")


def _hit(
    paper_id: str,
    rank: int,
    text: str,
    *,
    kind: str = "text",
    table_context: TableEvidenceContext | None = None,
) -> EvidenceHit:
    source_id = f"source-{rank}"
    return EvidenceHit(
        chunk_id=f"chunk-{rank}",
        source_evidence_ids=(source_id,),
        paper_id=paper_id,
        document_id=DOCUMENT_ID,
        document_version="published-2025",
        document_version_kind="published",
        extraction_id=EXTRACTION_ID,
        chunking_configuration_id=None,
        kind=kind,  # type: ignore[arg-type]
        source_location=SourceLocation(page_index_zero_based=4),
        rank=rank,
        component_scores=ComponentScores(),
        text=text,
        table_context=table_context,
    )


def _table_hit() -> EvidenceHit:
    source_id = "table-source"
    header = TableCellEvidence(0, 0, "Outcome", "cell")
    value = TableCellEvidence(
        1,
        0,
        "42",
        "cell",
        row_header_references=((1, 0),),
        row_headers=("Adults",),
        column_header_references=((0, 0),),
        column_headers=("Outcome",),
    )
    context = TableEvidenceContext(
        table_ordinal=2,
        header_row_count=1,
        caption="Trial results",
        units="percent",
        footnotes=("Adjusted estimate.",),
        header_rows=(TableRowEvidence(0, (header,)),),
        selected_rows=(TableRowEvidence(1, (value,)),),
        selected_cells=(),
        source_evidence_ids=(source_id,),
    )
    return EvidenceHit(
        chunk_id="table-chunk",
        source_evidence_ids=(source_id,),
        paper_id="W100",
        document_id=DOCUMENT_ID,
        document_version="published-2025",
        document_version_kind="published",
        extraction_id=EXTRACTION_ID,
        chunking_configuration_id=None,
        kind="table_row_group",
        source_location=SourceLocation(page_index_zero_based=4),
        rank=1,
        component_scores=ComponentScores(),
        text="Outcome | 42",
        table_context=context,
    )


def _paper(hit: EvidenceHit, rank: int) -> PaperHit:
    return PaperHit(
        paper_id=hit.paper_id,
        title=f"Paper {hit.paper_id}",
        publication_year=2025,
        rank=rank,
        component_scores=ComponentScores(),
        supporting_evidence=(hit,),
        evidence_rank=hit.rank,
    )


def test_character_budget_omits_whole_units_and_keeps_later_fitting_hits() -> None:
    candidates = (
        _hit("W100", 1, "123456"),
        _hit("W200", 2, "abcdef"),
        _hit("W300", 3, "z"),
    )
    rules = SelectionRules(
        evidence_result_character_budget=7,
        evidence_result_token_budget=100,
    )

    result = select_evidence_results(
        candidates,
        result_limit=10,
        selection_rules=rules,
    )

    assert [hit.chunk_id for hit in result.hits] == ["chunk-1", "chunk-3"]
    assert result.omissions[0].chunk_id == "chunk-2"
    assert result.omissions[0].source_evidence_ids == ("source-2",)
    assert result.omissions[0].reasons == ("result_character_budget",)
    assert result.characters_used == 7
    assert result.truncated is True
    assert result.omitted_count_exact is True
    assert result.warnings == ("character budget omitted complete evidence units",)


def test_token_budget_uses_the_profile_bound_unicode_tokenizer() -> None:
    candidates = (
        _hit("W100", 1, "alpha-beta 42.1%"),
        _hit("W200", 2, "small"),
    )
    rules = SelectionRules(
        evidence_result_character_budget=100,
        evidence_result_token_budget=2,
    )

    result = select_evidence_results(
        candidates,
        result_limit=10,
        selection_rules=rules,
    )

    assert [hit.chunk_id for hit in result.hits] == ["chunk-2"]
    assert result.omissions[0].reasons == ("result_token_budget",)
    assert result.tokens_used == 1


def test_item_and_per_paper_limits_report_source_linked_omissions() -> None:
    candidates = (
        _hit("W100", 1, "one"),
        _hit("W200", 2, "two"),
        _hit("W100", 3, "three"),
    )

    result = select_evidence_results(
        candidates,
        result_limit=2,
        selection_rules=SelectionRules(
            evidence_per_paper_limit=1,
            evidence_result_character_budget=100,
            evidence_result_token_budget=100,
        ),
        candidate_pools_truncated=True,
    )

    assert [hit.chunk_id for hit in result.hits] == ["chunk-1", "chunk-2"]
    assert result.omissions[0].chunk_id == "chunk-3"
    assert result.omissions[0].reasons == ("result_item_limit",)
    assert result.omitted_count == 1
    assert result.omitted_count_exact is False
    assert result.truncated is True
    assert result.warnings == (
        "result item limit omitted lower-ranked evidence",
        "candidate pools were truncated; omitted_count covers observed candidates",
    )


def test_per_paper_cap_is_applied_before_remaining_text_budget() -> None:
    candidates = (
        _hit("W100", 1, "first"),
        _hit("W100", 2, "second"),
        _hit("W200", 3, "third"),
    )
    rules = SelectionRules(
        evidence_per_paper_limit=1,
        evidence_result_character_budget=100,
        evidence_result_token_budget=100,
    )

    result = select_evidence_results(candidates, result_limit=10, selection_rules=rules)

    assert [hit.chunk_id for hit in result.hits] == ["chunk-1", "chunk-3"]
    assert result.omissions[0].reasons == ("per_paper_limit",)


def test_table_context_values_are_counted_with_the_bounded_readable_chunk() -> None:
    hit = _table_hit()
    rules = SelectionRules(
        evidence_result_character_budget=100,
        evidence_result_token_budget=100,
    )

    result = select_evidence_results((hit,), result_limit=1, selection_rules=rules)

    assert result.hits == (hit,)
    assert result.characters_used == 72
    assert result.tokens_used == 13


def test_evidence_search_page_cannot_exceed_the_request_item_maximum() -> None:
    with pytest.raises(ValueError, match="evidence search bounds"):
        select_evidence_results((), result_limit=51)


def test_table_hits_require_source_resolved_context_before_budgeting() -> None:
    hit = _hit("W100", 1, "table", kind="table_row_group")

    with pytest.raises(ValueError, match="source-resolved context"):
        select_evidence_results((hit,), result_limit=1)


def test_paper_support_budgets_apply_globally_without_changing_paper_ranks() -> None:
    first = _hit("W100", 1, "first")
    second = _hit("W200", 2, "second")
    rules = SelectionRules(
        paper_support_limit=2,
        evidence_result_character_budget=5,
        evidence_result_token_budget=10,
    )

    result = apply_evidence_budgets_to_paper_support(
        (_paper(first, 1), _paper(second, 2)),
        selection_rules=rules,
    )

    assert [paper.rank for paper in result.papers] == [1, 2]
    assert [paper.paper_id for paper in result.papers] == ["W100", "W200"]
    assert [hit.chunk_id for hit in result.papers[0].supporting_evidence] == ["chunk-1"]
    assert result.papers[1].supporting_evidence == ()
    assert result.selection.omissions[0].source_evidence_ids == ("source-2",)
    assert result.selection.omissions[0].reasons == ("result_character_budget",)


def test_result_budgets_cannot_exceed_the_configured_maximum() -> None:
    with pytest.raises(ValueError, match="configured result maximum"):
        SelectionRules(evidence_result_character_budget=24_001)
    with pytest.raises(ValueError, match="configured result maximum"):
        SelectionRules(evidence_result_token_budget=8_001)
    with pytest.raises(ValueError, match="unsupported text budget tokenizer"):
        SelectionRules(text_budget_tokenizer="whitespace-v1")  # type: ignore[arg-type]
