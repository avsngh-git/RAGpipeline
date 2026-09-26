"""Checks evidence-to-paper grouping and the strongest-passage score policy."""

from uuid import UUID

import pytest

from research_platform.ingestion.evidence import SourceLocation
from research_platform.search.contracts import (
    ComponentScores,
    EvidenceHit,
    PaperHit,
    RankedComponent,
)
from research_platform.search.paper_grouping import group_evidence_by_paper
from research_platform.search.profiles import SelectionRules

DOCUMENT_ID = UUID("91a7da33-066d-4c78-838a-413ba2f1b8d4")
EXTRACTION_ID = UUID("6715a62a-fb8c-41d3-812d-3130baf08f0f")


def _evidence(
    paper_id: str,
    rank: int,
    chunk_number: int,
    fusion_score: float,
) -> EvidenceHit:
    stable_id = f"sha256:{chunk_number:064x}"
    return EvidenceHit(
        chunk_id=stable_id,
        source_evidence_ids=(stable_id,),
        paper_id=paper_id,
        document_id=DOCUMENT_ID,
        document_version="published-2025",
        document_version_kind="published",
        extraction_id=EXTRACTION_ID,
        chunking_configuration_id=None,
        kind="text",
        source_location=SourceLocation(),
        rank=rank,
        component_scores=ComponentScores(
            fusion=RankedComponent(rank=rank, score=fusion_score)
        ),
        text=f"Evidence passage {chunk_number}",
    )


def test_grouping_uses_best_passage_and_does_not_sum_long_paper_scores() -> None:
    hits = (
        _evidence("W100", 1, 1, 0.10),
        _evidence("W200", 2, 2, 0.08),
        _evidence("W200", 3, 3, 0.07),
        _evidence("W200", 4, 4, 0.06),
        _evidence("W200", 5, 5, 0.05),
        _evidence("W200", 6, 6, 0.04),
    )

    papers = group_evidence_by_paper(hits)

    assert [paper.paper_id for paper in papers] == ["W100", "W200"]
    assert [paper.rank for paper in papers] == [1, 2]
    assert papers[1].component_scores.fusion == RankedComponent(rank=2, score=0.08)
    assert [hit.chunk_id for hit in papers[1].supporting_evidence] == [
        hits[1].chunk_id,
        hits[2].chunk_id,
        hits[3].chunk_id,
    ]
    assert all(
        paper.title is None and paper.publication_year is None for paper in papers
    )


def test_tied_best_hit_ranks_use_public_paper_id_as_a_stable_tie_break() -> None:
    papers = group_evidence_by_paper(
        (_evidence("W200", 1, 2, 0.1), _evidence("W100", 1, 1, 0.1))
    )

    assert [paper.paper_id for paper in papers] == ["W100", "W200"]


def test_profile_support_limit_is_applied_to_distinct_chunks() -> None:
    hits = tuple(_evidence("W100", rank, rank, 1 / rank) for rank in range(1, 5))

    papers = group_evidence_by_paper(
        hits, selection_rules=SelectionRules(paper_support_limit=2)
    )

    assert len(papers) == 1
    assert len(papers[0].supporting_evidence) == 2
    assert len({hit.chunk_id for hit in papers[0].supporting_evidence}) == 2


def test_duplicate_chunk_ids_are_rejected() -> None:
    hit = _evidence("W100", 1, 1, 0.1)

    with pytest.raises(ValueError, match="must not repeat chunk IDs"):
        group_evidence_by_paper((hit, hit))


def test_non_evidence_inputs_are_rejected() -> None:
    with pytest.raises(TypeError, match="EvidenceHit values"):
        group_evidence_by_paper((PaperHit("W100", None, None, 1, ComponentScores()),))  # type: ignore[arg-type]


def test_empty_evidence_returns_no_paper_candidates() -> None:
    assert group_evidence_by_paper(()) == ()
