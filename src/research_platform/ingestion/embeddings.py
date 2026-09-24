"""Optional local E5 passage embeddings and matching chunk tokenizer."""

from __future__ import annotations

import asyncio
import importlib
import math
import threading
from collections.abc import Sequence
from typing import Any, Literal

from research_platform.ingestion.evidence import TokenSpan
from research_platform.ingestion.indexing import IndexConfiguration

E5_SMALL_V2_MODEL = "intfloat/e5-small-v2"
E5_SMALL_V2_REVISION = "e8b23a92af33fd81c865283d505f8f058a570cc8"
E5_SMALL_V2_DIMENSIONS = 384
E5_SMALL_V2_MAX_TOKENS = 512
E5_SMALL_V2_PREPROCESSING = "e5-small-v2:passage-prefix:mean-mask:l2-normalize:v1"


class EmbeddingModelError(RuntimeError):
    """A safe local embedding failure without model or source text details."""


class E5SmallV2Embedder:
    """Batch-embed searchable passages with the pinned English E5 model.

    The optional Sentence Transformers package and model weights load only when
    this adapter is used. Core CI and ingestion without indexing need neither.
    """

    def __init__(
        self,
        *,
        device: Literal["auto", "cpu", "cuda"] = "auto",
        model: Any | None = None,
    ) -> None:
        if device not in {"auto", "cpu", "cuda"}:
            raise ValueError("device must be auto, cpu or cuda")
        self.device = device
        self._model = model
        self._tokenizer = getattr(model, "tokenizer", None)
        self._model_lock = threading.Lock()
        self._tokenizer_lock = threading.Lock()

    @staticmethod
    def index_configuration(
        collection_name: str = "phase1-e5-small-v2",
        *,
        batch_size: int = 16,
    ) -> IndexConfiguration:
        """Return the model and preprocessing identity required by this adapter."""
        return IndexConfiguration(
            collection_name=collection_name,
            embedding_model=E5_SMALL_V2_MODEL,
            embedding_revision=E5_SMALL_V2_REVISION,
            preprocessing_revision=E5_SMALL_V2_PREPROCESSING,
            vector_size=E5_SMALL_V2_DIMENSIONS,
            distance="Cosine",
            batch_size=batch_size,
            maximum_input_tokens=E5_SMALL_V2_MAX_TOKENS,
        )

    async def embed(
        self,
        texts: Sequence[str],
        *,
        configuration: IndexConfiguration,
    ) -> Sequence[Sequence[float]]:
        self._validate_configuration(configuration)
        if any(not isinstance(text, str) or not text.strip() for text in texts):
            raise ValueError("embedding inputs must be non-empty strings")
        if not texts:
            return ()
        try:
            return await asyncio.to_thread(
                self._encode_passages, tuple(texts), configuration
            )
        except EmbeddingModelError:
            raise
        except Exception:
            raise EmbeddingModelError("local embedding inference failed") from None

    async def embed_query(
        self, text: str, *, configuration: IndexConfiguration
    ) -> Sequence[float]:
        """Embed one search query using the model's required query prefix."""
        self._validate_configuration(configuration)
        if not isinstance(text, str) or not text.strip():
            raise ValueError("query text must be non-empty")
        try:
            vectors = await asyncio.to_thread(
                self._encode_texts, (text,), "query: ", configuration
            )
            return vectors[0]
        except EmbeddingModelError:
            raise
        except Exception:
            raise EmbeddingModelError("local query embedding failed") from None

    def token_spans(self, text: str) -> Sequence[TokenSpan]:
        """Return E5 tokenizer offsets for section and table chunking."""
        if not isinstance(text, str):
            raise ValueError("tokenizer input must be text")
        try:
            tokenizer = self._ensure_tokenizer()
            encoded = tokenizer(
                text,
                add_special_tokens=False,
                truncation=False,
                return_offsets_mapping=True,
                verbose=False,
            )
            offsets = encoded["offset_mapping"]
            if offsets and isinstance(offsets[0], list):
                offsets = offsets[0]
            spans: list[TokenSpan] = []
            for offset in offsets:
                start, end = offset
                if end > start:
                    spans.append(TokenSpan(start=start, end=end))
            return tuple(spans)
        except EmbeddingModelError:
            raise
        except Exception:
            raise EmbeddingModelError("local model tokenizer failed") from None

    def _encode_passages(
        self,
        texts: Sequence[str],
        configuration: IndexConfiguration,
    ) -> tuple[tuple[float, ...], ...]:
        return self._encode_texts(texts, "passage: ", configuration)

    def _encode_texts(
        self,
        texts: Sequence[str],
        prefix: str,
        configuration: IndexConfiguration,
    ) -> tuple[tuple[float, ...], ...]:
        model = self._ensure_model()
        encoded = model.encode(
            [prefix + text for text in texts],
            batch_size=min(configuration.batch_size, len(texts)),
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        if hasattr(encoded, "tolist"):
            encoded = encoded.tolist()
        if not isinstance(encoded, list) or len(encoded) != len(texts):
            raise EmbeddingModelError("embedding model returned an invalid batch")
        vectors: list[tuple[float, ...]] = []
        for vector in encoded:
            if (
                not isinstance(vector, (list, tuple))
                or len(vector) != E5_SMALL_V2_DIMENSIONS
            ):
                raise EmbeddingModelError("embedding model returned an invalid vector")
            values = tuple(float(value) for value in vector)
            if not all(math.isfinite(value) for value in values):
                raise EmbeddingModelError("embedding model returned non-finite values")
            vectors.append(values)
        return tuple(vectors)

    def _ensure_tokenizer(self) -> Any:
        if self._tokenizer is not None:
            return self._tokenizer
        if self._model is not None:
            self._tokenizer = self._model.tokenizer
            return self._tokenizer
        with self._tokenizer_lock:
            if self._tokenizer is not None:
                return self._tokenizer
            try:
                transformers = importlib.import_module("transformers")
                auto_tokenizer = transformers.AutoTokenizer
            except (ImportError, AttributeError):
                raise EmbeddingModelError(
                    "install the optional embeddings dependency to tokenize evidence"
                ) from None
            try:
                tokenizer = auto_tokenizer.from_pretrained(
                    E5_SMALL_V2_MODEL,
                    revision=E5_SMALL_V2_REVISION,
                    use_fast=True,
                    trust_remote_code=False,
                )
            except Exception:
                raise EmbeddingModelError(
                    "pinned local embedding tokenizer could not be loaded"
                ) from None
            if not getattr(tokenizer, "is_fast", False):
                raise EmbeddingModelError("embedding tokenizer has no source offsets")
            self._tokenizer = tokenizer
            return tokenizer

    def _ensure_model(self) -> Any:
        if self._model is not None:
            return self._model
        with self._model_lock:
            if self._model is not None:
                return self._model
            try:
                torch = importlib.import_module("torch")
                sentence_transformers = importlib.import_module("sentence_transformers")
                sentence_transformer = sentence_transformers.SentenceTransformer
            except (ImportError, AttributeError):
                raise EmbeddingModelError(
                    "install the optional embeddings dependency to use local indexing"
                ) from None
            if self.device == "cuda" and not torch.cuda.is_available():
                raise EmbeddingModelError("CUDA was requested but is unavailable")
            device = self.device
            if device == "auto":
                device = "cuda" if torch.cuda.is_available() else "cpu"
            try:
                model = sentence_transformer(
                    E5_SMALL_V2_MODEL,
                    revision=E5_SMALL_V2_REVISION,
                    device=device,
                    trust_remote_code=False,
                )
                model.max_seq_length = E5_SMALL_V2_MAX_TOKENS
            except Exception:
                raise EmbeddingModelError(
                    "pinned local embedding model could not be loaded"
                ) from None
            self._model = model
            self._tokenizer = model.tokenizer
            return model

    @staticmethod
    def _validate_configuration(configuration: IndexConfiguration) -> None:
        if (
            configuration.embedding_model != E5_SMALL_V2_MODEL
            or configuration.embedding_revision != E5_SMALL_V2_REVISION
            or configuration.preprocessing_revision != E5_SMALL_V2_PREPROCESSING
            or configuration.vector_size != E5_SMALL_V2_DIMENSIONS
            or configuration.distance != "Cosine"
            or configuration.maximum_input_tokens != E5_SMALL_V2_MAX_TOKENS
        ):
            raise ValueError("index configuration does not match the pinned E5 model")
