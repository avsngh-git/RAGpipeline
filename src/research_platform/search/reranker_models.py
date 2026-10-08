"""Offline, revision-pinned Sentence Transformers cross-encoder adapters."""

from __future__ import annotations

import importlib
from collections.abc import Sequence
from numbers import Real
from pathlib import Path
from typing import Any, Literal

from research_platform.search.profiles import RerankerIdentity
from research_platform.search.reranker import (
    RerankerAdapterError,
    RerankerDeviceExhausted,
    RerankerDeviceUnavailable,
    RerankerInferenceFailure,
    RerankerInvalidScoreError,
    RerankerModelLoadFailure,
    RerankerOutputAlignmentError,
    RerankerRuntimeUnavailable,
)
from research_platform.search.reranker_pairs import RERANKER_PAIR_FORMAT_ID

MINILM_RERANKER_MODEL = "cross-encoder/ms-marco-MiniLM-L6-v2"
MINILM_RERANKER_REVISION = "233902d25c440f23af6f7d6e94d2946bac0bee0a"
BGE_RERANKER_MODEL = "BAAI/bge-reranker-base"
BGE_RERANKER_REVISION = "2cfc18c9415c912f9d8155881c133215df768a70"
# Development-only candidate (not part of any frozen or active profile). Model
# card: Apache-2.0, ModernBERT, 7,999-token maximum, raw pair input, no prefix.
ETTIN_RERANKER_150M_MODEL = "cross-encoder/ettin-reranker-150m-v1"
ETTIN_RERANKER_150M_REVISION = "025501c4e0f9bbeb4c5b198318e0089ff061cc14"
ETTIN_RERANKER_MAXIMUM_INPUT_TOKENS = 7999
RERANKER_MAXIMUM_INPUT_TOKENS = 512
SUPPORTED_RERANKERS = {
    MINILM_RERANKER_MODEL: MINILM_RERANKER_REVISION,
    BGE_RERANKER_MODEL: BGE_RERANKER_REVISION,
    ETTIN_RERANKER_150M_MODEL: ETTIN_RERANKER_150M_REVISION,
}
RerankerDevice = Literal["auto", "cpu", "cuda"]


class PinnedSentenceTransformersReranker:
    """Lazy local-only tokenizer/scorer for the approved P2-10 candidate models.

    Weights must already be present in the Hugging Face cache (or ``cache_folder``).
    Loading never downloads files, permits Hub code, adds a query prefix, or applies
    a score activation/softmax.
    """

    def __init__(
        self,
        identity: RerankerIdentity,
        *,
        device: RerankerDevice = "auto",
        cache_folder: str | Path | None = None,
    ) -> None:
        validate_supported_reranker_identity(identity)
        if device not in {"auto", "cpu", "cuda"}:
            raise ValueError("device must be auto, cpu or cuda")
        if cache_folder is not None and (
            not isinstance(cache_folder, (str, Path)) or not str(cache_folder).strip()
        ):
            raise ValueError("cache_folder must be a non-empty path or null")
        self.identity = identity
        self.device = device
        self.cache_folder = cache_folder
        self._model: Any | None = None
        self._tokenizer: Any | None = None
        self._torch: Any | None = None

    def count_pair(self, query: str, evidence_text: str) -> int:
        """Count the complete model pair with special tokens and no truncation."""
        if not isinstance(query, str) or not isinstance(evidence_text, str):
            raise ValueError("pair inputs must be text")
        self._ensure_loaded()
        assert self._tokenizer is not None
        try:
            encoded = self._tokenizer(
                query, evidence_text, add_special_tokens=True, truncation=False
            )
            input_ids = encoded["input_ids"]
            if input_ids and isinstance(input_ids[0], (list, tuple)):
                if len(input_ids) != 1:
                    raise ValueError("one pair produced multiple token rows")
                input_ids = input_ids[0]
            return len(input_ids)
        except RerankerAdapterError:
            raise
        except Exception:
            raise RerankerModelLoadFailure(
                "pinned reranker tokenizer could not count a complete pair"
            ) from None

    def score_pairs(self, pairs: Sequence[tuple[str, str]]) -> tuple[float, ...]:
        """Return the pinned model's raw, unactivated scalar logit for each pair."""
        if not pairs:
            return ()
        self._ensure_loaded()
        assert self._model is not None
        try:
            output = self._model.predict(
                list(pairs),
                batch_size=len(pairs),
                show_progress_bar=False,
                activation_fn=_identity_activation,
                apply_softmax=False,
                convert_to_numpy=True,
            )
        except Exception as error:
            _raise_model_error(error, self._torch, during_load=False)
        if hasattr(output, "tolist"):
            output = output.tolist()
        if isinstance(output, (str, bytes)) or not isinstance(output, Sequence):
            raise RerankerOutputAlignmentError(
                "pinned reranker returned a non-sequence score result"
            )
        scores: list[float] = []
        for output_value in output:
            if isinstance(output_value, (list, tuple)):
                if len(output_value) != 1:
                    raise RerankerInvalidScoreError(
                        "pinned reranker returned a non-scalar result"
                    )
                output_value = output_value[0]
            if isinstance(output_value, bool) or not isinstance(output_value, Real):
                raise RerankerInvalidScoreError(
                    "pinned reranker returned a non-numeric result"
                )
            scores.append(float(output_value))
        return tuple(scores)

    def _ensure_loaded(self) -> None:
        if self._model is not None and self._tokenizer is not None:
            return
        try:
            torch = importlib.import_module("torch")
            transformers = importlib.import_module("transformers")
            sentence_transformers = importlib.import_module("sentence_transformers")
            tokenizer_factory = transformers.AutoTokenizer
            cross_encoder_factory = sentence_transformers.CrossEncoder
        except (ImportError, AttributeError):
            raise RerankerRuntimeUnavailable(
                "install the optional sentence-transformers inference dependency"
            ) from None

        device = self._resolve_device(torch)
        cache_folder = str(self.cache_folder) if self.cache_folder is not None else None
        try:
            tokenizer = tokenizer_factory.from_pretrained(
                self.identity.model,
                revision=self.identity.revision,
                cache_dir=cache_folder,
                local_files_only=True,
                trust_remote_code=False,
                use_fast=True,
            )
            if not getattr(tokenizer, "is_fast", False):
                raise ValueError("pinned tokenizer is not a fast tokenizer")
            model = cross_encoder_factory(
                model_name_or_path=self.identity.model,
                revision=self.identity.revision,
                cache_folder=cache_folder,
                local_files_only=True,
                trust_remote_code=False,
                device=device,
                max_length=self.identity.maximum_input_tokens,
                model_kwargs={
                    "dtype": getattr(
                        torch,
                        {"fp32": "float32", "fp16": "float16", "bf16": "bfloat16"}[
                            self.identity.precision
                        ],
                    )
                },
            )
        except Exception as error:
            _raise_model_error(error, torch, during_load=True)
        self._torch = torch
        self._tokenizer = tokenizer
        self._model = model

    def _resolve_device(self, torch: Any) -> str:
        cuda_available = bool(torch.cuda.is_available())
        if self.device == "cuda" and not cuda_available:
            raise RerankerDeviceUnavailable(
                "CUDA was requested but is unavailable in this runtime"
            )
        device = (
            "cuda"
            if self.device == "auto" and cuda_available
            else ("cpu" if self.device == "auto" else self.device)
        )
        if device == "cpu" and self.identity.precision != "fp32":
            # Half precision is a GPU speed setting; the frozen profile was measured
            # on CUDA. Refusing here lets search fall back to the unchanged hybrid
            # order instead of reranking with a different numeric path.
            raise RerankerDeviceUnavailable(
                f"{self.identity.precision} reranking requires CUDA"
            )
        return device


def validate_supported_reranker_identity(identity: RerankerIdentity) -> None:
    """Allow only the two exact P2-10.1 candidates and frozen raw pair format."""
    if not isinstance(identity, RerankerIdentity):
        raise ValueError("identity must be a RerankerIdentity")
    if SUPPORTED_RERANKERS.get(identity.model) != identity.revision:
        raise ValueError("reranker model and revision are not in the P2-10 shortlist")
    if identity.preprocessing_revision != RERANKER_PAIR_FORMAT_ID:
        raise ValueError("unsupported reranker pair preprocessing revision")
    if identity.model == ETTIN_RERANKER_150M_MODEL:
        if not 0 < identity.maximum_input_tokens <= ETTIN_RERANKER_MAXIMUM_INPUT_TOKENS:
            raise ValueError("Ettin pair budget must be within 1 and 7999 tokens")
    elif identity.maximum_input_tokens != RERANKER_MAXIMUM_INPUT_TOKENS:
        raise ValueError("supported rerankers use a 512-token pair budget")


def _identity_activation(logits: Any) -> Any:
    """Return logits unchanged so raw model scores remain uncalibrated ranking values."""
    return logits


def _raise_model_error(error: Exception, torch: Any, *, during_load: bool) -> None:
    if _is_device_exhaustion(error, torch):
        raise RerankerDeviceExhausted(
            "reranker device could not allocate model or inference memory"
        ) from None
    if during_load:
        raise RerankerModelLoadFailure(
            "pinned reranker weights are missing or could not be loaded locally"
        ) from None
    raise RerankerInferenceFailure("pinned reranker inference failed") from None


def _is_device_exhaustion(error: Exception, torch: Any) -> bool:
    if isinstance(error, MemoryError) or "out of memory" in str(error).casefold():
        return True
    exception_types: list[type[BaseException]] = []
    for parent in (torch, getattr(torch, "cuda", None)):
        exception_type = getattr(parent, "OutOfMemoryError", None)
        if isinstance(exception_type, type) and issubclass(
            exception_type, BaseException
        ):
            exception_types.append(exception_type)
    return bool(exception_types) and isinstance(error, tuple(exception_types))
