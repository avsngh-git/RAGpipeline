"""Regression coverage for Phase 2 cold model initialization."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Sequence

from research_platform.ingestion.embeddings import E5SmallV2Embedder
from research_platform.search.application import _warm_phase2_embedder


class _Tokenizer:
    def __call__(self, _text: str, **_options: object) -> dict[str, list[int]]:
        return {"input_ids": [101, 102]}


class _Model:
    tokenizer = _Tokenizer()

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def encode(self, texts: list[str], **_options: object) -> Sequence[Sequence[float]]:
        self.calls.append(texts)
        return [[1.0] + [0.0] * 383 for _ in texts]


class _DelayedLoadEmbedder(E5SmallV2Embedder):
    def __init__(self, model: _Model) -> None:
        super().__init__(query_timeout_seconds=0.01)
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


def test_startup_model_load_is_outside_normal_query_timeout() -> None:
    model = _Model()
    embedder = _DelayedLoadEmbedder(model)
    configuration = embedder.index_configuration()

    async def exercise() -> None:
        startup = asyncio.create_task(_warm_phase2_embedder(embedder, configuration))
        assert await asyncio.to_thread(embedder.load_started.wait, 1)
        await asyncio.sleep(0.05)
        embedder.release_load.set()
        await startup

    try:
        asyncio.run(exercise())
        assert len(model.calls) == 2
    finally:
        embedder.release_load.set()
        embedder.close()
