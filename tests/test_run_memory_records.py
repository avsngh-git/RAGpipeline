"""In-memory store coverage for Phase 4 run records."""

from __future__ import annotations

import pytest

from research_platform.runs.contracts import configuration_id
from research_platform.runs.memory import InMemoryRunStore
from research_platform.runs.repository import ConfigurationNotFound

_PAYLOAD: dict[str, object] = {
    "provenance_version": 2,
    "mode": "quick",
    "budgets": {"max_active_seconds": 1800.0, "max_tool_calls": 12},
    "decoding": None,
    "prompt_versions": {"system": "p3-system-v1"},
    "filters": {"year_from": 2020, "year_to": None},
    "list": [1, 2.5, "three"],
}


@pytest.mark.anyio
async def test_memory_round_trip_preserves_configuration_id() -> None:
    store = InMemoryRunStore()
    expected = configuration_id(_PAYLOAD)

    await store.save_run_configuration(expected, _PAYLOAD, provenance_version=2)
    loaded = await store.load_run_configuration(expected)

    assert loaded == _PAYLOAD
    assert configuration_id(loaded) == expected


@pytest.mark.anyio
async def test_memory_save_is_idempotent() -> None:
    store = InMemoryRunStore()
    expected = configuration_id(_PAYLOAD)

    await store.save_run_configuration(expected, _PAYLOAD, provenance_version=2)
    await store.save_run_configuration(expected, _PAYLOAD, provenance_version=2)

    assert await store.load_run_configuration(expected) == _PAYLOAD


@pytest.mark.anyio
async def test_memory_save_rejects_wrong_id() -> None:
    store = InMemoryRunStore()

    with pytest.raises(ValueError, match="does not match"):
        await store.save_run_configuration(
            "sha256:" + "0" * 64, _PAYLOAD, provenance_version=2
        )


@pytest.mark.anyio
async def test_memory_load_missing_raises() -> None:
    store = InMemoryRunStore()

    with pytest.raises(ConfigurationNotFound):
        await store.load_run_configuration("sha256:" + "1" * 64)


@pytest.mark.anyio
async def test_memory_loaded_configuration_is_a_copy() -> None:
    store = InMemoryRunStore()
    expected = configuration_id(_PAYLOAD)
    await store.save_run_configuration(expected, _PAYLOAD, provenance_version=2)

    loaded = await store.load_run_configuration(expected)
    loaded["mode"] = "changed"

    assert (await store.load_run_configuration(expected))["mode"] == "quick"
