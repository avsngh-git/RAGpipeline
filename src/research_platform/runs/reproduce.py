"""Rebuild and inspect effective configuration for a persisted run."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TypeVar, cast
from uuid import UUID

from pydantic import BaseModel, ValidationError

from research_platform.llm.types import CallKind, DecodingSettings, ModelIdentity
from research_platform.runs.contracts import (
    ResearchRequest,
    RunBudgets,
    configuration_id,
)
from research_platform.runs.repository import ConfigurationNotFound
from research_platform.runs.runner import (
    ServingIdentity,
    build_effective_configuration,
)
from research_platform.runs.store import RunStore


class NotReproducible(ValueError):
    """The run's stored configuration cannot rebuild its inputs."""


@dataclass(frozen=True)
class ReproductionInputs:
    request: ResearchRequest
    budgets: RunBudgets
    thinking: frozenset[CallKind]
    serving: ServingIdentity
    model: ModelIdentity
    decoding: DecodingSettings | None
    code_revision: str


@dataclass(frozen=True)
class ReproductionCheck:
    run_id: UUID
    configuration_id: str
    stored_configuration_found: bool
    hash_matches: bool
    rebuilt_matches: bool
    differences: tuple[str, ...]


def _missing(key: str) -> NotReproducible:
    return NotReproducible(f"configuration is missing {key}")


_ModelT = TypeVar("_ModelT", bound=BaseModel)


def _model_value(key: str, model: type[_ModelT], value: object) -> _ModelT:
    try:
        return model.model_validate(value)
    except (TypeError, ValueError, ValidationError):
        raise _missing(key) from None


def inputs_from_configuration(
    question: str, configuration: Mapping[str, object]
) -> ReproductionInputs:
    if configuration.get("provenance_version") != 2:
        raise NotReproducible("run predates provenance version 2")

    try:
        request = ResearchRequest.model_validate(
            {
                "question": question,
                "mode": configuration["mode"],
                "snapshot_id": configuration["snapshot_id"],
                "filters": configuration["filters"],
            }
        )
    except KeyError as error:
        raise _missing(str(error.args[0])) from None
    except (TypeError, ValueError, ValidationError) as error:
        if isinstance(error, ValidationError) and error.errors():
            location = error.errors()[0].get("loc", ())
            key = str(location[0]) if location else "request"
        else:
            key = "request"
        raise _missing(key) from None

    budgets = _model_value("budgets", RunBudgets, configuration.get("budgets"))
    model = _model_value("model", ModelIdentity, configuration.get("model"))

    thinking_raw = configuration.get("thinking")
    if not isinstance(thinking_raw, Mapping):
        raise _missing("thinking")
    try:
        thinking = frozenset(CallKind(kind) for kind, on in thinking_raw.items() if on)
    except (TypeError, ValueError):
        raise _missing("thinking") from None

    try:
        serving = ServingIdentity(
            snapshot_id=UUID(str(configuration["snapshot_id"])),
            retrieval_profile_id=str(configuration["retrieval_profile_id"]),
            generation=cast(int | None, configuration.get("generation")),
            retrieval_settings_id=cast(
                str | None, configuration.get("retrieval_settings_id")
            ),
            generation_configuration_id=cast(
                str | None, configuration.get("generation_configuration_id")
            ),
        )
    except (KeyError, TypeError, ValueError) as error:
        key = error.args[0] if isinstance(error, KeyError) else "serving"
        raise _missing(str(key)) from None

    decoding_raw = configuration.get("decoding")
    try:
        decoding = (
            DecodingSettings.model_validate(decoding_raw) if decoding_raw else None
        )
    except (TypeError, ValueError, ValidationError):
        raise _missing("decoding") from None

    try:
        code_revision = str(configuration["code_revision"])
    except KeyError as error:
        raise _missing(str(error.args[0])) from None

    return ReproductionInputs(
        request=request,
        budgets=budgets,
        thinking=thinking,
        serving=serving,
        model=model,
        decoding=decoding,
        code_revision=code_revision,
    )


def _flatten(mapping: Mapping[str, object]) -> dict[str, object]:
    flattened: dict[str, object] = {}

    def visit(prefix: str, value: object) -> None:
        if isinstance(value, dict) and value:
            for key, nested in value.items():
                path = f"{prefix}.{key}" if prefix else str(key)
                visit(path, nested)
        else:
            flattened[prefix] = value

    for key, value in mapping.items():
        visit(str(key), value)
    return flattened


def configuration_differences(
    stored: Mapping[str, object], current: Mapping[str, object]
) -> tuple[str, ...]:
    stored_flat = _flatten(stored)
    current_flat = _flatten(current)
    return tuple(
        sorted(
            key
            for key in stored_flat.keys() | current_flat.keys()
            if key not in stored_flat
            or key not in current_flat
            or stored_flat[key] != current_flat[key]
        )
    )


async def check_run(store: RunStore, run_id: UUID) -> ReproductionCheck:
    view = await store.get_run_view(run_id)
    if view.provenance is None:
        raise NotReproducible("run has no provenance")

    expected_id = view.provenance.configuration_id
    try:
        stored = await store.load_run_configuration(expected_id)
    except ConfigurationNotFound:
        return ReproductionCheck(
            run_id=run_id,
            configuration_id=expected_id,
            stored_configuration_found=False,
            hash_matches=False,
            rebuilt_matches=False,
            differences=(),
        )

    hash_matches = configuration_id(stored) == expected_id
    inputs = inputs_from_configuration(view.question, stored)
    rebuilt = build_effective_configuration(
        run_id=run_id,
        request=inputs.request,
        serving=inputs.serving,
        model=inputs.model,
        thinking=inputs.thinking,
        budgets=inputs.budgets,
        code_revision=inputs.code_revision,
        decoding=inputs.decoding,
    )
    rebuilt_matches = rebuilt.provenance.configuration_id == expected_id
    return ReproductionCheck(
        run_id=run_id,
        configuration_id=expected_id,
        stored_configuration_found=True,
        hash_matches=hash_matches,
        rebuilt_matches=rebuilt_matches,
        differences=configuration_differences(stored, rebuilt.payload),
    )


def reproduction_recipe(inputs: ReproductionInputs) -> dict[str, object]:
    environment: dict[str, object] = {
        "RESEARCH_PLATFORM_LLM_MODEL": inputs.model.name,
        "RESEARCH_PLATFORM_LLM_THINKING": ",".join(
            sorted(kind.value for kind in inputs.thinking)
        ),
    }
    if inputs.decoding is not None:
        environment.update(
            {
                "RESEARCH_PLATFORM_LLM_SEED": inputs.decoding.seed,
                "RESEARCH_PLATFORM_LLM_CONTEXT_TOKENS": (
                    inputs.decoding.context_tokens
                ),
                "RESEARCH_PLATFORM_LLM_TIMEOUT_SECONDS": (
                    inputs.decoding.timeout_seconds
                ),
            }
        )
    recipe: dict[str, object] = {
        "git_checkout": inputs.code_revision.split("+", maxsplit=1)[0],
        "environment": environment,
        "mode": inputs.request.mode.value,
        "filters": inputs.request.filters.model_dump(mode="json"),
        "snapshot_id": str(inputs.serving.snapshot_id),
        "generation": inputs.serving.generation,
    }
    recipe["dirty"] = "+dirty.sha256:" in inputs.code_revision
    return recipe
