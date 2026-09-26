"""Checks for canonical snapshot-bound retrieval profile identities."""

from dataclasses import replace
from uuid import UUID

import pytest

from research_platform.search.profiles import (
    CandidateLimits,
    DenseIndexIdentity,
    FusionSettings,
    LexicalIndexIdentity,
    RerankerIdentity,
    RetrievalProfile,
    RetrievalProfileProvenance,
    SelectionRules,
    SnapshotChunkSelection,
    SnapshotSelection,
    compute_chunk_selection_id,
)

SNAPSHOT_ID = UUID("4b11fab3-d4a5-4e7a-a58e-8654accf2c6c")
DOC_ONE = UUID("91a7da33-066d-4c78-838a-413ba2f1b8d4")
DOC_TWO = UUID("f141bf26-b889-4374-8b26-5c4df718e0e4")
EXTRACTION_ONE = UUID("6715a62a-fb8c-41d3-812d-3130baf08f0f")
EXTRACTION_TWO = UUID("7cb3f6f6-3899-49d4-a124-3d64c4901ca0")
SNAPSHOT_CONFIG_ID = "sha256:" + "a" * 64
INDEX_CONFIG_ID = "sha256:" + "b" * 64


def selection_members() -> tuple[SnapshotChunkSelection, ...]:
    return (
        SnapshotChunkSelection("W123", DOC_ONE, EXTRACTION_ONE, None),
        SnapshotChunkSelection("W456", DOC_TWO, EXTRACTION_TWO, "sha256:" + "c" * 64),
    )


def profile(*, reranker: RerankerIdentity | None = None) -> RetrievalProfile:
    snapshot = SnapshotSelection.from_members(
        snapshot_id=SNAPSHOT_ID,
        snapshot_configuration_id=SNAPSHOT_CONFIG_ID,
        members=selection_members(),
        selected_chunk_ids=("sha256:" + "d" * 64, "sha256:" + "e" * 64),
    )
    return RetrievalProfile(
        snapshot=snapshot,
        lexical_index=LexicalIndexIdentity(
            implementation="bm25-candidate",
            implementation_revision="0.1",
            analyzer="english",
            analyzer_revision="analyzer-v1",
            normalization_revision="normalization-v1",
            index_format_revision="format-v1",
        ),
        dense_index=DenseIndexIdentity(
            model="e5-small-v2",
            revision="revision-a",
            preprocessing_revision="passage-query-prefix-v1",
            dimensions=384,
            maximum_input_tokens=512,
            index_configuration_id=INDEX_CONFIG_ID,
        ),
        reranker=reranker,
        fusion=FusionSettings(rank_constant=60),
        candidate_limits=CandidateLimits(
            lexical_top_k=50,
            dense_top_k=50,
            fused_top_k=50,
            rerank_top_k=10 if reranker is not None else None,
        ),
        selection_rules=SelectionRules(),
    )


def test_chunk_selection_id_is_order_independent_and_binds_exact_chunk_ids() -> None:
    members = selection_members()
    chunks = ("sha256:" + "d" * 64, "sha256:" + "e" * 64)

    first = compute_chunk_selection_id(
        snapshot_id=SNAPSHOT_ID,
        snapshot_configuration_id=SNAPSHOT_CONFIG_ID,
        members=members,
        selected_chunk_ids=chunks,
    )
    reordered = compute_chunk_selection_id(
        snapshot_id=SNAPSHOT_ID,
        snapshot_configuration_id=SNAPSHOT_CONFIG_ID,
        members=tuple(reversed(members)),
        selected_chunk_ids=tuple(reversed(chunks)),
    )
    changed_chunk = compute_chunk_selection_id(
        snapshot_id=SNAPSHOT_ID,
        snapshot_configuration_id=SNAPSHOT_CONFIG_ID,
        members=members,
        selected_chunk_ids=("sha256:" + "d" * 64, "sha256:" + "f" * 64),
    )

    assert first == reordered
    assert first.startswith("sha256:")
    assert first != changed_chunk


def test_chunk_selection_identity_rejects_ambiguous_or_invalid_inputs() -> None:
    member = selection_members()[0]
    with pytest.raises(ValueError, match="duplicate paper/document selections"):
        compute_chunk_selection_id(
            snapshot_id=SNAPSHOT_ID,
            snapshot_configuration_id=SNAPSHOT_CONFIG_ID,
            members=(member, member),
            selected_chunk_ids=("sha256:" + "d" * 64,),
        )
    with pytest.raises(ValueError, match="selected_chunk_ids must not be empty"):
        compute_chunk_selection_id(
            snapshot_id=SNAPSHOT_ID,
            snapshot_configuration_id=SNAPSHOT_CONFIG_ID,
            members=(member,),
            selected_chunk_ids=(),
        )
    with pytest.raises(ValueError, match="selected chunk ID must be a SHA-256"):
        compute_chunk_selection_id(
            snapshot_id=SNAPSHOT_ID,
            snapshot_configuration_id=SNAPSHOT_CONFIG_ID,
            members=(member,),
            selected_chunk_ids=("chunk-1",),
        )


def test_profile_round_trip_and_identity_include_every_result_choice() -> None:
    base = profile(
        reranker=RerankerIdentity(
            model="minilm-l6-v2",
            revision="revision-r1",
            preprocessing_revision="pair-truncation-v1",
            maximum_input_tokens=512,
        )
    )

    restored = RetrievalProfile.from_dict(base.to_dict())
    assert restored == base
    assert restored.profile_id == base.profile_id

    assert (
        replace(
            base,
            lexical_index=replace(base.lexical_index, analyzer_revision="analyzer-v2"),
        ).profile_id
        != base.profile_id
    )
    assert (
        replace(
            base,
            dense_index=replace(base.dense_index, revision="revision-b"),
        ).profile_id
        != base.profile_id
    )
    assert (
        replace(
            base,
            reranker=replace(base.reranker, preprocessing_revision="pair-v2"),
        ).profile_id
        != base.profile_id
    )
    assert (
        replace(
            base,
            fusion=replace(base.fusion, rank_constant=30),
        ).profile_id
        != base.profile_id
    )
    assert (
        replace(
            base,
            candidate_limits=replace(base.candidate_limits, fused_top_k=40),
        ).profile_id
        != base.profile_id
    )
    assert (
        replace(
            base,
            selection_rules=replace(base.selection_rules, paper_support_limit=2),
        ).profile_id
        != base.profile_id
    )
    assert (
        replace(
            base,
            snapshot=replace(base.snapshot, chunk_selection_id="sha256:" + "f" * 64),
        ).profile_id
        != base.profile_id
    )


def test_code_revision_is_separate_from_profile_compatibility_identity() -> None:
    config = profile()
    first = RetrievalProfileProvenance(
        profile_id=config.profile_id,
        code_revision="1" * 40,
        working_tree_dirty=False,
    )
    second = RetrievalProfileProvenance(
        profile_id=config.profile_id,
        code_revision="2" * 40,
        working_tree_dirty=True,
    )

    assert first.profile_id == second.profile_id == config.profile_id
    assert first.to_dict() != second.to_dict()
    assert "code_revision" not in config.to_dict()


def test_profile_stage_presence_and_bounds_are_validated() -> None:
    base = profile()
    with pytest.raises(ValueError, match="fused_top_k must match"):
        replace(
            base,
            candidate_limits=replace(base.candidate_limits, fused_top_k=None),
        )
    with pytest.raises(ValueError, match="fusion requires lexical and dense"):
        RetrievalProfile(
            snapshot=base.snapshot,
            lexical_index=base.lexical_index,
            dense_index=None,
            fusion=FusionSettings(),
            candidate_limits=CandidateLimits(
                lexical_top_k=50,
                dense_top_k=None,
                fused_top_k=50,
                rerank_top_k=None,
            ),
        )
    with pytest.raises(ValueError, match="configured candidate maximum"):
        CandidateLimits(lexical_top_k=201)
    with pytest.raises(ValueError, match="configured per-paper maximum"):
        SelectionRules(paper_support_limit=6)
    with pytest.raises(ValueError, match="unknown"):
        RetrievalProfile.from_dict({**base.to_dict(), "git_revision": "abc"})
