"""Hand-computed behavior checks for profile-bound reciprocal-rank fusion."""

import pytest

from research_platform.ingestion.indexing import IndexInput
from research_platform.search.dense_search import HydratedDenseHit
from research_platform.search.fusion import reciprocal_rank_fusion
from research_platform.search.lexical import LexicalHit
from research_platform.search.profiles import FusionSettings


def _lexical(evidence_id: str, score: float) -> LexicalHit:
    return LexicalHit(stable_id=evidence_id, paper_id="W123", row=0, score=score)


def _dense(evidence_id: str, rank: int, score: float) -> HydratedDenseHit:
    evidence = IndexInput(
        evidence_id=evidence_id,
        text="evidence text",
        payload={
            "paper_id": "W123",
            "document_id": "document",
            "extraction_id": "extraction",
            "snapshot_id": "snapshot",
        },
    )
    return HydratedDenseHit(rank=rank, score=score, evidence=evidence)


def test_rrf_sums_one_based_contributions_for_matching_evidence_ids() -> None:
    results = reciprocal_rank_fusion(
        (_lexical("a", 12.0), _lexical("b", 7.0)),
        (_dense("b", 1, 0.91), _dense("c", 2, 0.72)),
        settings=FusionSettings(rank_constant=60),
    )

    assert [item.evidence_id for item in results] == ["b", "a", "c"]
    assert results[0].score == pytest.approx(1 / 62 + 1 / 61)
    assert results[1].score == pytest.approx(1 / 61)
    assert results[2].score == pytest.approx(1 / 62)
    assert results[0].component_scores.lexical.rank == 2
    assert results[0].component_scores.lexical.score == 7.0
    assert results[0].component_scores.dense.rank == 1
    assert results[0].component_scores.dense.score == 0.91
    assert results[0].component_scores.fusion.rank == 1


def test_rrf_handles_empty_or_disjoint_branches_and_keeps_missing_component_null() -> (
    None
):
    lexical_only = reciprocal_rank_fusion(
        (_lexical("lex", 4.0),), (), settings=FusionSettings()
    )
    dense_only = reciprocal_rank_fusion(
        (), (_dense("dense", 1, 0.8),), settings=FusionSettings()
    )

    assert lexical_only[0].score == pytest.approx(1 / 61)
    assert lexical_only[0].component_scores.dense is None
    assert dense_only[0].score == pytest.approx(1 / 61)
    assert dense_only[0].component_scores.lexical is None


def test_rrf_uses_stable_evidence_ids_to_break_equal_score_ties() -> None:
    results = reciprocal_rank_fusion(
        (_lexical("z", 9.0), _lexical("a", 8.0)),
        (_dense("a", 1, 0.9), _dense("z", 2, 0.7)),
        settings=FusionSettings(rank_constant=60),
    )

    assert [item.evidence_id for item in results] == ["a", "z"]
    assert results[0].score == pytest.approx(results[1].score)
    assert results[0].component_scores.lexical.rank == 2
    assert results[0].component_scores.dense.rank == 1


def test_rrf_rejects_duplicate_ids_within_a_branch_and_invalid_dense_ranks() -> None:
    with pytest.raises(ValueError, match="must not repeat"):
        reciprocal_rank_fusion(
            (_lexical("same", 2.0), _lexical("same", 1.0)),
            (),
            settings=FusionSettings(),
        )

    with pytest.raises(ValueError, match="sequential 1-based"):
        reciprocal_rank_fusion((), (_dense("same", 2, 0.8),), settings=FusionSettings())


def test_rrf_settings_require_positive_constant_and_versioned_method() -> None:
    with pytest.raises(ValueError, match="rank_constant"):
        FusionSettings(rank_constant=0)
    with pytest.raises(ValueError, match="rrf-v1"):
        FusionSettings(method="rrf")  # type: ignore[arg-type]
