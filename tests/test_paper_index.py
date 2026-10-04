"""Unit tests for the papers collection sync (P35-07)."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from typing import Any, cast
from uuid import UUID, uuid4

import pytest

from research_platform.ingestion.generation_index import (
    GenerationIndexConfiguration,
    GenerationPoint,
    GenerationQdrantCollection,
    paper_point_id,
)
from research_platform.ingestion.indexing import IndexConfiguration
from research_platform.ingestion.paper_index import (
    PaperIndexInput,
    _paper_input,
    sync_papers,
)

CONFIGURATION = GenerationIndexConfiguration(
    passages_collection="test-passages",
    papers_collection="test-papers",
    embedding_model="model",
    embedding_revision="revision",
    preprocessing_revision="preprocessing",
    vector_size=2,
    distance="Cosine",
    batch_size=2,
    maximum_input_tokens=512,
)


def _paper(paper_id: str, title: str | None = "Title", abstract: str | None = None):
    return PaperIndexInput(paper_id, title, abstract, 2024, paper_id, None)


class _Repository:
    def __init__(self, papers: Sequence[PaperIndexInput], members: set[str]) -> None:
        self.papers = tuple(papers)
        self.members = frozenset(members)

    async def load_known_papers(self) -> tuple[PaperIndexInput, ...]:
        return self.papers

    async def snapshot_member_ids(self, snapshot_id: UUID) -> frozenset[str]:
        return self.members


class _Collection:
    def __init__(self) -> None:
        self.payloads: dict[UUID, dict[str, object]] = {}
        self.upserted: list[str] = []

    async def ensure_collection(self) -> None:
        return None

    async def ensure_payload_indexes(self) -> None:
        return None

    async def scroll_payloads(
        self, *, filter_: Mapping[str, object], fields: Sequence[str]
    ) -> tuple[Mapping[str, object], ...]:
        assert filter_ == {}
        return tuple(dict(payload) for payload in self.payloads.values())

    async def upsert(self, points: Sequence[GenerationPoint]) -> int:
        for point in points:
            self.payloads[point.point_id] = dict(point.payload)
            self.upserted.append(cast(str, point.payload["paper_id"]))
        return len(points)

    async def set_payload(
        self, point_ids: Sequence[UUID], payload: Mapping[str, object]
    ) -> None:
        for point_id in point_ids:
            self.payloads[point_id].update(payload)


class _Embedder:
    def __init__(self) -> None:
        self.texts: list[str] = []

    async def embed(
        self, texts: Sequence[str], *, configuration: IndexConfiguration
    ) -> Sequence[Sequence[float]]:
        self.texts.extend(texts)
        return [(1.0, 0.0) for _ in texts]


def _sync(
    repository: _Repository,
    collection: _Collection,
    embedder: _Embedder,
    generation: int = 1,
):
    return asyncio.run(
        sync_papers(
            repository=cast(Any, repository),
            papers=cast(GenerationQdrantCollection, collection),
            embedder=embedder,
            configuration=CONFIGURATION,
            generation=generation,
            snapshot_id=uuid4(),
        )
    )


def _payload(collection: _Collection, paper_id: str) -> dict[str, object]:
    return collection.payloads[paper_point_id(paper_id, CONFIGURATION.configuration_id)]


def test_payload_fields_and_status() -> None:
    collection = _Collection()
    report = _sync(
        _Repository([_paper("W1", abstract="An abstract"), _paper("W2")], {"W1"}),
        collection,
        _Embedder(),
    )

    assert (report.upserted_count, report.newly_indexed_count) == (2, 1)
    member = _payload(collection, "W1")
    assert member["catalog_status"] == "ingested"
    assert member["indexed_generation"] == 1
    assert member["abstract"] == "An abstract"
    other = _payload(collection, "W2")
    assert other["catalog_status"] == "metadata_only"
    assert "indexed_generation" not in other


def test_unchanged_papers_are_not_reembedded() -> None:
    collection, embedder = _Collection(), _Embedder()
    repository = _Repository([_paper("W1"), _paper("W2")], {"W1"})
    _sync(repository, collection, embedder)
    repository.papers = (_paper("W1"), _paper("W2", title="Changed"))
    report = _sync(repository, collection, embedder, generation=2)

    assert report.upserted_count == 1
    assert embedder.texts == ["Title", "Title", "Changed"]
    assert _payload(collection, "W1")["indexed_generation"] == 1


def test_members_get_indexed_generation_once() -> None:
    collection = _Collection()
    repository = _Repository([_paper("W1"), _paper("W2")], {"W1"})
    _sync(repository, collection, _Embedder())
    repository.members = frozenset({"W1", "W2"})
    report = _sync(repository, collection, _Embedder(), generation=2)

    assert report.newly_indexed_count == 1
    assert _payload(collection, "W1")["indexed_generation"] == 1
    assert _payload(collection, "W2")["indexed_generation"] == 2


def test_empty_text_is_skipped_and_member_without_text_fails() -> None:
    collection = _Collection()
    report = _sync(
        _Repository([_paper("W1"), _paper("W2", title=None)], {"W1"}),
        collection,
        _Embedder(),
    )
    assert report.skipped_without_text == 1
    with pytest.raises(ValueError, match="no paper text"):
        _sync(
            _Repository([_paper("W2", title=None)], {"W2"}), _Collection(), _Embedder()
        )


def test_json_text_metadata_is_decoded_for_the_abstract() -> None:
    row = {
        "paper_id": "W1",
        "title": "Title",
        "publication_year": 2023,
        "metadata": '{"abstract_inverted_index": {"Hello": [0], "world": [1]}}',
        "openalex_id": "W1",
        "doi": "10.1/x",
    }
    paper = _paper_input(row)
    assert paper.abstract == "Hello world"
    assert paper.index_text == "Title\n\nHello world"


class _PaperSparse:
    def __init__(self) -> None:
        self.texts: list[str] = []

    async def encode_papers(self, texts):
        from research_platform.ingestion.generation_index import SparseVector

        self.texts.extend(texts)
        return tuple((SparseVector((7,), (0.25,)), ("title",)) for _ in texts)


def test_paper_sparse_vectors_use_title_only() -> None:
    from research_platform.ingestion.generation_index import SparseLexicalSettings

    lexical = GenerationIndexConfiguration(
        **{
            **CONFIGURATION.__dict__,
            "lexical": SparseLexicalSettings(
                "scientific-en", "v1", "vocab", 1.5, 0.75, 3.0, 3.0
            ),
        }
    )
    collection, encoder = _Collection(), _PaperSparse()
    asyncio.run(
        sync_papers(
            repository=cast(
                Any, _Repository([_paper("W1", " Title ", "Abstract")], {"W1"})
            ),
            papers=cast(GenerationQdrantCollection, collection),
            embedder=_Embedder(),
            configuration=lexical,
            generation=1,
            snapshot_id=uuid4(),
            sparse_encoder=encoder,
        )
    )
    assert encoder.texts == ["Title"]
    payload = collection.payloads[paper_point_id("W1", lexical.configuration_id)]
    assert payload["lexical_terms"] == ["title"]
    with pytest.raises(ValueError, match="sparse encoder is required"):
        asyncio.run(
            sync_papers(
                repository=cast(Any, _Repository([], set())),
                papers=cast(GenerationQdrantCollection, _Collection()),
                embedder=_Embedder(),
                configuration=lexical,
                generation=1,
                snapshot_id=uuid4(),
            )
        )
