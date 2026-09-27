"""Checks rank-based fusion of metadata and evidence paper candidates."""

from uuid import UUID

import pytest

from research_platform.api.schemas.search import PaperSearchResponse
from research_platform.ingestion.evidence import SourceLocation
from research_platform.search.contracts import (
    ComponentScores,
    EvidenceHit,
    PaperHit,
    PaperMetadataHit,
    RankedComponent,
    RetrievalMode,
    SearchResponse,
)
from research_platform.search.paper_fusion import fuse_paper_candidates
from research_platform.search.paper_grouping import group_evidence_by_paper
from research_platform.search.profiles import FusionSettings

DOCUMENT_ID = UUID("91a7da33-066d-4c78-838a-413ba2f1b8d4")
EXTRACTION_ID = UUID("6715a62a-fb8c-41d3-812d-3130baf08f0f")


def _metadata_hit(
    paper_id: str, rank: int, lexical_score: float, title: str | None
) -> PaperMetadataHit:
    return PaperMetadataHit(
        paper_id=paper_id,
        title=title,
        publication_year=2025,
        rank=rank,
        component_scores=ComponentScores(
            lexical=RankedComponent(rank=rank, score=lexical_score)
        ),
    )


def _evidence_hit(paper_id: str, rank: int, number: int) -> EvidenceHit:
    stable_id = f"sha256:{number:064x}"
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
            dense=RankedComponent(rank=rank, score=0.9 / rank),
            fusion=RankedComponent(rank=rank, score=0.02 / rank),
        ),
        text=f"Passage {number}",
    )


def test_rank_fusion_keeps_branch_ranks_and_does_not_add_raw_scores() -> None:
    metadata_hits = (
        _metadata_hit("W100", 1, 1000.0, "Metadata only"),
        _metadata_hit("W300", 2, 0.01, "Both branches"),
    )
    evidence_hits = group_evidence_by_paper(
        (_evidence_hit("W200", 1, 1), _evidence_hit("W300", 2, 2))
    )

    fused = fuse_paper_candidates(
        metadata_hits, evidence_hits, settings=FusionSettings(rank_constant=60)
    )

    assert [hit.paper_id for hit in fused] == ["W300", "W100", "W200"]
    assert fused[0].metadata_rank == 2
    assert fused[0].evidence_rank == 2
    assert fused[0].component_scores.fusion == RankedComponent(
        rank=1, score=(1 / 62) + (1 / 62)
    )
    assert fused[0].component_scores.lexical == RankedComponent(rank=2, score=0.01)
    assert fused[0].component_scores.dense == RankedComponent(rank=2, score=0.45)
    assert fused[0].supporting_evidence == evidence_hits[1].supporting_evidence


def test_metadata_only_candidate_has_no_fabricated_evidence() -> None:
    fused = fuse_paper_candidates(
        (_metadata_hit("W100", 1, 5.0, "A metadata match"),),
        (),
        settings=FusionSettings(rank_constant=60),
    )

    assert len(fused) == 1
    assert fused[0].metadata_rank == 1
    assert fused[0].evidence_rank is None
    assert fused[0].supporting_evidence == ()
    assert fused[0].title == "A metadata match"
    assert fused[0].component_scores.fusion == RankedComponent(rank=1, score=1 / 61)


def test_equal_fused_scores_use_public_paper_id_as_stable_tie_break() -> None:
    metadata_hits = (_metadata_hit("W200", 1, 10.0, "Metadata"),)
    evidence_hits = group_evidence_by_paper((_evidence_hit("W100", 1, 1),))

    fused = fuse_paper_candidates(
        metadata_hits, evidence_hits, settings=FusionSettings(rank_constant=60)
    )

    assert [hit.paper_id for hit in fused] == ["W100", "W200"]


def test_evidence_branch_rank_is_distinct_from_strongest_passage_rank() -> None:
    evidence_candidates = group_evidence_by_paper(
        (
            _evidence_hit("W100", 1, 1),
            _evidence_hit("W100", 2, 2),
            _evidence_hit("W200", 3, 3),
        )
    )

    fused = fuse_paper_candidates(
        (), evidence_candidates, settings=FusionSettings(rank_constant=60)
    )

    assert [hit.paper_id for hit in fused] == ["W100", "W200"]
    assert fused[1].rank == fused[1].evidence_rank == 2
    assert fused[1].supporting_evidence[0].rank == 3


def test_duplicate_paper_candidates_in_one_branch_are_rejected() -> None:
    duplicate_metadata = (
        _metadata_hit("W100", 1, 4.0, "First"),
        _metadata_hit("W100", 2, 2.0, "Duplicate"),
    )

    with pytest.raises(ValueError, match="metadata ranking must not repeat paper IDs"):
        fuse_paper_candidates(
            duplicate_metadata, (), settings=FusionSettings(rank_constant=60)
        )


def test_duplicate_ranks_in_one_branch_are_rejected() -> None:
    tied_metadata = (
        _metadata_hit("W100", 1, 4.0, "First"),
        _metadata_hit("W200", 1, 2.0, "Second"),
    )

    with pytest.raises(ValueError, match="metadata ranking must not repeat ranks"):
        fuse_paper_candidates(
            tied_metadata, (), settings=FusionSettings(rank_constant=60)
        )


def test_empty_candidate_branches_return_no_results() -> None:
    assert (
        fuse_paper_candidates((), (), settings=FusionSettings(rank_constant=60)) == ()
    )


def test_paper_response_schema_preserves_both_branch_ranks() -> None:
    evidence_hits = group_evidence_by_paper((_evidence_hit("W100", 1, 1),))
    paper = fuse_paper_candidates(
        (_metadata_hit("W100", 2, 4.0, "Both branches"),),
        evidence_hits,
        settings=FusionSettings(rank_constant=60),
    )[0]
    response = SearchResponse[PaperHit](
        request_id="paper-fusion-test",
        snapshot_id=UUID("4b11fab3-d4a5-4e7a-a58e-8654accf2c6c"),
        retrieval_profile_id="sha256:" + "a" * 64,
        effective_configuration_id="sha256:" + "b" * 64,
        requested_mode=RetrievalMode.HYBRID,
        effective_mode=RetrievalMode.HYBRID,
        eligible_count=1,
        hits=(paper,),
    )

    serialized = PaperSearchResponse.from_contract(response)

    assert serialized.hits[0].metadata_rank == 2
    assert serialized.hits[0].evidence_rank == 1
