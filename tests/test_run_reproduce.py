from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from research_platform.agents.graph_deep import build_deep_graph
from research_platform.agents.graph_quick import build_quick_graph
from research_platform.evaluation.phase3_regression import (
    load_cases,
    load_corpus,
    run_case_detailed,
)
from research_platform.llm.scripted import ScriptedLLM
from research_platform.llm.types import CallKind, DecodingSettings, ModelIdentity
from research_platform.runs.checkpointing import checkpoint_serializer
from research_platform.runs.contracts import ResearchMode, ResearchRequest, RunBudgets
from research_platform.runs.memory import InMemoryRunStore
from research_platform.runs.reproduce import (
    NotReproducible,
    ReproductionInputs,
    check_run,
    configuration_differences,
    inputs_from_configuration,
    reproduction_recipe,
)
from research_platform.runs.runner import (
    GraphBuilder,
    ResearchRunner,
    RunnerDependencies,
    ServingIdentity,
    build_provenance,
)
from research_platform.tools.fakes import fake_services
from research_platform.tools.research_tools import ResearchTools

_ROOT = Path(__file__).parents[1]
_CASES_PATH = _ROOT / "benchmarks" / "phase3" / "regression-cases-v2.json"


def _case_and_corpus(case_id: str = "route-01-search-path"):
    cases = {case.case_id: case for case in load_cases(_CASES_PATH)}
    case = cases[case_id]
    return case, load_corpus(_CASES_PATH)


@pytest.mark.anyio
async def test_check_passes_for_scripted_run() -> None:
    case, corpus = _case_and_corpus()
    case_run = await run_case_detailed(case, corpus)

    result = await check_run(case_run.store, case_run.run_id)

    assert result.hash_matches
    assert result.rebuilt_matches
    assert result.differences == ()


@pytest.mark.anyio
async def test_scripted_rerun_follows_same_tool_path() -> None:
    case, corpus = _case_and_corpus()
    original = await run_case_detailed(case, corpus)
    view = await original.store.get_run_view(original.run_id)
    assert view.provenance is not None
    stored = await original.store.load_run_configuration(
        view.provenance.configuration_id
    )
    inputs = inputs_from_configuration(view.question, stored)

    search, papers, citations, related = fake_services(corpus)
    tools = ResearchTools(
        search=search,
        papers=papers,
        citations=citations,
        related=related,
    )
    graphs: dict[ResearchMode, GraphBuilder] = {
        ResearchMode.QUICK: build_quick_graph,
        ResearchMode.DEEP_RESEARCH: build_deep_graph,
    }
    rerun_store = InMemoryRunStore()
    runner = ResearchRunner(
        RunnerDependencies(
            repository=rerun_store,
            tools=tools,
            llm=ScriptedLLM(case.replies, identity=inputs.model),
            checkpointer=InMemorySaver(serde=checkpoint_serializer()),
            serving=ServingIdentity(
                snapshot_id=inputs.serving.snapshot_id,
                retrieval_profile_id=inputs.serving.retrieval_profile_id,
                generation=inputs.serving.generation,
                retrieval_settings_id=inputs.serving.retrieval_settings_id,
                generation_configuration_id=(
                    inputs.serving.generation_configuration_id
                ),
            ),
            budgets=inputs.budgets,
            thinking=inputs.thinking,
            decoding=inputs.decoding,
            code_revision=inputs.code_revision,
            graphs=graphs,
        )
    )
    rerun_id = await rerun_store.create_run(inputs.request)
    await runner.run(rerun_id)

    rerun_view = await rerun_store.get_run_view(rerun_id)
    assert rerun_view.provenance is not None
    assert rerun_view.provenance.configuration_id == view.provenance.configuration_id
    assert tuple(call.tool_name for call in rerun_store.tool_calls(rerun_id)) == tuple(
        call.tool_name for call in original.store.tool_calls(original.run_id)
    )


@pytest.mark.anyio
async def test_missing_configuration_reported() -> None:
    store = InMemoryRunStore()
    request = ResearchRequest(
        question="synthetic question",
        mode=ResearchMode.QUICK,
    )
    run_id = await store.create_run(request)
    provenance = build_provenance(
        run_id=run_id,
        request=request,
        serving=ServingIdentity(
            UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"), "synthetic-profile"
        ),
        model=ModelIdentity(name="scripted", runtime="scripted", context_tokens=8192),
        thinking=frozenset(),
        budgets=RunBudgets(),
        code_revision="synthetic-revision",
    )
    await store.mark_running(run_id, provenance=provenance)

    result = await check_run(store, run_id)

    assert result.stored_configuration_found is False
    assert result.hash_matches is False
    assert result.rebuilt_matches is False


def test_version_one_configuration_not_reproducible() -> None:
    with pytest.raises(NotReproducible, match="predates provenance version 2"):
        inputs_from_configuration("synthetic question", {"provenance_version": 1})


def test_differences_list_changed_keys() -> None:
    assert configuration_differences(
        {"mode": "quick", "budgets": {"calls": 3}, "none": None},
        {"mode": "deep_research", "budgets": {"calls": 3}, "added": None},
    ) == ("added", "mode", "none")


def test_recipe_has_environment() -> None:
    inputs = ReproductionInputs(
        request=ResearchRequest(
            question="synthetic question",
            mode=ResearchMode.QUICK,
        ),
        budgets=RunBudgets(),
        thinking=frozenset({CallKind.PLAN}),
        serving=ServingIdentity(
            UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"), "synthetic-profile"
        ),
        model=ModelIdentity(name="scripted", runtime="scripted", context_tokens=8192),
        decoding=DecodingSettings(seed=17, context_tokens=8192, timeout_seconds=45.0),
        code_revision="abc123+dirty.sha256:deadbeef",
    )

    recipe = reproduction_recipe(inputs)

    assert recipe["environment"] == {
        "RESEARCH_PLATFORM_LLM_MODEL": inputs.model.name,
        "RESEARCH_PLATFORM_LLM_THINKING": "plan",
        "RESEARCH_PLATFORM_LLM_SEED": 17,
        "RESEARCH_PLATFORM_LLM_CONTEXT_TOKENS": 8192,
        "RESEARCH_PLATFORM_LLM_TIMEOUT_SECONDS": 45.0,
    }
    assert recipe["git_checkout"] == "abc123"
    assert recipe["dirty"] is True
