"""Unit tests for generation-tagged Qdrant collections (P35-05)."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from typing import Any
from uuid import uuid4

import httpx
import pytest

from research_platform.ingestion.generation_index import (
    GenerationIndexConfiguration,
    GenerationPoint,
    GenerationQdrantCollection,
    SparseLexicalSettings,
    SparseVector,
    generation_filter,
    indexed_paper_filter,
    paper_point_id,
    passage_point_id,
    with_conditions,
)
from research_platform.ingestion.indexing import IndexConfigurationMismatch

LEXICAL = SparseLexicalSettings(
    analyzer="scientific-en",
    analyzer_revision="v1",
    vocabulary_id="scientific-en-v1",
    k1=1.5,
    b=0.75,
    evidence_average_length=30.4,
    paper_average_length=180.2,
)


def _configuration(*, lexical: SparseLexicalSettings | None = None):
    return GenerationIndexConfiguration(
        passages_collection="test-passages",
        papers_collection="test-papers",
        embedding_model="model",
        embedding_revision="revision",
        preprocessing_revision="preprocessing",
        vector_size=2,
        distance="Cosine",
        batch_size=2,
        maximum_input_tokens=512,
        lexical=lexical,
    )


class _Recorder:
    def __init__(self, existing: dict[str, Any] | None = None) -> None:
        self.requests: list[tuple[str, str, Any]] = []
        self.existing = existing
        self.responses: dict[tuple[str, str], Any] = {}

    def handle(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        self.requests.append((request.method, request.url.path, body))
        if request.method == "GET" and request.url.path.startswith("/collections/"):
            if self.existing is None:
                return httpx.Response(404)
            return httpx.Response(200, json={"result": {"config": self.existing}})
        if request.method == "PUT" and request.url.path.count("/") == 2:
            self.existing = {"params": body}
            return httpx.Response(200, json={"result": True})
        key = (request.method, request.url.path)
        if key in self.responses:
            return httpx.Response(200, json={"result": self.responses[key]})
        return httpx.Response(200, json={"result": {"status": "ok"}})


def _run(
    recorder: _Recorder,
    action: Callable[[GenerationQdrantCollection], Any],
    *,
    lexical: SparseLexicalSettings | None = None,
    role: str = "passages",
) -> Any:
    async def exercise() -> Any:
        async with httpx.AsyncClient(
            base_url="http://qdrant", transport=httpx.MockTransport(recorder.handle)
        ) as http:
            collection = GenerationQdrantCollection(
                _configuration(lexical=lexical),
                role,
                http,  # type: ignore[arg-type]
            )
            return await action(collection)

    return asyncio.run(exercise())


def test_configuration_round_trips_and_id_changes_with_lexical_settings() -> None:
    dense_only = _configuration()
    lexical = _configuration(lexical=LEXICAL)

    assert GenerationIndexConfiguration.from_dict(dense_only.to_dict()) == dense_only
    assert GenerationIndexConfiguration.from_dict(lexical.to_dict()) == lexical
    assert dense_only.configuration_id != lexical.configuration_id
    assert dense_only.configuration_id.startswith("sha256:")
    with pytest.raises(ValueError, match="separate collections"):
        GenerationIndexConfiguration(
            **{**dense_only.__dict__, "papers_collection": "test-passages"}
        )


def test_dense_configuration_matches_model_fields() -> None:
    dense = _configuration().dense_configuration()

    assert dense.collection_name == "test-passages"
    assert (dense.embedding_model, dense.embedding_revision) == ("model", "revision")
    assert dense.vector_size == 2
    assert dense.maximum_input_tokens == 512


def test_point_ids_are_deterministic_and_role_specific() -> None:
    assert passage_point_id("e1", "sha256:c") == passage_point_id("e1", "sha256:c")
    assert passage_point_id("e1", "sha256:c") != passage_point_id("e1", "sha256:d")
    assert passage_point_id("W1", "sha256:c") != paper_point_id("W1", "sha256:c")


def test_generation_filter_shape() -> None:
    assert generation_filter(3) == {
        "must": [
            {"key": "added_generation", "range": {"lte": 3}},
            {
                "should": [
                    {"is_empty": {"key": "retired_generation"}},
                    {"key": "retired_generation", "range": {"gt": 3}},
                ]
            },
        ]
    }
    assert indexed_paper_filter(2) == {
        "must": [{"key": "indexed_generation", "range": {"lte": 2}}]
    }
    combined = with_conditions(generation_filter(1), [{"key": "paper_id"}])
    assert combined["must"][-1] == {"key": "paper_id"}
    assert len(generation_filter(1)["must"]) == 2
    with pytest.raises(ValueError):
        generation_filter(0)


def test_ensure_collection_declares_sparse_only_when_lexical() -> None:
    dense = _Recorder()
    _run(dense, lambda c: c.ensure_collection())
    created = [body for method, _p, body in dense.requests if method == "PUT"][0]
    assert created == {"vectors": {"dense": {"size": 2, "distance": "Cosine"}}}

    lexical = _Recorder()
    _run(lexical, lambda c: c.ensure_collection(), lexical=LEXICAL)
    created = [body for method, _p, body in lexical.requests if method == "PUT"][0]
    assert created["sparse_vectors"] == {"scientific_bm25": {"modifier": "idf"}}


def test_ensure_collection_rejects_mismatched_existing_collection() -> None:
    wrong_size = _Recorder(
        {"params": {"vectors": {"dense": {"size": 3, "distance": "Cosine"}}}}
    )
    with pytest.raises(IndexConfigurationMismatch, match="dense vector"):
        _run(wrong_size, lambda c: c.ensure_collection())

    unnamed = _Recorder({"params": {"vectors": {"size": 2, "distance": "Cosine"}}})
    with pytest.raises(IndexConfigurationMismatch):
        _run(unnamed, lambda c: c.ensure_collection())

    missing_sparse = _Recorder(
        {"params": {"vectors": {"dense": {"size": 2, "distance": "Cosine"}}}}
    )
    with pytest.raises(IndexConfigurationMismatch, match="sparse vector"):
        _run(missing_sparse, lambda c: c.ensure_collection(), lexical=LEXICAL)


def test_payload_indexes_per_role() -> None:
    def fields(recorder: _Recorder) -> list[str]:
        return [
            body["field_name"]
            for _m, path, body in recorder.requests
            if path.endswith("/index")
        ]

    passages = _Recorder()
    _run(passages, lambda c: c.ensure_payload_indexes())
    assert fields(passages) == [
        "paper_id",
        "publication_year",
        "evidence_kind",
        "document_version_kind",
        "added_generation",
        "retired_generation",
    ]
    papers = _Recorder()
    _run(papers, lambda c: c.ensure_payload_indexes(), lexical=LEXICAL, role="papers")
    assert fields(papers) == [
        "paper_id",
        "publication_year",
        "indexed_generation",
        "catalog_status",
        "lexical_terms",
    ]


def test_upsert_rejects_oversized_batch_and_bad_vectors() -> None:
    def point(dense=(0.1, 0.2), sparse=None) -> GenerationPoint:
        return GenerationPoint(uuid4(), dense, sparse, {"evidence_id": "e"})

    recorder = _Recorder()
    with pytest.raises(ValueError, match="batch size"):
        _run(recorder, lambda c: c.upsert([point(), point(), point()]))
    with pytest.raises(ValueError, match="exactly 2"):
        _run(recorder, lambda c: c.upsert([point(dense=(0.1,))]))
    with pytest.raises(ValueError, match="lexical settings"):
        _run(recorder, lambda c: c.upsert([point(sparse=SparseVector((1,), (0.5,)))]))
    with pytest.raises(ValueError, match="require a sparse vector"):
        _run(recorder, lambda c: c.upsert([point()]), lexical=LEXICAL)
    assert not [r for r in recorder.requests if r[1].endswith("/points")]

    accepted = _Recorder()
    count = _run(
        accepted,
        lambda c: c.upsert([point(sparse=SparseVector((1, 4), (0.5, 0.25)))]),
        lexical=LEXICAL,
    )
    assert count == 1
    sent = accepted.requests[-1][2]["points"][0]["vector"]
    assert sent["scientific_bm25"] == {"indices": [1, 4], "values": [0.5, 0.25]}


def test_sparse_vector_validation() -> None:
    assert SparseVector((), ()).to_json() == {"indices": [], "values": []}
    with pytest.raises(ValueError, match="same length"):
        SparseVector((1,), ())
    with pytest.raises(ValueError, match="strictly increasing"):
        SparseVector((2, 1), (0.1, 0.2))
    with pytest.raises(ValueError, match="positive"):
        SparseVector((1,), (0.0,))


def test_query_sparse_sends_idf_filter() -> None:
    recorder = _Recorder()
    recorder.responses[("POST", "/collections/test-passages/points/query")] = {
        "points": [{"id": str(uuid4()), "score": 1.5, "payload": {"evidence_id": "e"}}]
    }
    corpus = generation_filter(2)
    matches = _run(
        recorder,
        lambda c: c.query_sparse(
            SparseVector((3,), (1.0,)),
            filter_=with_conditions(
                corpus, [{"key": "paper_id", "match": {"value": "W1"}}]
            ),
            idf_filter=corpus,
            limit=5,
        ),
        lexical=LEXICAL,
    )
    body = recorder.requests[-1][2]
    assert body["using"] == "scientific_bm25"
    assert body["params"] == {"idf": {"corpus": corpus}}
    assert body["limit"] == 5
    assert matches[0].score == 1.5
    assert (
        _run(
            _Recorder(),
            lambda c: c.query_sparse(
                SparseVector((), ()), filter_=corpus, idf_filter=corpus, limit=5
            ),
            lexical=LEXICAL,
        )
        == ()
    )


def test_retrieve_reorders_by_requested_id_and_skips_missing() -> None:
    first, second, missing = uuid4(), uuid4(), uuid4()
    recorder = _Recorder()
    recorder.responses[("POST", "/collections/test-passages/points")] = [
        {"id": str(second), "payload": {"evidence_id": "b"}},
        {
            "id": str(first),
            "payload": {"evidence_id": "a"},
            "vector": {"dense": [0.1, 0.2]},
        },
    ]
    matches = _run(
        recorder, lambda c: c.retrieve([first, missing, second], with_dense=True)
    )

    assert [m.point_id for m in matches] == [first, second]
    assert matches[0].dense == (0.1, 0.2)
    assert recorder.requests[-1][2]["with_vector"] == ["dense"]


def test_query_dense_exact_sends_exact_parameter() -> None:
    recorder = _Recorder()
    recorder.responses[("POST", "/collections/test-passages/points/query")] = {
        "points": []
    }
    _run(
        recorder,
        lambda c: c.query_dense(
            (1.0, 0.0), filter_=generation_filter(1), limit=3, exact=True
        ),
    )
    assert recorder.requests[-1][2]["params"] == {"exact": True}
    _run(
        recorder,
        lambda c: c.query_dense((1.0, 0.0), filter_=generation_filter(1), limit=3),
    )
    assert "params" not in recorder.requests[-1][2]
