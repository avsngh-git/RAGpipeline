"""Unit tests for search content served from generation collections (P35-09)."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import pytest

from research_platform.ingestion.generation_build import _passage_input, passage_payload
from research_platform.ingestion.generation_index import (
    GenerationIndexConfiguration,
    GenerationMatch,
    GenerationQdrantCollection,
    generation_filter,
    passage_point_id,
)
from research_platform.ingestion.generation_registry import GenerationRecord
from research_platform.ingestion.indexing import (
    IndexConfiguration,
    IndexInput,
    IndexReconciliationRequired,
    SnapshotIndexMismatch,
    SnapshotIndexNotReady,
)
from research_platform.search.application import _hit_and_source_unit
from research_platform.search.contracts import (
    ComponentScores,
    RankedComponent,
    SearchFilters,
)
from research_platform.search.generation_search import (
    GenerationDenseSearch,
    PassageAuthorizer,
    QdrantContentReader,
)
from research_platform.search.profile_manifest import load_frozen_profile

ROOT = Path(__file__).resolve().parents[1]
FROZEN = load_frozen_profile(ROOT / "benchmarks" / "phase2" / "frozen-profile-v10.toml")
DENSE_IDENTITY = FROZEN.dense_index
assert DENSE_IDENTITY is not None
DENSE_PROFILE = replace(
    FROZEN,
    lexical_index=None,
    fusion=None,
    reranker=None,
    candidate_limits=replace(
        FROZEN.candidate_limits,
        lexical_top_k=None,
        fused_top_k=None,
        rerank_top_k=None,
    ),
)
CONFIGURATION = GenerationIndexConfiguration(
    passages_collection="research-passages-test",
    papers_collection="research-papers-test",
    embedding_model=DENSE_IDENTITY.model,
    embedding_revision=DENSE_IDENTITY.revision,
    preprocessing_revision=DENSE_IDENTITY.preprocessing_revision,
    vector_size=DENSE_IDENTITY.dimensions,
    distance="Cosine",
    batch_size=8,
    maximum_input_tokens=DENSE_IDENTITY.maximum_input_tokens,
)
SNAPSHOT_ID = FROZEN.snapshot.snapshot_id
DOCUMENT_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
EXTRACTION_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")


def _row(
    evidence_id: str, text: str = "Reranking improves recall."
) -> dict[str, object]:
    return {
        "evidence_id": evidence_id,
        "text": text,
        "paper_id": "W1",
        "document_id": DOCUMENT_ID,
        "version": "v1",
        "document_version_kind": "published",
        "extraction_id": EXTRACTION_ID,
        "source_artifact_id": uuid4(),
        "source_artifact_sha256": "c" * 64,
        "evidence_kind": "text",
        "publication_year": 2024,
        "title": "Paper",
        "section_id": None,
        "section_title": "Results",
        "section_ordinal": 2,
        "chunking_configuration_id": "sha256:" + "d" * 64,
        "start_offset": 0,
        "end_offset": len(text),
        "evidence_source_location": json.dumps(
            {
                "page_index_zero_based": 3,
                "printed_page_label": "4",
                "bounding_box": None,
                "coordinate_system": None,
            }
        ),
        "evidence_metadata": json.dumps({"heading_path": ["Results"]}),
    }


def _qdrant_payload(evidence_id: str, *, generation: int = 1, **extra: object):
    payload = passage_payload(
        _passage_input(_row(evidence_id)), CONFIGURATION, generation
    )
    payload.update(extra)
    return payload


class _Passages:
    def __init__(self, payloads: Sequence[dict[str, object]]) -> None:
        self.payloads = {
            passage_point_id(
                cast(str, p["evidence_id"]), CONFIGURATION.configuration_id
            ): p
            for p in payloads
        }
        self.filters: list[Mapping[str, object]] = []

    async def retrieve(self, point_ids: Sequence[UUID], *, with_dense: bool = False):
        return tuple(
            GenerationMatch(point_id, 0.0, self.payloads[point_id])
            for point_id in reversed(point_ids)
            if point_id in self.payloads
        )

    async def count(self, filter_: Mapping[str, object]) -> int:
        self.filters.append(filter_)
        return 7

    async def query_dense(
        self,
        vector: Sequence[float],
        *,
        filter_: Mapping[str, object],
        limit: int,
        exact: bool = False,
    ):
        assert exact
        self.filters.append(filter_)
        return tuple(
            GenerationMatch(point_id, 0.9 - index / 10, payload)
            for index, (point_id, payload) in enumerate(self.payloads.items())
        )[:limit]


class _Authorizer:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[tuple[UUID, tuple[str, ...]]] = []

    async def authorize(self, snapshot_id: UUID, evidence_ids: Sequence[str]) -> None:
        self.calls.append((snapshot_id, tuple(evidence_ids)))
        if self.error is not None:
            raise self.error


class _Registry:
    def __init__(self, state: str | None = "published") -> None:
        self.state = state

    async def by_snapshot(self, configuration_id: str, snapshot_id: UUID):
        if self.state is None:
            return None
        return GenerationRecord(
            uuid4(), configuration_id, 1, snapshot_id, None, "e" * 64, self.state, 0, {}
        )  # type: ignore[arg-type]


class _Embedder:
    async def embed_query(self, text: str, *, configuration: IndexConfiguration):
        assert configuration == CONFIGURATION.dense_configuration()
        return [1.0] + [0.0] * (CONFIGURATION.vector_size - 1)


def _reader(
    passages: _Passages, authorizer: _Authorizer | None = None
) -> QdrantContentReader:
    return QdrantContentReader(
        cast(GenerationQdrantCollection, passages),
        cast(PassageAuthorizer, authorizer or _Authorizer()),
        CONFIGURATION,
    )


def _search(
    passages: _Passages, registry: _Registry | None = None
) -> GenerationDenseSearch:
    return GenerationDenseSearch(
        passages=cast(GenerationQdrantCollection, passages),
        reader=_reader(passages),
        registry=registry or _Registry(),
        configuration=CONFIGURATION,
        query_embedder=_Embedder(),
    )


def test_dense_search_uses_generation_filter_and_exact_count() -> None:
    passages = _Passages([_qdrant_payload("e1"), _qdrant_payload("e2")])
    response = asyncio.run(
        _search(passages).search_query(
            DENSE_PROFILE, "query", limit=2, filters=SearchFilters(year_from=2020)
        )
    )

    assert response.candidate_count == 7
    assert response.truncated
    assert response.index_configuration_id == DENSE_IDENTITY.index_configuration_id
    assert [hit.evidence.evidence_id for hit in response.hydrated_hits] == ["e1", "e2"]
    assert [hit.rank for hit in response.hydrated_hits] == [1, 2]
    must = cast(list[object], passages.filters[0]["must"])
    assert must[:2] == generation_filter(1)["must"]
    assert {"key": "publication_year", "range": {"gte": 2020}} in must
    assert all(
        cast(dict[str, object], c).get("key") != "filter_payload_revision" for c in must
    )
    assert passages.filters[0] == passages.filters[1]


def test_content_reader_preserves_order_and_payload() -> None:
    authorizer = _Authorizer()
    passages = _Passages([_qdrant_payload("e1"), _qdrant_payload("e2")])
    inputs = asyncio.run(
        _reader(passages, authorizer).read(SNAPSHOT_ID, 1, ["e2", "e1"])
    )

    assert [item.evidence_id for item in inputs] == ["e2", "e1"]
    assert inputs[0].text == "Reranking improves recall."
    assert inputs[0].payload["source_spans"]
    assert authorizer.calls == [(SNAPSHOT_ID, ("e2", "e1"))]


def test_content_reader_rejects_hash_mismatch_and_invisible_points() -> None:
    tampered = _Passages([_qdrant_payload("e1", text="edited")])
    with pytest.raises(SnapshotIndexMismatch, match="hash"):
        asyncio.run(_reader(tampered).read(SNAPSHOT_ID, 1, ["e1"]))
    later = _Passages([_qdrant_payload("e1", generation=2)])
    with pytest.raises(SnapshotIndexMismatch, match="not visible"):
        asyncio.run(_reader(later).read(SNAPSHOT_ID, 1, ["e1"]))
    retired = _Passages([_qdrant_payload("e1", retired_generation=1)])
    with pytest.raises(SnapshotIndexMismatch, match="not visible"):
        asyncio.run(_reader(retired).read(SNAPSHOT_ID, 1, ["e1"]))


def test_content_reader_rejects_missing_point() -> None:
    with pytest.raises(IndexReconciliationRequired):
        asyncio.run(
            _reader(_Passages([_qdrant_payload("e1")])).read(
                SNAPSHOT_ID, 1, ["e1", "e9"]
            )
        )


def test_unauthorized_evidence_raises_permission_error() -> None:
    reader = _reader(
        _Passages([_qdrant_payload("e1")]), _Authorizer(PermissionError("no"))
    )
    with pytest.raises(PermissionError):
        asyncio.run(reader.read(SNAPSHOT_ID, 1, ["e1"]))


def test_unpublished_generation_is_not_ready() -> None:
    passages = _Passages([_qdrant_payload("e1")])
    for registry in (_Registry(state=None), _Registry(state="verified")):
        with pytest.raises(SnapshotIndexNotReady):
            asyncio.run(
                _search(passages, registry).search_query(DENSE_PROFILE, "q", limit=1)
            )


def test_hits_from_qdrant_payload_equal_hits_from_postgres_rows() -> None:
    row = _row("e1")
    (qdrant,) = asyncio.run(
        _reader(_Passages([_qdrant_payload("e1")])).read(SNAPSHOT_ID, 1, ["e1"])
    )
    # Mirrors IndexRepository._hydrate_snapshot_matches_on_connection.
    from research_platform.ingestion.indexing import _evidence_locator_payload

    postgres = IndexInput(
        "e1",
        cast(str, row["text"]),
        {
            "snapshot_id": str(SNAPSHOT_ID),
            "paper_id": row["paper_id"],
            "document_id": str(row["document_id"]),
            "document_version": row["version"],
            "extraction_id": str(row["extraction_id"]),
            "source_artifact_id": str(row["source_artifact_id"]),
            "source_artifact_sha256": row["source_artifact_sha256"],
            "publication_year": row["publication_year"],
            "evidence_kind": row["evidence_kind"],
            "document_version_kind": row["document_version_kind"],
            "paper_title": row["title"],
            "section_id": None,
            "section_title": row["section_title"],
            "chunking_configuration_id": row["chunking_configuration_id"],
            **_evidence_locator_payload(row),
        },
    )
    scores = ComponentScores(dense=RankedComponent(rank=1, score=0.5))
    assert _hit_and_source_unit(qdrant, rank=1, scores=scores) == _hit_and_source_unit(
        postgres, rank=1, scores=scores
    )
    assert (
        qdrant.payload["text_sha256"]
        == hashlib.sha256(qdrant.text.encode()).hexdigest()
    )
