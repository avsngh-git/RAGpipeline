"""Pure preflight checks for the Phase 2 dense index copy command."""

from __future__ import annotations

from uuid import UUID

import pytest

from research_platform.ingestion.indexing import IndexConfiguration
from research_platform.ingestion.snapshot_selection import SnapshotSelection
from scripts.phase2_copy_dense_index import CopyPlan, CopyRefused, build_copy_plan

SNAPSHOT_ID = UUID("4b11fab3-d4a5-4e7a-a58e-8654accf2c6c")
COLLECTION = "phase2-dev-gte-modernbert-base-v1"
SOURCE_SELECTION = SnapshotSelection(
    snapshot_id=SNAPSHOT_ID,
    snapshot_configuration_id="sha256:" + "a" * 64,
    chunk_selection_id="sha256:" + "b" * 64,
)
CONFIGURATION = IndexConfiguration(
    collection_name=COLLECTION,
    embedding_model="Alibaba-NLP/gte-modernbert-base",
    embedding_revision="e7f32e3c00f91d699e8c43b53106206bcc72bb22",
    preprocessing_revision="gte-modernbert-base:no-prefix:cls-pooling:l2-normalize:v1",
    vector_size=768,
    distance="Cosine",
    batch_size=8,
    maximum_input_tokens=8192,
)
STATE = {
    "collection_name": COLLECTION,
    "status": "ready",
    "expected_count": 44_277,
    "indexed_count": 44_277,
    "details": {
        "evidence_ids_sha256": "evidence-fingerprint",
        "qdrant_evidence_ids_sha256": "evidence-fingerprint",
    },
}


def _plan(
    *,
    source_selection: SnapshotSelection = SOURCE_SELECTION,
    target_selection: SnapshotSelection = SOURCE_SELECTION,
    target_configuration: dict[str, object] | None = None,
    target_state: dict[str, object] | None = None,
    target_collection_exists: bool = False,
) -> CopyPlan:
    return build_copy_plan(
        snapshot_id=SNAPSHOT_ID,
        collection_name=COLLECTION,
        source_selection=source_selection,
        target_selection=target_selection,
        source_configuration_id=CONFIGURATION.configuration_id,
        source_configuration=CONFIGURATION.to_dict(),
        source_state=STATE,
        target_configuration=target_configuration,
        target_state=target_state,
        target_collection_exists=target_collection_exists,
    )


def test_dry_run_plan_contains_collection_configuration_and_count() -> None:
    plan = _plan()

    assert plan.collection_name == COLLECTION
    assert plan.configuration_id == CONFIGURATION.configuration_id
    assert plan.point_count == 44_277
    assert plan.snapshot_id == SNAPSHOT_ID


def test_plan_refuses_snapshot_selection_mismatch() -> None:
    different_selection = SnapshotSelection(
        snapshot_id=SNAPSHOT_ID,
        snapshot_configuration_id="sha256:" + "c" * 64,
        chunk_selection_id="sha256:" + "d" * 64,
    )

    with pytest.raises(CopyRefused, match="snapshot selection differs"):
        _plan(target_selection=different_selection)


def test_plan_refuses_existing_target_collection() -> None:
    with pytest.raises(CopyRefused, match="collection already exists"):
        _plan(target_collection_exists=True)


def test_plan_refuses_conflicting_target_configuration() -> None:
    conflicting_configuration = CONFIGURATION.to_dict()
    conflicting_configuration["vector_size"] = 384

    with pytest.raises(CopyRefused, match="different content"):
        _plan(target_configuration=conflicting_configuration)


def test_plan_refuses_conflicting_target_snapshot_state() -> None:
    conflicting_state = {**STATE, "expected_count": 10}

    with pytest.raises(CopyRefused, match="state already has different content"):
        _plan(target_state=conflicting_state)


def test_plan_refuses_wrong_accepted_snapshot_point_count() -> None:
    wrong_count = {**STATE, "expected_count": 44_276, "indexed_count": 44_276}

    with pytest.raises(CopyRefused, match="accepted point count"):
        build_copy_plan(
            snapshot_id=SNAPSHOT_ID,
            collection_name=COLLECTION,
            source_selection=SOURCE_SELECTION,
            target_selection=SOURCE_SELECTION,
            source_configuration_id=CONFIGURATION.configuration_id,
            source_configuration=CONFIGURATION.to_dict(),
            source_state=wrong_count,
            target_configuration=None,
            target_state=None,
            target_collection_exists=False,
        )
