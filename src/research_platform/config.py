"""Validated application configuration loaded from environment variables."""

import os
from dataclasses import dataclass, field
from math import isfinite
from pathlib import Path
from typing import Final
from urllib.parse import urlparse

DEFAULT_DATABASE_URL: Final = "postgresql://research:research@localhost:5432/research"
DEFAULT_QDRANT_URL: Final = "http://localhost:6333"
DEFAULT_DEPENDENCY_TIMEOUT_SECONDS: Final = 2.0
DEFAULT_EVIDENCE_ACCESS_PROFILE: Final = "disabled"
_ALLOWED_EVIDENCE_ACCESS_PROFILES: Final = frozenset(
    {"disabled", "trusted_private_local"}
)

_ALLOWED_ENVIRONMENTS: Final = frozenset({"development", "test", "production"})
_ALLOWED_LOG_LEVELS: Final = frozenset(
    {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
)


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
