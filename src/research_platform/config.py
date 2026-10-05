"""Validated application configuration loaded from environment variables."""

import os
from dataclasses import dataclass, field
from decimal import Decimal
from math import isfinite
from pathlib import Path
from typing import Final
from urllib.parse import urlparse

from research_platform.llm.types import CallKind

DEFAULT_DATABASE_URL: Final = "postgresql://research:research@localhost:5432/research"
DEFAULT_QDRANT_URL: Final = "http://localhost:6333"
DEFAULT_DEPENDENCY_TIMEOUT_SECONDS: Final = 2.0
DEFAULT_EVIDENCE_ACCESS_PROFILE: Final = "disabled"
DEFAULT_LLM_BASE_URL: Final = "http://localhost:11434"
DEFAULT_LLM_MODEL: Final = "qwen3.5-2b-text:q4_k_m"
DEFAULT_LLM_TIMEOUT_SECONDS: Final = 1200.0
DEFAULT_LLM_CONTEXT_TOKENS: Final = 32768
DEFAULT_LLM_SEED: Final = 20261001
_ALLOWED_EVIDENCE_ACCESS_PROFILES: Final = frozenset(
    {"disabled", "trusted_private_local"}
)

_ALLOWED_ENVIRONMENTS: Final = frozenset({"development", "test", "production"})
_ALLOWED_LOG_LEVELS: Final = frozenset(
    {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
)


@dataclass(frozen=True)
class DiscoverySettings:
    """Conservative policy and cost defaults for online OpenAlex discovery."""

    max_search_requests_per_run: int = 10
    max_downloads_per_run: int = 5
    daily_spend_cap_usd: Decimal = Decimal("0.50")
    search_request_cost_usd: Decimal = Decimal("0.001")
    content_download_cost_usd: Decimal = Decimal("0.01")
    minimum_publication_year: int = 2020
    language: str = "en"
    openalex_field_ids: tuple[str, ...] = ("fields/17",)
    results_per_request: int = 25

    def __post_init__(self) -> None:
        for name in (
            "max_search_requests_per_run",
            "max_downloads_per_run",
            "results_per_request",
            "minimum_publication_year",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{name} must be an integer")
            if value <= 0:
                raise ValueError(f"{name} must be positive")
        if self.minimum_publication_year < 2020:
            raise ValueError("minimum_publication_year cannot be before 2020")
        if self.results_per_request > 100:
            raise ValueError("results_per_request cannot exceed OpenAlex's limit of 100")
        if self.language != "en":
            raise ValueError("online discovery language is fixed to 'en'")
        if not isinstance(self.openalex_field_ids, tuple) or not self.openalex_field_ids:
            raise ValueError("openalex_field_ids must be a non-empty tuple")
        if any(
            not isinstance(field_id, str)
            or not field_id.startswith("fields/")
            or not field_id.removeprefix("fields/").isdigit()
            for field_id in self.openalex_field_ids
        ):
            raise ValueError("OpenAlex field IDs must look like 'fields/17'")
        if len(set(self.openalex_field_ids)) != len(self.openalex_field_ids):
            raise ValueError("openalex_field_ids must not contain duplicates")
        if not isinstance(self.daily_spend_cap_usd, Decimal) or (
            not self.daily_spend_cap_usd.is_finite()
            or self.daily_spend_cap_usd <= 0
            or self.daily_spend_cap_usd >= Decimal("1")
        ):
            raise ValueError("daily_spend_cap_usd must be finite, positive, and below $1")
        for name in ("search_request_cost_usd", "content_download_cost_usd"):
            value = getattr(self, name)
            if not isinstance(value, Decimal) or not value.is_finite() or value <= 0:
                raise ValueError(f"{name} must be a finite positive Decimal")


def _environment_default() -> str:
    return os.environ.get("RESEARCH_PLATFORM_ENVIRONMENT", "development")


def _log_level_default() -> str:
    return os.environ.get("RESEARCH_PLATFORM_LOG_LEVEL", "INFO")


def _database_url_default() -> str:
    return os.environ.get("RESEARCH_PLATFORM_DATABASE_URL", DEFAULT_DATABASE_URL)


def _qdrant_url_default() -> str:
    return os.environ.get("RESEARCH_PLATFORM_QDRANT_URL", DEFAULT_QDRANT_URL)


def _openalex_api_key_default() -> str | None:
    return os.environ.get("OPENALEX_API_KEY") or None


def _evidence_access_profile_default() -> str:
    return os.environ.get(
        "RESEARCH_PLATFORM_EVIDENCE_ACCESS_PROFILE",
        DEFAULT_EVIDENCE_ACCESS_PROFILE,
    )


def _lexical_index_root_default() -> Path:
    return Path(
        os.environ.get(
            "RESEARCH_PLATFORM_LEXICAL_INDEX_ROOT",
            "local-reference/phase2-indexes",
        )
    )


def _model_device_default() -> str:
    return os.environ.get("RESEARCH_PLATFORM_MODEL_DEVICE", "auto")


def _content_source_default() -> str:
    return os.environ.get("RESEARCH_PLATFORM_CONTENT_SOURCE", "qdrant")


def _lexical_engine_default() -> str:
    return os.environ.get("RESEARCH_PLATFORM_LEXICAL_ENGINE", "qdrant")


def _generation_collection_default() -> str:
    return os.environ.get("RESEARCH_PLATFORM_GENERATION_COLLECTION", "research-corpus")


def _generation_configuration_default() -> Path:
    return Path(
        os.environ.get(
            "RESEARCH_PLATFORM_GENERATION_CONFIGURATION",
            "configs/phase35-generation-index-lexical.example.json",
        )
    )


def _reranker_cache_dir_default() -> Path | None:
    value = os.environ.get("RESEARCH_PLATFORM_RERANKER_CACHE_DIR")
    return Path(value) if value else None


def _dependency_timeout_default() -> float:
    return float(
        os.environ.get(
            "RESEARCH_PLATFORM_DEPENDENCY_TIMEOUT_SECONDS",
            str(DEFAULT_DEPENDENCY_TIMEOUT_SECONDS),
        )
    )


def _llm_base_url_default() -> str:
    return os.environ.get("RESEARCH_PLATFORM_LLM_BASE_URL", DEFAULT_LLM_BASE_URL)


def _llm_model_default() -> str:
    return os.environ.get("RESEARCH_PLATFORM_LLM_MODEL", DEFAULT_LLM_MODEL)


def _llm_timeout_default() -> float:
    return float(
        os.environ.get(
            "RESEARCH_PLATFORM_LLM_TIMEOUT_SECONDS",
            str(DEFAULT_LLM_TIMEOUT_SECONDS),
        )
    )


def _llm_context_tokens_default() -> int:
    return int(
        os.environ.get(
            "RESEARCH_PLATFORM_LLM_CONTEXT_TOKENS",
            str(DEFAULT_LLM_CONTEXT_TOKENS),
        )
    )


def _llm_thinking_default() -> frozenset[CallKind]:
    raw_values = os.environ.get("RESEARCH_PLATFORM_LLM_THINKING", "plan,synthesize")
    values = (value.strip() for value in raw_values.split(","))
    return frozenset(CallKind(value) for value in values if value)


def _llm_seed_default() -> int:
    return int(os.environ.get("RESEARCH_PLATFORM_LLM_SEED", str(DEFAULT_LLM_SEED)))


def _validate_url(name: str, value: str, schemes: frozenset[str]) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty URL")

    parsed = urlparse(value)
    if parsed.scheme not in schemes or not parsed.netloc:
        expected = ", ".join(sorted(schemes))
        raise ValueError(f"{name} must use one of these schemes: {expected}")

    return value


@dataclass(frozen=True)
class Settings:
    """Runtime settings shared by application components."""

    environment: str = field(default_factory=_environment_default)
    log_level: str = field(default_factory=_log_level_default)
    database_url: str = field(
        default_factory=_database_url_default,
        repr=False,
    )
    qdrant_url: str = field(default_factory=_qdrant_url_default)
    openalex_api_key: str | None = field(
        default_factory=_openalex_api_key_default,
        repr=False,
    )
    dependency_timeout_seconds: float = field(
        default_factory=_dependency_timeout_default
    )
    evidence_access_profile: str = field(
        default_factory=_evidence_access_profile_default
    )
    lexical_index_root: Path = field(default_factory=_lexical_index_root_default)
    model_device: str = field(default_factory=_model_device_default)
    reranker_cache_dir: Path | None = field(default_factory=_reranker_cache_dir_default)
    content_source: str = field(default_factory=_content_source_default)
    lexical_engine: str = field(default_factory=_lexical_engine_default)
    generation_collection: str = field(default_factory=_generation_collection_default)
    generation_configuration: Path = field(
        default_factory=_generation_configuration_default
    )
    llm_base_url: str = field(default_factory=_llm_base_url_default)
    llm_model: str = field(default_factory=_llm_model_default)
    llm_timeout_seconds: float = field(default_factory=_llm_timeout_default)
    llm_context_tokens: int = field(default_factory=_llm_context_tokens_default)
    llm_thinking: frozenset[CallKind] = field(default_factory=_llm_thinking_default)
    llm_seed: int = field(default_factory=_llm_seed_default)

    def __post_init__(self) -> None:
        environment = self.environment.strip().lower()
        if environment not in _ALLOWED_ENVIRONMENTS:
            allowed = ", ".join(sorted(_ALLOWED_ENVIRONMENTS))
            raise ValueError(f"environment must be one of: {allowed}")
        object.__setattr__(self, "environment", environment)

        log_level = self.log_level.strip().upper()
        if log_level not in _ALLOWED_LOG_LEVELS:
            allowed = ", ".join(sorted(_ALLOWED_LOG_LEVELS))
            raise ValueError(f"log_level must be one of: {allowed}")
        object.__setattr__(self, "log_level", log_level)

        _validate_url("database_url", self.database_url, frozenset({"postgresql"}))
        _validate_url("qdrant_url", self.qdrant_url, frozenset({"http", "https"}))
        _validate_url("llm_base_url", self.llm_base_url, frozenset({"http", "https"}))

        llm_model = self.llm_model.strip()
        if not llm_model:
            raise ValueError("llm_model must be a non-empty model name")
        object.__setattr__(self, "llm_model", llm_model)

        if (
            not isfinite(self.llm_timeout_seconds)
            or not 0 < self.llm_timeout_seconds <= 3600
        ):
            raise ValueError(
                "llm_timeout_seconds must be greater than 0 and at most 3600"
            )

        if not 2048 <= self.llm_context_tokens <= 262144:
            raise ValueError("llm_context_tokens must be between 2048 and 262144")

        if self.llm_seed < 0:
            raise ValueError("llm_seed must be at least 0")

        if self.openalex_api_key is not None:
            if (
                not isinstance(self.openalex_api_key, str)
                or not self.openalex_api_key.strip()
            ):
                raise ValueError("openalex_api_key must be a non-empty secret or None")
            object.__setattr__(self, "openalex_api_key", self.openalex_api_key.strip())

        evidence_access_profile = self.evidence_access_profile.strip().lower()
        if evidence_access_profile not in _ALLOWED_EVIDENCE_ACCESS_PROFILES:
            allowed = ", ".join(sorted(_ALLOWED_EVIDENCE_ACCESS_PROFILES))
            raise ValueError(f"evidence_access_profile must be one of: {allowed}")
        object.__setattr__(self, "evidence_access_profile", evidence_access_profile)

        model_device = self.model_device.strip().lower()
        if model_device not in {"auto", "cpu", "cuda"}:
            raise ValueError("model_device must be auto, cpu or cuda")
        object.__setattr__(self, "model_device", model_device)
        content_source = self.content_source.strip().lower()
        if content_source not in {"postgres", "qdrant"}:
            raise ValueError("content_source must be postgres or qdrant")
        object.__setattr__(self, "content_source", content_source)
        lexical_engine = self.lexical_engine.strip().lower()
        if lexical_engine not in {"bm25s", "qdrant"}:
            raise ValueError("lexical_engine must be bm25s or qdrant")
        object.__setattr__(self, "lexical_engine", lexical_engine)
        if not self.generation_collection.strip():
            raise ValueError("generation_collection must be a non-empty name")
        object.__setattr__(
            self, "generation_configuration", Path(self.generation_configuration)
        )
        lexical_root = Path(self.lexical_index_root)
        if not str(lexical_root).strip():
            raise ValueError("lexical_index_root must be a non-empty path")
        object.__setattr__(self, "lexical_index_root", lexical_root)
        if self.reranker_cache_dir is not None:
            reranker_cache_dir = Path(self.reranker_cache_dir)
            if not str(reranker_cache_dir).strip():
                raise ValueError("reranker_cache_dir must be a non-empty path or null")
            object.__setattr__(self, "reranker_cache_dir", reranker_cache_dir)

        if (
            not isfinite(self.dependency_timeout_seconds)
            or self.dependency_timeout_seconds <= 0
        ):
            raise ValueError(
                "dependency_timeout_seconds must be a finite positive number"
            )
