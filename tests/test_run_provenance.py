"""Versioned effective configuration hashes capture answer-affecting inputs."""

from uuid import UUID

from research_platform.agents.prompts import PROMPT_VERSIONS
from research_platform.agents.tool_schemas import tool_schema_digest
from research_platform.llm.types import CallKind, DecodingSettings, ModelIdentity
from research_platform.runs.contracts import (
    ResearchMode,
    ResearchRequest,
    RunBudgets,
    RunProvenance,
    configuration_id,
)
from research_platform.runs.runner import (
    PROVENANCE_VERSION,
    ServingIdentity,
    build_effective_configuration,
)

_SNAPSHOT = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
_RUN_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
_MODEL = ModelIdentity(name="m", runtime="scripted", context_tokens=8192)
_REQUEST = ResearchRequest(
    question="Synthetic retrieval question", mode=ResearchMode.QUICK
)
_SERVING = ServingIdentity(_SNAPSHOT, "sha256:" + "a" * 64)


def _effective(seed: int = 1, timeout_seconds: float = 60):
    return build_effective_configuration(
        run_id=_RUN_ID,
        request=_REQUEST,
        serving=_SERVING,
        model=_MODEL,
        thinking=frozenset({CallKind.PLAN}),
        budgets=RunBudgets(),
        code_revision="synthetic-revision",
        decoding=DecodingSettings(
            seed=seed,
            context_tokens=8192,
            timeout_seconds=timeout_seconds,
        ),
    )


def test_payload_contains_version_two_fields() -> None:
    result = _effective()

    assert result.payload["provenance_version"] == PROVENANCE_VERSION == 2
    assert set(result.payload["prompt_fingerprints"]) == set(PROMPT_VERSIONS)
    assert result.payload["tool_schema_digest"] == tool_schema_digest()
    assert result.payload["decoding"]["seed"] == 1


def test_configuration_id_equals_hash_of_payload() -> None:
    result = _effective()

    assert configuration_id(result.payload) == result.provenance.configuration_id


def test_configuration_id_changes_with_seed() -> None:
    assert (
        _effective(seed=1).provenance.configuration_id
        != _effective(seed=2).provenance.configuration_id
    )


def test_configuration_id_changes_with_timeout() -> None:
    assert (
        _effective(timeout_seconds=60).provenance.configuration_id
        != _effective(timeout_seconds=61).provenance.configuration_id
    )


def test_configuration_id_is_stable() -> None:
    assert (
        _effective().provenance.configuration_id
        == _effective().provenance.configuration_id
    )


def test_generation_configuration_id_recorded() -> None:
    serving = ServingIdentity(
        _SNAPSHOT,
        "sha256:" + "a" * 64,
        generation=2,
        retrieval_settings_id="sha256:" + "b" * 64,
        generation_configuration_id="sha256:" + "c" * 64,
    )
    result = build_effective_configuration(
        run_id=_RUN_ID,
        request=_REQUEST,
        serving=serving,
        model=_MODEL,
        thinking=frozenset(),
        budgets=RunBudgets(),
        code_revision="synthetic-revision",
    )

    assert result.payload["generation_configuration_id"] == "sha256:" + "c" * 64
    assert result.provenance.generation_configuration_id == "sha256:" + "c" * 64


def test_version_one_provenance_still_loads() -> None:
    provenance = RunProvenance.model_validate(
        {
            "snapshot_id": str(_SNAPSHOT),
            "retrieval_profile_id": "sha256:" + "a" * 64,
            "configuration_id": "sha256:" + "d" * 64,
            "code_revision": "old-revision",
            "model": _MODEL.model_dump(mode="json"),
            "thinking": {"plan": True},
            "prompt_versions": {},
            "budgets": RunBudgets().model_dump(mode="json"),
            "trace_id": str(_RUN_ID),
        }
    )

    assert provenance.provenance_version == 1
    assert provenance.decoding is None
