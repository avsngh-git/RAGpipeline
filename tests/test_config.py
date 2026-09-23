"""Behavioral tests for the application configuration boundary."""

import pytest

from research_platform.config import (
    DEFAULT_DATABASE_URL,
    DEFAULT_DEPENDENCY_TIMEOUT_SECONDS,
    DEFAULT_QDRANT_URL,
    Settings,
)

_SETTING_ENVIRONMENT_VARIABLES = (
    "RESEARCH_PLATFORM_ENVIRONMENT",
    "RESEARCH_PLATFORM_LOG_LEVEL",
    "RESEARCH_PLATFORM_DATABASE_URL",
    "RESEARCH_PLATFORM_QDRANT_URL",
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

    settings = Settings()

    assert settings.environment == "test"
    assert settings.log_level == "DEBUG"
    assert settings.database_url == (
        "postgresql://user:password@db.example:5432/research"
    )
    assert settings.qdrant_url == "https://qdrant.example"
    assert settings.dependency_timeout_seconds == 4.5


@pytest.mark.parametrize(
    ("variable", "value", "field_name"),
    [
        ("RESEARCH_PLATFORM_ENVIRONMENT", "staging", "environment"),
        ("RESEARCH_PLATFORM_LOG_LEVEL", "VERBOSE", "log_level"),
        ("RESEARCH_PLATFORM_DATABASE_URL", "not-a-url", "database_url"),
        ("RESEARCH_PLATFORM_QDRANT_URL", "postgresql://db", "qdrant_url"),
        (
            "RESEARCH_PLATFORM_DEPENDENCY_TIMEOUT_SECONDS",
            "0",
            "dependency_timeout_seconds",
        ),
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
