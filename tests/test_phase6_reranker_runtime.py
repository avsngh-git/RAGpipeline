from __future__ import annotations

from uuid import UUID

from research_platform.llm.types import CallKind, ModelIdentity
from research_platform.runs.contracts import (
    RerankerRuntimeRecord,
    ResearchMode,
    ResearchRequest,
    RunBudgets,
)
from research_platform.runs.reproduce import (
    inputs_from_configuration,
    reproduction_recipe,
)
from research_platform.runs.runner import ServingIdentity, build_effective_configuration

_RUN_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
_SNAPSHOT_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")


def _effective_configuration(
    *,
    reranker_runtime: RerankerRuntimeRecord | None = None,
    include_runtime_keyword: bool = True,
):
    arguments = {
        "run_id": _RUN_ID,
        "request": ResearchRequest(
            question="Synthetic reranker runtime question", mode=ResearchMode.QUICK
        ),
        "serving": ServingIdentity(_SNAPSHOT_ID, "synthetic-profile"),
        "model": ModelIdentity(
            name="synthetic", runtime="scripted", context_tokens=8192
        ),
        "thinking": frozenset({CallKind.PLAN}),
        "budgets": RunBudgets(),
        "code_revision": "synthetic-revision",
    }
    if include_runtime_keyword:
        return build_effective_configuration(
            **arguments, reranker_runtime=reranker_runtime
        )
    return build_effective_configuration(**arguments)


def test_configuration_includes_runtime_when_known() -> None:
    runtime = RerankerRuntimeRecord(device="cpu", precision="fp32")

    result = _effective_configuration(reranker_runtime=runtime)

    assert result.payload["reranker_runtime"] == {
        "device": "cpu",
        "precision": "fp32",
    }
    assert result.provenance.reranker_runtime == runtime


def test_configuration_hash_unchanged_without_runtime() -> None:
    omitted = _effective_configuration(include_runtime_keyword=False)
    explicit_none = _effective_configuration(reranker_runtime=None)

    assert "reranker_runtime" not in omitted.payload
    assert "reranker_runtime" not in explicit_none.payload
    assert (
        omitted.provenance.configuration_id == explicit_none.provenance.configuration_id
    )


def test_cpu_and_gpu_runs_hash_differently() -> None:
    cpu = _effective_configuration(
        reranker_runtime=RerankerRuntimeRecord(device="cpu", precision="fp32")
    )
    gpu = _effective_configuration(
        reranker_runtime=RerankerRuntimeRecord(device="cuda", precision="fp16")
    )

    assert cpu.provenance.configuration_id != gpu.provenance.configuration_id


def test_reproduce_round_trips_the_runtime() -> None:
    runtime = RerankerRuntimeRecord(device="cpu", precision="fp32")
    original = _effective_configuration(reranker_runtime=runtime)

    inputs = inputs_from_configuration(
        "Synthetic reranker runtime question", original.payload
    )
    rebuilt = build_effective_configuration(
        run_id=_RUN_ID,
        request=inputs.request,
        serving=inputs.serving,
        model=inputs.model,
        thinking=inputs.thinking,
        budgets=inputs.budgets,
        code_revision=inputs.code_revision,
        decoding=inputs.decoding,
        reranker_runtime=inputs.reranker_runtime,
    )

    assert inputs.reranker_runtime == runtime
    assert rebuilt.provenance.configuration_id == original.provenance.configuration_id


def test_reproduce_accepts_older_payloads() -> None:
    result = _effective_configuration(include_runtime_keyword=False)

    inputs = inputs_from_configuration(
        "Synthetic reranker runtime question", result.payload
    )

    assert inputs.reranker_runtime is None


def test_reproduction_recipe_records_actual_model_device() -> None:
    runtime = RerankerRuntimeRecord(device="cpu", precision="fp32")
    result = _effective_configuration(reranker_runtime=runtime)
    inputs = inputs_from_configuration(
        "Synthetic reranker runtime question", result.payload
    )

    recipe = reproduction_recipe(inputs)

    assert recipe["environment"]["RESEARCH_PLATFORM_MODEL_DEVICE"] == "cpu"
