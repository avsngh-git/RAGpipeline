"""Tests for the optional pinned E5 passage embedder."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Sequence

import pytest

from research_platform.ingestion.embeddings import (
    BGE_BASE_EN_V1_5_MODEL,
    BGE_BASE_EN_V1_5_PREPROCESSING,
    BGE_BASE_EN_V1_5_QUERY_PREFIX,
    BGE_BASE_EN_V1_5_REVISION,
    E5_SMALL_V2_MODEL,
    E5_SMALL_V2_PREPROCESSING,
    E5_SMALL_V2_REVISION,
    GTE_MODERNBERT_BASE_MODEL,
    GTE_MODERNBERT_BASE_PREPROCESSING,
    GTE_MODERNBERT_BASE_REVISION,
    BGEBaseEnV15Embedder,
    E5SmallV2Embedder,
    EmbeddingInferenceBusy,
    EmbeddingInferenceTimeout,
    EmbeddingModelError,
    GTEModernBertBaseEmbedder,
    create_embedder_for_configuration,
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
        return {"offset_mapping": spans, "input_ids": [101, *range(len(spans)), 102]}


class _FakeModel:
    tokenizer = _FakeTokenizer()

    def __init__(self, dimensions: int = 384) -> None:
        self.dimensions = dimensions
        self.calls: list[tuple[list[str], dict[str, object]]] = []

    def encode(self, texts: list[str], **options: object) -> Sequence[Sequence[float]]:
        self.calls.append((texts, options))
        return [
            [1.0 if index == 0 else 0.0 for index in range(self.dimensions)]
            for _ in texts
        ]


class _BlockingModel(_FakeModel):
    def __init__(self) -> None:
        super().__init__()
        self.started = threading.Event()
        self.release = threading.Event()
        self.finished = threading.Event()
        self._active_lock = threading.Lock()
        self._active = 0
        self.maximum_active = 0

    def encode(self, texts: list[str], **options: object) -> Sequence[Sequence[float]]:
        with self._active_lock:
            self._active += 1
            self.maximum_active = max(self.maximum_active, self._active)
        self.started.set()
        try:
            if not self.release.wait(timeout=2):
                raise TimeoutError("test encoder release was not signaled")
            return super().encode(texts, **options)
        finally:
            with self._active_lock:
                self._active -= 1
            self.finished.set()


class _SlowLoadingEmbedder(E5SmallV2Embedder):
    def __init__(self, model: _FakeModel) -> None:
        super().__init__()
        self._fixture_model = model
        self.load_started = threading.Event()
        self.release_load = threading.Event()

    def _ensure_model(self):
        if self._model is not None:
            return self._model
        with self._model_lock:
            if self._model is None:
                self.load_started.set()
                if not self.release_load.wait(timeout=2):
                    raise TimeoutError("test model-load release was not signaled")
                self._model = self._fixture_model
                self._tokenizer = self._fixture_model.tokenizer
        return self._model


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
    embedder.close()


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


def test_bge_passages_are_unprefixed_and_use_the_pinned_768_dim_profile() -> None:
    model = _FakeModel(dimensions=768)
    embedder = BGEBaseEnV15Embedder(model=model)
    config = embedder.index_configuration()

    import asyncio

    vectors = asyncio.run(
        embedder.embed(("prose evidence", "| table | result |"), configuration=config)
    )

    assert len(vectors) == 2
    assert all(len(vector) == 768 for vector in vectors)
    assert config.embedding_model == BGE_BASE_EN_V1_5_MODEL
    assert config.embedding_revision == BGE_BASE_EN_V1_5_REVISION
    assert config.preprocessing_revision == BGE_BASE_EN_V1_5_PREPROCESSING
    assert (
        config.collection_name
        != E5SmallV2Embedder.index_configuration().collection_name
    )
    assert config.batch_size == 4
    assert model.calls[0][0] == ["prose evidence", "| table | result |"]
    assert model.calls[0][1]["normalize_embeddings"] is True


def test_bge_query_uses_the_exact_retrieval_instruction() -> None:
    model = _FakeModel(dimensions=768)
    embedder = BGEBaseEnV15Embedder(model=model)
    config = embedder.index_configuration()

    import asyncio

    vector = asyncio.run(embedder.embed_query("retrieval query", configuration=config))

    assert len(vector) == 768
    assert model.calls[0][0] == [BGE_BASE_EN_V1_5_QUERY_PREFIX + "retrieval query"]
    assert model.calls[0][1]["normalize_embeddings"] is True
    embedder.close()


def test_bge_embedder_rejects_mismatched_profile_and_overlong_passage() -> None:
    model = _FakeModel(dimensions=768)
    embedder = BGEBaseEnV15Embedder(model=model)
    config = embedder.index_configuration()
    incompatible = IndexConfiguration.from_dict(
        {**config.to_dict(), "embedding_revision": "unreviewed-revision"}
    )

    import asyncio

    with pytest.raises(ValueError, match="pinned BGE-base-en-v1.5"):
        asyncio.run(embedder.embed(("evidence",), configuration=incompatible))
    with pytest.raises(EmbeddingModelError, match="token limit"):
        asyncio.run(embedder.embed(("token " * 511,), configuration=config))
    assert model.calls == []


def test_gte_modernbert_is_unprefixed_8192_token_dev_profile() -> None:
    import asyncio

    model = _FakeModel(dimensions=768)
    embedder = GTEModernBertBaseEmbedder(model=model)
    config = embedder.index_configuration()

    asyncio.run(embedder.embed(("passage text",), configuration=config))
    asyncio.run(embedder.embed_query("a query", configuration=config))

    assert config.embedding_model == GTE_MODERNBERT_BASE_MODEL
    assert config.embedding_revision == GTE_MODERNBERT_BASE_REVISION
    assert config.preprocessing_revision == GTE_MODERNBERT_BASE_PREPROCESSING
    assert (config.vector_size, config.maximum_input_tokens) == (768, 8192)
    assert config.collection_name == "phase2-dev-gte-modernbert-base-v1"
    assert model.calls[0][0] == ["passage text"]
    assert model.calls[1][0] == ["a query"]
    assert isinstance(
        create_embedder_for_configuration(config), GTEModernBertBaseEmbedder
    )
    embedder.close()


def test_fp16_embedding_requires_cuda_and_valid_precision() -> None:
    with pytest.raises(ValueError, match="precision"):
        GTEModernBertBaseEmbedder(precision="int8")  # type: ignore[arg-type]
    assert (
        GTEModernBertBaseEmbedder(model=_FakeModel(768), precision="fp16").precision
        == "fp16"
    )


def test_configuration_factory_selects_only_a_pinned_local_adapter() -> None:
    bge_config = BGEBaseEnV15Embedder.index_configuration()
    e5_config = E5SmallV2Embedder.index_configuration()

    assert isinstance(
        create_embedder_for_configuration(bge_config), BGEBaseEnV15Embedder
    )
    assert isinstance(create_embedder_for_configuration(e5_config), E5SmallV2Embedder)
    unsupported = IndexConfiguration.from_dict(
        {**bge_config.to_dict(), "embedding_revision": "unknown"}
    )
    with pytest.raises(ValueError, match="pinned E5-small-v2, BGE"):
        create_embedder_for_configuration(unsupported)


def test_cancelled_query_keeps_single_worker_capacity_until_inference_finishes() -> (
    None
):
    model = _BlockingModel()
    embedder = E5SmallV2Embedder(model=model, query_timeout_seconds=1.0)
    config = embedder.index_configuration()

    async def exercise() -> None:
        request = asyncio.create_task(
            embedder.embed_query("blocked query", configuration=config)
        )
        assert await asyncio.to_thread(model.started.wait, 1)
        request.cancel()
        with pytest.raises(asyncio.CancelledError):
            await request

        for _ in range(8):
            with pytest.raises(EmbeddingInferenceBusy):
                await embedder.embed_query("another query", configuration=config)
        assert model.maximum_active == 1

        model.release.set()
        assert await asyncio.to_thread(model.finished.wait, 1)
        vector = await embedder.embed_query("after completion", configuration=config)
        assert len(vector) == 384

    try:
        asyncio.run(exercise())
    finally:
        model.release.set()
        embedder.close()
    assert model.maximum_active == 1


def test_query_timeout_does_not_free_worker_until_encoder_completes() -> None:
    model = _BlockingModel()
    embedder = E5SmallV2Embedder(model=model, query_timeout_seconds=0.01)
    config = embedder.index_configuration()

    async def exercise() -> None:
        request = asyncio.create_task(
            embedder.embed_query("slow query", configuration=config)
        )
        assert await asyncio.to_thread(model.started.wait, 1)
        with pytest.raises(EmbeddingInferenceTimeout):
            await request
        with pytest.raises(EmbeddingInferenceBusy):
            await embedder.embed_query("queued query", configuration=config)
        model.release.set()
        assert await asyncio.to_thread(model.finished.wait, 1)
        assert (
            len(await embedder.embed_query("recovered query", configuration=config))
            == 384
        )

    try:
        asyncio.run(exercise())
    finally:
        model.release.set()
        embedder.close()


def test_slow_model_load_occupies_bounded_query_worker() -> None:
    model = _FakeModel()
    embedder = _SlowLoadingEmbedder(model)
    config = embedder.index_configuration()

    async def exercise() -> None:
        startup_probe = asyncio.create_task(
            embedder.embed_query("readiness probe", configuration=config)
        )
        assert await asyncio.to_thread(embedder.load_started.wait, 1)
        with pytest.raises(EmbeddingInferenceBusy):
            await embedder.embed_query("concurrent search", configuration=config)
        embedder.release_load.set()
        assert len(await startup_probe) == 384
        assert (
            len(await embedder.embed_query("subsequent search", configuration=config))
            == 384
        )

    try:
        asyncio.run(exercise())
    finally:
        embedder.release_load.set()
        embedder.close()
