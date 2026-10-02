"""Behavioral tests for the application configuration boundary."""

import pytest

from research_platform.config import (
    DEFAULT_DATABASE_URL,
    DEFAULT_DEPENDENCY_TIMEOUT_SECONDS,
    DEFAULT_EVIDENCE_ACCESS_PROFILE,
    DEFAULT_LLM_BASE_URL,
    DEFAULT_LLM_CONTEXT_TOKENS,
    DEFAULT_LLM_MODEL,
    DEFAULT_LLM_SEED,
    DEFAULT_LLM_TIMEOUT_SECONDS,
    DEFAULT_QDRANT_URL,
    Settings,
)
from research_platform.llm.types import CallKind

_SETTING_ENVIRONMENT_VARIABLES = (
    "RESEARCH_PLATFORM_ENVIRONMENT",
    "RESEARCH_PLATFORM_LOG_LEVEL",
    "RESEARCH_PLATFORM_DATABASE_URL",
    "RESEARCH_PLATFORM_QDRANT_URL",
    "RESEARCH_PLATFORM_EVIDENCE_ACCESS_PROFILE",
    "RESEARCH_PLATFORM_LLM_BASE_URL",
    "RESEARCH_PLATFORM_LLM_MODEL",
    "RESEARCH_PLATFORM_LLM_TIMEOUT_SECONDS",
    "RESEARCH_PLATFORM_LLM_CONTEXT_TOKENS",
    "RESEARCH_PLATFORM_LLM_THINKING",
    "RESEARCH_PLATFORM_LLM_SEED",
    "OPENALEX_API_KEY",
)


def test_settings_use_safe_development_defaults(monkeypatch) -> None:
    for variable in _SETTING_ENVIRONMENT_VARIABLES:
        monkeypatch.delenv(variable, raising=False)

    settings = Settings()

    assert settings.environment == "development"
    assert settings.log_level == "INFO"
    assert settings.database_url == DEFAULT_DATABASE_URL
    assert settings.qdrant_url == DEFAULT_QDRANT_URL
    assert settings.dependency_timeout_seconds == DEFAULT_DEPENDENCY_TIMEOUT_SECONDS
    assert settings.evidence_access_profile == DEFAULT_EVIDENCE_ACCESS_PROFILE
    assert settings.openalex_api_key is None
    assert settings.llm_base_url == DEFAULT_LLM_BASE_URL
    assert settings.llm_model == DEFAULT_LLM_MODEL
    assert settings.llm_timeout_seconds == DEFAULT_LLM_TIMEOUT_SECONDS
    assert settings.llm_context_tokens == DEFAULT_LLM_CONTEXT_TOKENS
    assert settings.llm_thinking == frozenset()
    assert settings.llm_seed == DEFAULT_LLM_SEED
    assert DEFAULT_DATABASE_URL not in repr(settings)


def test_settings_read_environment_overrides(monkeypatch) -> None:
    monkeypatch.setenv("RESEARCH_PLATFORM_ENVIRONMENT", "test")
    monkeypatch.setenv("RESEARCH_PLATFORM_LOG_LEVEL", "DEBUG")
    monkeypatch.setenv(
        "RESEARCH_PLATFORM_DATABASE_URL",
        "postgresql://user:password@db.example:5432/research",
    )
    monkeypatch.setenv("RESEARCH_PLATFORM_QDRANT_URL", "https://qdrant.example")
    monkeypatch.setenv("RESEARCH_PLATFORM_DEPENDENCY_TIMEOUT_SECONDS", "4.5")
    monkeypatch.setenv("RESEARCH_PLATFORM_LLM_BASE_URL", "https://ollama.example")
    monkeypatch.setenv("RESEARCH_PLATFORM_LLM_MODEL", " local-model:v1 ")
    monkeypatch.setenv("RESEARCH_PLATFORM_LLM_TIMEOUT_SECONDS", "240")
    monkeypatch.setenv("RESEARCH_PLATFORM_LLM_CONTEXT_TOKENS", "32768")
    monkeypatch.setenv("RESEARCH_PLATFORM_LLM_THINKING", "plan, synthesize")
    monkeypatch.setenv("RESEARCH_PLATFORM_LLM_SEED", "42")
    monkeypatch.setenv(
        "RESEARCH_PLATFORM_EVIDENCE_ACCESS_PROFILE", "TRUSTED_PRIVATE_LOCAL"
    )
    monkeypatch.setenv("OPENALEX_API_KEY", "  secret-test-key  ")

    settings = Settings()

    assert settings.environment == "test"
    assert settings.log_level == "DEBUG"
    assert settings.database_url == (
        "postgresql://user:password@db.example:5432/research"
    )
    assert settings.qdrant_url == "https://qdrant.example"
    assert settings.dependency_timeout_seconds == 4.5
    assert settings.evidence_access_profile == "trusted_private_local"
    assert settings.openalex_api_key == "secret-test-key"
    assert settings.llm_base_url == "https://ollama.example"
    assert settings.llm_model == "local-model:v1"
    assert settings.llm_timeout_seconds == 240
    assert settings.llm_context_tokens == 32768
    assert settings.llm_thinking == frozenset({CallKind.PLAN, CallKind.SYNTHESIZE})
    assert settings.llm_seed == 42
    assert "secret-test-key" not in repr(settings)


@pytest.mark.parametrize(
    ("variable", "value", "field_name"),
    [
        ("RESEARCH_PLATFORM_ENVIRONMENT", "staging", "environment"),
        ("RESEARCH_PLATFORM_LOG_LEVEL", "VERBOSE", "log_level"),
        ("RESEARCH_PLATFORM_DATABASE_URL", "not-a-url", "database_url"),
        ("RESEARCH_PLATFORM_QDRANT_URL", "postgresql://db", "qdrant_url"),
        (
            "RESEARCH_PLATFORM_EVIDENCE_ACCESS_PROFILE",
            "public",
            "evidence_access_profile",
        ),
        (
            "RESEARCH_PLATFORM_DEPENDENCY_TIMEOUT_SECONDS",
            "0",
            "dependency_timeout_seconds",
        ),
        ("RESEARCH_PLATFORM_LLM_BASE_URL", "ftp://ollama.example", "llm_base_url"),
        ("RESEARCH_PLATFORM_LLM_MODEL", "  ", "llm_model"),
        ("RESEARCH_PLATFORM_LLM_TIMEOUT_SECONDS", "600.1", "llm_timeout_seconds"),
        ("RESEARCH_PLATFORM_LLM_CONTEXT_TOKENS", "1024", "llm_context_tokens"),
        ("RESEARCH_PLATFORM_LLM_THINKING", "unknown", "CallKind"),
        ("RESEARCH_PLATFORM_LLM_SEED", "-1", "llm_seed"),
    ],
)
def test_settings_reject_invalid_values(
    monkeypatch,
    variable: str,
    value: str,
    field_name: str,
) -> None:
    monkeypatch.setenv(variable, value)

    with pytest.raises(ValueError, match=field_name):
        Settings()
