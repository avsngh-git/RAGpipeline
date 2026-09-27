"""Checks profile-bound per-paper caps for ranked evidence."""

from dataclasses import replace
from uuid import UUID

import pytest

from research_platform.ingestion.evidence import SourceLocation
from research_platform.search.contracts import ComponentScores, EvidenceHit
from research_platform.search.evidence_selection import select_evidence_per_paper
from research_platform.search.profiles import SelectionRules

DOCUMENT_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
EXTRACTION_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")


def _hit(paper_id: str, rank: int) -> EvidenceHit:
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
        kind="text",
        source_location=SourceLocation(page_index_zero_based=4),
        rank=rank,
        component_scores=ComponentScores(),
        text=f"passage {rank}",
    )


def test_default_profile_cap_keeps_three_hits_per_paper_in_global_rank_order() -> None:
    candidates = (
        _hit("W100", 1),
        _hit("W200", 2),
        _hit("W100", 3),
        _hit("W100", 4),
        _hit("W200", 5),
        _hit("W100", 6),
    )

    result = select_evidence_per_paper(candidates)

    assert [hit.chunk_id for hit in result.hits] == [
        "chunk-1",
        "chunk-2",
        "chunk-3",
        "chunk-4",
        "chunk-5",
    ]
    assert [item.chunk_id for item in result.omissions] == ["chunk-6"]
    assert result.omissions[0].paper_id == "W100"
    assert result.omissions[0].original_rank == 6
    assert result.omissions[0].source_evidence_ids == ("source-6",)
    assert result.per_paper_limit == 3
    assert result.candidate_count == 6
    assert result.omitted_count == 1
    assert result.truncated is True


def test_configured_cap_is_applied_independently_to_each_paper() -> None:
    candidates = tuple(
        _hit("W100" if rank <= 4 else "W200", rank) for rank in range(1, 8)
    )
    rules = SelectionRules(evidence_per_paper_limit=2)

    result = select_evidence_per_paper(candidates, selection_rules=rules)

    assert [hit.chunk_id for hit in result.hits] == [
        "chunk-1",
        "chunk-2",
        "chunk-5",
        "chunk-6",
    ]
    assert [item.chunk_id for item in result.omissions] == [
        "chunk-3",
        "chunk-4",
        "chunk-7",
    ]
    assert {item.paper_id for item in result.omissions} == {"W100", "W200"}
    assert all(
        hit.rank == int(hit.chunk_id.removeprefix("chunk-")) for hit in result.hits
    )


def test_selection_rules_keep_both_per_paper_caps_separate() -> None:
    rules = SelectionRules(paper_support_limit=1, evidence_per_paper_limit=2)

    assert rules.paper_support_limit == 1
    assert rules.evidence_per_paper_limit == 2


def test_empty_candidate_sequence_is_not_truncated() -> None:
    result = select_evidence_per_paper(())

    assert result.hits == ()
    assert result.omissions == ()
    assert result.candidate_count == 0
    assert result.omitted_count == 0
    assert result.truncated is False


def test_duplicate_chunk_ids_and_candidate_ranks_are_rejected() -> None:
    first = _hit("W100", 1)

    with pytest.raises(ValueError, match="must not repeat chunk IDs"):
        select_evidence_per_paper((first, first))

    with pytest.raises(ValueError, match="ranks must be unique"):
        select_evidence_per_paper((first, replace(_hit("W200", 2), rank=1)))


def test_profile_rejects_a_cap_above_the_configured_maximum() -> None:
    with pytest.raises(ValueError, match="configured per-paper maximum"):
        SelectionRules(evidence_per_paper_limit=6)
