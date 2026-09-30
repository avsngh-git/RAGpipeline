"""Optional local, revision-pinned sentence embedding adapters."""

from __future__ import annotations

import asyncio
import importlib
import math
import threading
from collections.abc import Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, ClassVar, Literal

from research_platform.ingestion.evidence import TokenSpan
from research_platform.ingestion.indexing import IndexConfiguration

E5_SMALL_V2_MODEL = "intfloat/e5-small-v2"
E5_SMALL_V2_REVISION = "e8b23a92af33fd81c865283d505f8f058a570cc8"
E5_SMALL_V2_DIMENSIONS = 384
E5_SMALL_V2_MAX_TOKENS = 512
E5_SMALL_V2_PREPROCESSING = "e5-small-v2:passage-prefix:mean-mask:l2-normalize:v1"

BGE_BASE_EN_V1_5_MODEL = "BAAI/bge-base-en-v1.5"
BGE_BASE_EN_V1_5_REVISION = "a5beb1e3e68b9ab74eb54cfd186867f64f240e1a"
BGE_BASE_EN_V1_5_DIMENSIONS = 768
BGE_BASE_EN_V1_5_MAX_TOKENS = 512
BGE_BASE_EN_V1_5_PREPROCESSING = (
    "bge-base-en-v1.5:query-instruction:cls-pooling:l2-normalize:v1"
)
BGE_BASE_EN_V1_5_QUERY_PREFIX = (
    "Represent this sentence for searching relevant passages: "
)

GTE_MODERNBERT_BASE_MODEL = "Alibaba-NLP/gte-modernbert-base"
GTE_MODERNBERT_BASE_REVISION = "e7f32e3c00f91d699e8c43b53106206bcc72bb22"
GTE_MODERNBERT_BASE_DIMENSIONS = 768
GTE_MODERNBERT_BASE_MAX_TOKENS = 8192
GTE_MODERNBERT_BASE_PREPROCESSING = (
    "gte-modernbert-base:no-prefix:cls-pooling:l2-normalize:v1"
)

EmbeddingDevice = Literal["auto", "cpu", "cuda"]
EmbeddingPrecision = Literal["fp32", "fp16"]


@dataclass(frozen=True)
class _EmbeddingProfile:
    """Model identity and formatting that determine one local embedding space."""

    model: str
    revision: str
    preprocessing_revision: str
    dimensions: int
    maximum_input_tokens: int
    passage_prefix: str
    query_prefix: str
    display_name: str
    collection_name: str
    batch_size: int

    def matches(self, configuration: IndexConfiguration) -> bool:
        return (
            configuration.embedding_model == self.model
            and configuration.embedding_revision == self.revision
            and configuration.preprocessing_revision == self.preprocessing_revision
            and configuration.vector_size == self.dimensions
            and configuration.distance == "Cosine"
            and configuration.maximum_input_tokens == self.maximum_input_tokens
        )

    def index_configuration(
        self,
        *,
        collection_name: str | None = None,
        batch_size: int | None = None,
    ) -> IndexConfiguration:
        return IndexConfiguration(
            collection_name=(
                self.collection_name if collection_name is None else collection_name
            ),
            embedding_model=self.model,
            embedding_revision=self.revision,
            preprocessing_revision=self.preprocessing_revision,
            vector_size=self.dimensions,
            distance="Cosine",
            batch_size=self.batch_size if batch_size is None else batch_size,
            maximum_input_tokens=self.maximum_input_tokens,
        )


_E5_PROFILE = _EmbeddingProfile(
    model=E5_SMALL_V2_MODEL,
    revision=E5_SMALL_V2_REVISION,
    preprocessing_revision=E5_SMALL_V2_PREPROCESSING,
    dimensions=E5_SMALL_V2_DIMENSIONS,
    maximum_input_tokens=E5_SMALL_V2_MAX_TOKENS,
    passage_prefix="passage: ",
    query_prefix="query: ",
    display_name="E5-small-v2",
    collection_name="phase1-e5-small-v2",
    batch_size=16,
)
_BGE_PROFILE = _EmbeddingProfile(
    model=BGE_BASE_EN_V1_5_MODEL,
    revision=BGE_BASE_EN_V1_5_REVISION,
    preprocessing_revision=BGE_BASE_EN_V1_5_PREPROCESSING,
    dimensions=BGE_BASE_EN_V1_5_DIMENSIONS,
    maximum_input_tokens=BGE_BASE_EN_V1_5_MAX_TOKENS,
    passage_prefix="",
    query_prefix=BGE_BASE_EN_V1_5_QUERY_PREFIX,
    display_name="BGE-base-en-v1.5",
    collection_name="phase2-bge-base-en-v1-5",
    batch_size=4,
)
_GTE_PROFILE = _EmbeddingProfile(
    model=GTE_MODERNBERT_BASE_MODEL,
    revision=GTE_MODERNBERT_BASE_REVISION,
    preprocessing_revision=GTE_MODERNBERT_BASE_PREPROCESSING,
    dimensions=GTE_MODERNBERT_BASE_DIMENSIONS,
    maximum_input_tokens=GTE_MODERNBERT_BASE_MAX_TOKENS,
    passage_prefix="",
    query_prefix="",
    display_name="gte-modernbert-base",
    collection_name="phase2-dev-gte-modernbert-base-v1",
    batch_size=8,
)
_SUPPORTED_PROFILES = (_E5_PROFILE, _BGE_PROFILE, _GTE_PROFILE)


class EmbeddingModelError(RuntimeError):
    """A safe local embedding failure without model or source text details."""


class EmbeddingInferenceTimeout(EmbeddingModelError):
    """Query encoding exceeded its configured wait deadline."""


class EmbeddingInferenceBusy(EmbeddingModelError):
    """A previous query still occupies the adapter's single worker."""


def _consume_query_future_exception(
    future: asyncio.Future[tuple[tuple[float, ...], ...]],
) -> None:
    """Retrieve errors from an encoder call that outlives its awaiting request."""
    if not future.cancelled():
        future.exception()


class _SentenceTransformerEmbedder:
    """Shared lazy loader, input validation and normalized encoding implementation."""

    _profile: ClassVar[_EmbeddingProfile]

    def __init__(
        self,
        *,
        device: EmbeddingDevice = "auto",
        model: Any | None = None,
        query_timeout_seconds: float = 10.0,
        precision: EmbeddingPrecision = "fp32",
    ) -> None:
        if device not in {"auto", "cpu", "cuda"}:
            raise ValueError("device must be auto, cpu or cuda")
        if precision not in {"fp32", "fp16"}:
            raise ValueError("precision must be fp32 or fp16")
        self.device = device
        self.precision = precision
        self._model = model
        self._tokenizer = getattr(model, "tokenizer", None)
        if (
            isinstance(query_timeout_seconds, bool)
            or not isinstance(query_timeout_seconds, (int, float))
            or not math.isfinite(query_timeout_seconds)
            or query_timeout_seconds <= 0
        ):
            raise ValueError("query_timeout_seconds must be finite and positive")
        self.query_timeout_seconds = float(query_timeout_seconds)
        self._model_lock = threading.Lock()
        self._tokenizer_lock = threading.Lock()
        self._query_submission_lock = threading.Lock()
        self._query_executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="query-embedding"
        )
        self._active_query_future: Future[tuple[tuple[float, ...], ...]] | None = None
        self._closed = False

    @classmethod
    def index_configuration(
        cls,
        collection_name: str | None = None,
        *,
        batch_size: int | None = None,
    ) -> IndexConfiguration:
        """Return the immutable model identity with a separately named collection."""
        return cls._profile.index_configuration(
            collection_name=collection_name,
            batch_size=batch_size,
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
                self._encode_texts,
                tuple(texts),
                self._profile.passage_prefix,
                configuration,
            )
        except EmbeddingModelError:
            raise
        except Exception:
            raise EmbeddingModelError("local embedding inference failed") from None

    async def embed_query(
        self, text: str, *, configuration: IndexConfiguration
    ) -> Sequence[float]:
        """Embed one search query with this model's pinned query formatting."""
        self._validate_configuration(configuration)
        if not isinstance(text, str) or not text.strip():
            raise ValueError("query text must be non-empty")
        loop = asyncio.get_running_loop()
        with self._query_submission_lock:
            if self._closed:
                raise EmbeddingModelError("local query embedder is closed")
            if (
                self._active_query_future is not None
                and not self._active_query_future.done()
            ):
                raise EmbeddingInferenceBusy(
                    "query embedding worker is completing a previous request"
                )
            try:
                worker_future = self._query_executor.submit(
                    self._encode_texts,
                    (text,),
                    self._profile.query_prefix,
                    configuration,
                )
            except RuntimeError:
                raise EmbeddingModelError("local query embedder is closed") from None
            self._active_query_future = worker_future
        future = asyncio.wrap_future(worker_future, loop=loop)
        future.add_done_callback(_consume_query_future_exception)
        try:
            vectors = await asyncio.wait_for(
                asyncio.shield(future), timeout=self.query_timeout_seconds
            )
            return vectors[0]
        except TimeoutError:
            raise EmbeddingInferenceTimeout(
                "local query embedding exceeded its configured timeout"
            ) from None
        except asyncio.CancelledError:
            raise
        except EmbeddingModelError:
            raise
        except Exception:
            raise EmbeddingModelError("local query embedding failed") from None

    def close(self) -> None:
        """Reject new query work and cancel queued work while the active call finishes."""
        with self._query_submission_lock:
            if not self._closed:
                self._closed = True
                self._query_executor.shutdown(wait=False, cancel_futures=True)

    def token_spans(self, text: str) -> Sequence[TokenSpan]:
        """Return tokenizer offsets for source-aware chunking."""
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

    def _encode_texts(
        self,
        texts: Sequence[str],
        prefix: str,
        configuration: IndexConfiguration,
    ) -> tuple[tuple[float, ...], ...]:
        model = self._ensure_model()
        tokenizer = self._ensure_tokenizer()
        formatted_texts = [prefix + text for text in texts]
        for formatted_text in formatted_texts:
            encoded = tokenizer(
                formatted_text,
                add_special_tokens=True,
                truncation=False,
                verbose=False,
            )
            input_ids = encoded["input_ids"]
            if input_ids and isinstance(input_ids[0], list):
                input_ids = input_ids[0]
            if len(input_ids) > self._profile.maximum_input_tokens:
                raise EmbeddingModelError(
                    "embedding input exceeds the configured model token limit"
                )
        encoded_vectors = model.encode(
            formatted_texts,
            batch_size=min(configuration.batch_size, len(texts)),
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        if hasattr(encoded_vectors, "tolist"):
            encoded_vectors = encoded_vectors.tolist()
        if not isinstance(encoded_vectors, list) or len(encoded_vectors) != len(texts):
            raise EmbeddingModelError("embedding model returned an invalid batch")
        vectors: list[tuple[float, ...]] = []
        for vector in encoded_vectors:
            if (
                not isinstance(vector, (list, tuple))
                or len(vector) != self._profile.dimensions
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
                    self._profile.model,
                    revision=self._profile.revision,
                    use_fast=True,
                    local_files_only=True,
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
                    self._profile.model,
                    revision=self._profile.revision,
                    device=device,
                    local_files_only=True,
                    trust_remote_code=False,
                )
                if self.precision == "fp16":
                    if device != "cuda":
                        raise EmbeddingModelError("fp16 embedding requires CUDA")
                    model.half()
                model.max_seq_length = self._profile.maximum_input_tokens
            except Exception:
                raise EmbeddingModelError(
                    "pinned local embedding model could not be loaded"
                ) from None
            self._model = model
            self._tokenizer = model.tokenizer
            return model

    def _validate_configuration(self, configuration: IndexConfiguration) -> None:
        if not self._profile.matches(configuration):
            raise ValueError(
                f"index configuration does not match pinned {self._profile.display_name}"
            )


class E5SmallV2Embedder(_SentenceTransformerEmbedder):
    """Batch-embed passages with the pinned Phase 1 E5 retrieval model."""

    _profile = _E5_PROFILE


class BGEBaseEnV15Embedder(_SentenceTransformerEmbedder):
    """Batch-embed passages with the pinned Phase 2 BGE-base-en-v1.5 model."""

    _profile = _BGE_PROFILE


class GTEModernBertBaseEmbedder(_SentenceTransformerEmbedder):
    """Batch-embed passages with the development-only gte-modernbert-base model."""

    _profile = _GTE_PROFILE


def validate_supported_embedding_configuration(
    configuration: IndexConfiguration,
) -> None:
    """Reject query profiles that do not name one of the pinned local models."""
    if not any(profile.matches(configuration) for profile in _SUPPORTED_PROFILES):
        raise ValueError(
            "query adapter configuration does not match pinned E5-small-v2, "
            "BGE-base-en-v1.5 or gte-modernbert-base"
        )


def index_configuration_for_model(
    *,
    model: str,
    revision: str,
    preprocessing_revision: str,
    dimensions: int,
    maximum_input_tokens: int,
) -> IndexConfiguration:
    """Build the pinned collection configuration for a supported embedding identity."""
    for profile in _SUPPORTED_PROFILES:
        if (
            profile.model == model
            and profile.revision == revision
            and profile.preprocessing_revision == preprocessing_revision
            and profile.dimensions == dimensions
            and profile.maximum_input_tokens == maximum_input_tokens
        ):
            return profile.index_configuration()
    raise ValueError("embedding identity is not a supported pinned local model")


def create_embedder_for_configuration(
    configuration: IndexConfiguration,
    *,
    device: EmbeddingDevice = "auto",
    precision: EmbeddingPrecision = "fp32",
) -> _SentenceTransformerEmbedder:
    """Choose the pinned local adapter from the vector-index identity."""
    validate_supported_embedding_configuration(configuration)
    if configuration.embedding_model == E5_SMALL_V2_MODEL:
        return E5SmallV2Embedder(device=device, precision=precision)
    if configuration.embedding_model == BGE_BASE_EN_V1_5_MODEL:
        return BGEBaseEnV15Embedder(device=device, precision=precision)
    if configuration.embedding_model == GTE_MODERNBERT_BASE_MODEL:
        return GTEModernBertBaseEmbedder(device=device, precision=precision)
    raise ValueError("no local embedding adapter supports this configuration")
