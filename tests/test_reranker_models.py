"""Offline loading and error classification for pinned cross-encoder models."""

from types import SimpleNamespace
from typing import Any

import pytest

import research_platform.search.reranker_models as reranker_models
from research_platform.search.profiles import RerankerIdentity
from research_platform.search.reranker import (
    RerankerDeviceExhausted,
    RerankerDeviceUnavailable,
    RerankerInvalidScoreError,
    RerankerModelLoadFailure,
)
from research_platform.search.reranker_models import (
    MINILM_RERANKER_MODEL,
    MINILM_RERANKER_REVISION,
    PinnedSentenceTransformersReranker,
)


class FakeTokenizer:
    is_fast = True

    def __init__(self) -> None:
        self.calls: list[tuple[tuple[Any, ...], dict[str, object]]] = []

    def __call__(self, *args: Any, **kwargs: object) -> dict[str, list[int]]:
        self.calls.append((args, kwargs))
        return {"input_ids": [101, 11, 102, 12, 102]}


class FakeArray:
    def __init__(self, values: list[float]) -> None:
        self.values = values

    def tolist(self) -> list[float]:
        return self.values


class FakeModel:
    def __init__(self) -> None:
        self.calls: list[tuple[list[tuple[str, str]], dict[str, object]]] = []
        self.error: Exception | None = None
        self.output: FakeArray | None = None

    def predict(self, pairs: list[tuple[str, str]], **kwargs: object) -> FakeArray:
        self.calls.append((pairs, kwargs))
        if self.error is not None:
            raise self.error
        return self.output or FakeArray([3.25] * len(pairs))


def _identity() -> RerankerIdentity:
    return RerankerIdentity(
        model=MINILM_RERANKER_MODEL,
        revision=MINILM_RERANKER_REVISION,
        preprocessing_revision="query-source-chunk-v1",
        maximum_input_tokens=512,
    )


def _mock_libraries(
    monkeypatch: pytest.MonkeyPatch,
    *,
    tokenizer: FakeTokenizer,
    model: FakeModel,
    cuda_available: bool = False,
    model_load_error: Exception | None = None,
) -> tuple[dict[str, object], dict[str, object]]:
    calls: dict[str, object] = {}
    torch = SimpleNamespace(
        float32=object(), cuda=SimpleNamespace(is_available=lambda: cuda_available)
    )

    class AutoTokenizer:
        @staticmethod
        def from_pretrained(model_name: str, **kwargs: object) -> FakeTokenizer:
            calls["tokenizer_model"] = model_name
            calls["tokenizer_kwargs"] = kwargs
            return tokenizer

    def load_cross_encoder(**kwargs: object) -> FakeModel:
        calls["model_kwargs"] = kwargs
        if model_load_error is not None:
            raise model_load_error
        return model

    packages = {
        "torch": torch,
        "transformers": SimpleNamespace(AutoTokenizer=AutoTokenizer),
        "sentence_transformers": SimpleNamespace(CrossEncoder=load_cross_encoder),
    }
    monkeypatch.setattr(
        reranker_models.importlib,
        "import_module",
        lambda name: packages[name],
    )
    return calls, {"torch": torch}


def test_pinned_loader_is_offline_revision_pinned_and_returns_raw_logits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tokenizer = FakeTokenizer()
    model = FakeModel()
    calls, dependencies = _mock_libraries(monkeypatch, tokenizer=tokenizer, model=model)
    scorer = PinnedSentenceTransformersReranker(
        _identity(), device="cpu", cache_folder="/tmp/pinned-cache"
    )

    assert scorer.count_pair("exact query", "stored evidence") == 5
    scores = scorer.score_pairs((("exact query", "stored evidence"),))

    assert scores == (3.25,)
    assert calls["tokenizer_model"] == MINILM_RERANKER_MODEL
    tokenizer_kwargs = calls["tokenizer_kwargs"]
    assert tokenizer_kwargs == {
        "revision": MINILM_RERANKER_REVISION,
        "cache_dir": "/tmp/pinned-cache",
        "local_files_only": True,
        "trust_remote_code": False,
        "use_fast": True,
    }
    assert tokenizer.calls == [
        (
            ("exact query", "stored evidence"),
            {"add_special_tokens": True, "truncation": False},
        )
    ]
    model_kwargs = calls["model_kwargs"]
    assert model_kwargs["model_name_or_path"] == MINILM_RERANKER_MODEL
    assert model_kwargs["revision"] == MINILM_RERANKER_REVISION
    assert model_kwargs["local_files_only"] is True
    assert model_kwargs["trust_remote_code"] is False
    assert model_kwargs["max_length"] == 512
    assert model_kwargs["device"] == "cpu"
    assert model_kwargs["model_kwargs"] == {
        "torch_dtype": dependencies["torch"].float32
    }
    pairs, predict_kwargs = model.calls[0]
    assert pairs == [("exact query", "stored evidence")]
    assert predict_kwargs["batch_size"] == 1
    assert predict_kwargs["apply_softmax"] is False
    assert predict_kwargs["show_progress_bar"] is False
    assert predict_kwargs["activation_fn"]("raw logits") == "raw logits"


def test_only_reviewed_model_revisions_are_accepted() -> None:
    identity = _identity()
    with pytest.raises(ValueError, match="not in the P2-10 shortlist"):
        PinnedSentenceTransformersReranker(
            RerankerIdentity(
                model=identity.model,
                revision="main",
                preprocessing_revision=identity.preprocessing_revision,
                maximum_input_tokens=identity.maximum_input_tokens,
            )
        )


def test_missing_local_weights_are_a_safe_controlled_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls, _dependencies = _mock_libraries(
        monkeypatch,
        tokenizer=FakeTokenizer(),
        model=FakeModel(),
        model_load_error=OSError("private cache path and source details"),
    )
    scorer = PinnedSentenceTransformersReranker(_identity(), device="cpu")

    with pytest.raises(RerankerModelLoadFailure) as error:
        scorer.count_pair("query", "evidence")

    assert "private cache path" not in str(error.value)
    assert calls["model_kwargs"]["local_files_only"] is True


def test_requested_cuda_without_a_visible_device_is_controlled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_libraries(
        monkeypatch,
        tokenizer=FakeTokenizer(),
        model=FakeModel(),
        cuda_available=False,
    )
    scorer = PinnedSentenceTransformersReranker(_identity(), device="cuda")

    with pytest.raises(RerankerDeviceUnavailable):
        scorer.count_pair("query", "evidence")


def test_device_memory_exhaustion_is_classified_without_leaking_backend_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tokenizer = FakeTokenizer()
    model = FakeModel()
    model.error = RuntimeError("CUDA out of memory; private tensor details")
    _mock_libraries(
        monkeypatch=monkeypatch,
        tokenizer=tokenizer,
        model=model,
    )
    scorer = PinnedSentenceTransformersReranker(_identity(), device="cpu")

    with pytest.raises(RerankerDeviceExhausted) as error:
        scorer.score_pairs((("query", "evidence"),))

    assert "private tensor details" not in str(error.value)


def test_non_scalar_model_output_is_a_controlled_invalid_score(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tokenizer = FakeTokenizer()
    model = FakeModel()
    model.output = FakeArray([[0.4, 0.6]])  # type: ignore[arg-type]
    _mock_libraries(monkeypatch, tokenizer=tokenizer, model=model)
    scorer = PinnedSentenceTransformersReranker(_identity(), device="cpu")

    with pytest.raises(RerankerInvalidScoreError):
        scorer.score_pairs((("query", "evidence"),))
