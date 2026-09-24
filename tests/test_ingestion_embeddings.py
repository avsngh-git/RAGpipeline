"""Tests for the optional pinned E5 passage embedder."""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from research_platform.ingestion.embeddings import (
    E5_SMALL_V2_MODEL,
    E5_SMALL_V2_PREPROCESSING,
    E5_SMALL_V2_REVISION,
    E5SmallV2Embedder,
)
from research_platform.ingestion.evidence import TokenSpan
from research_platform.ingestion.indexing import IndexConfiguration


class _FakeTokenizer:
    def __call__(self, text: str, **_options: object) -> dict[str, object]:
        spans: list[tuple[int, int]] = []
        start: int | None = None
        for index, character in enumerate(text):
            if character.isspace():
                if start is not None:
                    spans.append((start, index))
                    start = None
            elif start is None:
                start = index
        if start is not None:
            spans.append((start, len(text)))
        return {"offset_mapping": spans}


class _FakeModel:
    tokenizer = _FakeTokenizer()

    def __init__(self) -> None:
        self.calls: list[tuple[list[str], dict[str, object]]] = []

    def encode(self, texts: list[str], **options: object) -> Sequence[Sequence[float]]:
        self.calls.append((texts, options))
        return [list(1.0 if index == 0 else 0.0 for index in range(384)) for _ in texts]


def test_e5_embedder_prepends_passage_and_returns_normalized_dimension() -> None:
    model = _FakeModel()
    embedder = E5SmallV2Embedder(model=model)
    config = embedder.index_configuration(batch_size=4)

    import asyncio

    vectors = asyncio.run(
        embedder.embed(("paper evidence", "table values"), configuration=config)
    )

    assert len(vectors) == 2
    assert len(vectors[0]) == 384
    assert model.calls == [
        (
            ["passage: paper evidence", "passage: table values"],
            {
                "batch_size": 2,
                "convert_to_numpy": True,
                "normalize_embeddings": True,
                "show_progress_bar": False,
            },
        )
    ]


def test_e5_query_uses_query_prefix() -> None:
    model = _FakeModel()
    embedder = E5SmallV2Embedder(model=model)
    config = embedder.index_configuration()

    import asyncio

    vector = asyncio.run(embedder.embed_query("retrieval query", configuration=config))

    assert len(vector) == 384
    assert model.calls[0][0] == ["query: retrieval query"]
    assert model.calls[0][1]["normalize_embeddings"] is True


def test_e5_tokenizer_offsets_are_reusable_for_source_chunks() -> None:
    embedder = E5SmallV2Embedder(model=_FakeModel())

    assert embedder.token_spans("alpha beta") == (
        TokenSpan(0, 5),
        TokenSpan(6, 10),
    )


def test_e5_embedder_rejects_a_different_index_identity() -> None:
    embedder = E5SmallV2Embedder(model=_FakeModel())
    compatible = embedder.index_configuration()
    incompatible = IndexConfiguration.from_dict(
        {**compatible.to_dict(), "embedding_model": "other/model"}
    )
    import asyncio

    with pytest.raises(ValueError, match="does not match"):
        asyncio.run(embedder.embed(("text",), configuration=incompatible))


def test_e5_model_identity_is_pinned_and_uses_retrieval_preprocessing() -> None:
    config = E5SmallV2Embedder.index_configuration()

    assert config.embedding_model == E5_SMALL_V2_MODEL
    assert config.embedding_revision == E5_SMALL_V2_REVISION
    assert config.preprocessing_revision == E5_SMALL_V2_PREPROCESSING
    assert config.vector_size == 384
    assert config.maximum_input_tokens == 512
