"""Checks profile-bounded paper result selection and truncation semantics."""

from dataclasses import replace
from uuid import UUID

import pytest

from research_platform.ingestion.snapshot_selection import (
    SnapshotChunkSelection,
    SnapshotSelection,
)
from research_platform.search.contracts import (
    ComponentScores,
    PaperMetadataHit,
    RankedComponent,
)
from research_platform.search.paper_fusion import fuse_paper_candidates
from research_platform.search.paper_selection import (
    PaperResultSelection,
    paper_candidate_scan_limit,
    select_paper_results,
)
from research_platform.search.profiles import (
    CandidateLimits,
    DenseIndexIdentity,
    FusionSettings,
    LexicalIndexIdentity,
    RerankerIdentity,
    RetrievalProfile,
    SelectionRules,
)

SNAPSHOT_ID = UUID("4b11fab3-d4a5-4e7a-a58e-8654accf2c6c")
DOCUMENT_ID = UUID("91a7da33-066d-4c78-838a-413ba2f1b8d4")
EXTRACTION_ID = UUID("6715a62a-fb8c-41d3-812d-3130baf08f0f")
SHA_A = "sha256:" + "a" * 64
SHA_B = "sha256:" + "b" * 64


def _profile() -> RetrievalProfile:
    snapshot = SnapshotSelection.from_members(
        snapshot_id=SNAPSHOT_ID,
        snapshot_configuration_id=SHA_A,
        members=(SnapshotChunkSelection("W123", DOCUMENT_ID, EXTRACTION_ID, None),),
        selected_chunk_ids=(SHA_B,),
    )
    return RetrievalProfile(
        snapshot=snapshot,
        lexical_index=LexicalIndexIdentity(
            implementation="bm25-candidate",
            implementation_revision="0.1",
            analyzer="scientific-en-v1",
            analyzer_revision="1",
            normalization_revision="1",
            index_format_revision="2",
        ),
        dense_index=DenseIndexIdentity(
            model="e5-small-v2",
            revision="revision-a",
            preprocessing_revision="query-prefix-v1",
            dimensions=384,
            maximum_input_tokens=512,
            index_configuration_id=SHA_B,
        ),
        fusion=FusionSettings(rank_constant=60),
        candidate_limits=CandidateLimits(
            lexical_top_k=3,
            dense_top_k=4,
            fused_top_k=5,
            rerank_top_k=None,
        ),
        selection_rules=SelectionRules(),
    )


def _candidates(count: int):
    metadata_hits = tuple(
        PaperMetadataHit(
            paper_id=f"W{index + 100}",
            title=f"Paper {index}",
            publication_year=2025,
            rank=index,
            component_scores=ComponentScores(
                lexical=RankedComponent(rank=index, score=1.0 / index)
            ),
        )
        for index in range(1, count + 1)
    )
    return fuse_paper_candidates(
        metadata_hits, (), settings=FusionSettings(rank_constant=60)
    )


def test_scan_cap_is_derived_from_profile_branch_candidate_limits() -> None:
    assert paper_candidate_scan_limit(_profile()) == 8


def test_result_page_reports_exact_omissions_within_complete_candidate_pools() -> None:
    candidates = _candidates(3)

    page = select_paper_results(
        candidates,
        limit=2,
        profile=_profile(),
        candidate_pools_truncated=False,
    )

    assert [hit.paper_id for hit in page.hits] == ["W101", "W102"]
    assert page.candidate_count == 3
    assert page.candidate_scan_limit == 8
    assert page.truncated is True
    assert page.omitted_count == 1
    assert page.omitted_count_exact is True
    assert page.warnings == ("paper result limit omitted lower-ranked candidates",)


def test_upstream_pool_truncation_is_exposed_even_when_page_is_underfilled() -> None:
    page = select_paper_results(
        _candidates(1),
        limit=10,
        profile=_profile(),
        candidate_pools_truncated=True,
    )

    assert len(page.hits) == 1
    assert page.truncated is True
    assert page.omitted_count == 0
    assert page.omitted_count_exact is False
    assert page.warnings == (
        "candidate pools were truncated; omitted_count covers only observed candidates",
    )


def test_scan_cap_rejects_more_candidates_than_profile_allows() -> None:
    with pytest.raises(ValueError, match="exceeds the profile-derived scan cap"):
        select_paper_results(
            _candidates(9),
            limit=10,
            profile=_profile(),
            candidate_pools_truncated=False,
        )


def test_selection_result_rejects_duplicate_paper_rows() -> None:
    first, second = _candidates(2)
    duplicate = type(second)(
        paper_id=first.paper_id,
        title=second.title,
        publication_year=second.publication_year,
        rank=2,
        component_scores=second.component_scores,
        metadata_rank=second.metadata_rank,
        evidence_rank=second.evidence_rank,
    )

    with pytest.raises(ValueError, match="one record per paper"):
        select_paper_results(
            (first, duplicate),
            limit=10,
            profile=_profile(),
            candidate_pools_truncated=False,
        )


def test_selection_contract_requires_truncation_for_inexact_omission_count() -> None:
    with pytest.raises(ValueError, match="truncated must include"):
        PaperResultSelection(
            hits=(),
            candidate_count=0,
            candidate_scan_limit=1,
            truncated=False,
            omitted_count=0,
            omitted_count_exact=False,
        )


def test_paper_scan_covers_fused_evidence_tail_beyond_reranker_prefix() -> None:
    profile = _profile()
    profile = replace(
        profile,
        reranker=RerankerIdentity(
            model="test-reranker",
            revision="revision-a",
            preprocessing_revision="query-source-v1",
            maximum_input_tokens=512,
        ),
        candidate_limits=replace(
            profile.candidate_limits, rerank_top_k=2, fused_top_k=5
        ),
    )

    assert paper_candidate_scan_limit(profile) == 8
    page = select_paper_results(
        _candidates(8),
        limit=8,
        profile=profile,
        candidate_pools_truncated=False,
    )
    assert page.candidate_count == 8
    assert len(page.hits) == 8
