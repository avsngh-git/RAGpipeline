"""Budgeted plan, execute, and evaluate graph for deep research runs."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import timedelta
from time import perf_counter
from typing import Any, Final, cast
from uuid import UUID

from langgraph.graph import END, START, StateGraph
from opentelemetry.trace import get_current_span
from pydantic import TypeAdapter

from research_platform.agents.actions import (
    Action,
    DiscoverPapersAction,
    RequestIngestionAction,
    SufficiencyDecision,
)
from research_platform.agents.evidence import pack_evidence
from research_platform.agents.nodes import (
    NodeDependencies,
    answer_node,
    record_observation,
    run_action_observed,
    traced_node,
)
from research_platform.agents.prompts import (
    evaluate_messages,
    format_observation,
    plan_messages,
)
from research_platform.agents.state import ResearchState
from research_platform.agents.tool_schemas import (
    actions_from_tool_calls,
    research_tool_definitions,
)
from research_platform.llm.contracts import (
    LLMInvalidOutput,
    StructuredCall,
    ToolCallRequest,
)
from research_platform.llm.types import CallKind
from research_platform.observability.tracing import (
    ATTR_GENERATION,
    ATTR_INGESTION_REQUEST_ID,
    ATTR_INGESTION_STATUS,
    ATTR_INGESTION_WAITED_SECONDS,
    set_id_attribute,
)
from research_platform.runs.contracts import ResearchFilters, RunBudgets
from research_platform.runs.repository import ToolCallRecord
from research_platform.tools.research_tools import ToolObservation

_POLL_SECONDS = 5.0
_TERMINAL = frozenset({"succeeded", "partially_succeeded", "failed"})

_ACTION_ADAPTER: TypeAdapter[Action] = TypeAdapter(Action)


def remaining_actions(state: ResearchState, budgets: RunBudgets) -> int:
    """Return the smaller of the per-plan and global executed-call budgets."""
    return max(
        0,
        min(
            budgets.max_actions_per_plan,
            budgets.max_tool_calls - state["ledger"].tool_calls_used,
        ),
    )


def default_actions(question: str, filters: ResearchFilters) -> tuple[Action, ...]:
    """Return the quick workflow's bounded paper and passage searches."""
    return (
        _ACTION_ADAPTER.validate_python(
            {
                "tool": "search_papers",
                "query": question[:500],
                "year_from": filters.year_from,
                "year_to": filters.year_to,
                "limit": 10,
            }
        ),
        _ACTION_ADAPTER.validate_python(
            {
                "tool": "search_evidence",
                "query": question[:500],
                "limit": 20,
            }
        ),
    )


PLAN_POLICY: Final = "p4-discover-first-v1"
_DISCOVERY_MIN_YEAR: Final = 2020


def ensure_discovery(
    actions: Sequence[Action],
    *,
    question: str,
    filters: ResearchFilters,
    max_actions: int,
) -> tuple[Action, ...]:
    """Add one discover_papers call to the first plan unless it already has one.

    The 2B planner rarely chooses discovery on its own (backlog #115), so code adds it.
    When the plan is full, discovery replaces the last action, so the model's first
    choice is kept. Nothing is added when fewer than two actions are allowed or the
    year filter ends before discovery's 2020 floor.
    """
    if any(isinstance(action, DiscoverPapersAction) for action in actions):
        return tuple(actions)
    if max_actions < 2:
        return tuple(actions)
    if filters.year_to is not None and filters.year_to < _DISCOVERY_MIN_YEAR:
        return tuple(actions)
    year_from = (
        filters.year_from
        if filters.year_from is not None and filters.year_from >= _DISCOVERY_MIN_YEAR
        else None
    )
    discover = DiscoverPapersAction(
        tool="discover_papers",
        query=question[:300],
        year_from=year_from,
        year_to=filters.year_to,
        limit=5,
    )
    kept = tuple(actions)[: max_actions - 1]
    return (*kept, discover)


def build_deep_graph(
    deps: NodeDependencies,
) -> StateGraph[ResearchState, None, ResearchState, ResearchState]:
    """Build the bounded iterative deep-research workflow."""
    budgets = deps.context.budgets

    async def plan(state: ResearchState) -> dict[str, Any]:
        max_actions = remaining_actions(state, budgets)
        if max_actions == 0:
            return {"pending_actions": [], "sufficient": True}

        try:
            result = await deps.llm.call_tools(
                ToolCallRequest(
                    messages=plan_messages(
                        question=state["question"],
                        filters=deps.context.filters,
                        max_actions=max_actions,
                    ),
                    tools=tuple(research_tool_definitions()),
                    think=CallKind.PLAN in deps.thinking,
                    max_repair_attempts=budgets.max_model_retries,
                )
            )
            actions = actions_from_tool_calls(result.calls, max_actions=max_actions)
            observations = state["observations"]
        except (LLMInvalidOutput, ValueError):
            actions = default_actions(state["question"], deps.context.filters)[
                :max_actions
            ]
            observations = [
                *state["observations"],
                "plan fallback: default actions",
            ][-20:]

        if deps.tools.discovery_available:
            actions = ensure_discovery(
                actions,
                question=state["question"],
                filters=deps.context.filters,
                max_actions=max_actions,
            )

        return {
            "pending_actions": [action.model_dump(mode="json") for action in actions],
            "plan_round": 1,
            "model_calls": state["model_calls"] + 1,
            "observations": observations,
        }

    async def execute(state: ResearchState) -> dict[str, Any]:
        current: dict[str, Any] = {
            "ledger": state["ledger"],
            "registry": state["registry"],
            "observations": state["observations"],
        }
        pending_request = state.get("pending_ingestion_request_id")
        waits = state.get("ingestion_waits", 0)
        for raw_action in state["pending_actions"]:
            action_state = cast(ResearchState, {**state, **current})
            if remaining_actions(action_state, budgets) == 0:
                break
            action = _ACTION_ADAPTER.validate_python(raw_action)
            if isinstance(action, RequestIngestionAction) and (
                pending_request is not None or waits >= 1
            ):
                rejected = ToolObservation(
                    ordinal=action_state["ledger"].records,
                    tool=action.tool,
                    arguments=action.model_dump(mode="json"),
                    status="rejected",
                    summary={},
                    error_category="ingestion_already_requested",
                )
                current.update(await record_observation(deps, action_state, rejected))
                continue
            update, observation = await run_action_observed(deps, action_state, action)
            current.update(update)
            request_id = observation.summary.get("request_id")
            if isinstance(action, RequestIngestionAction) and isinstance(
                request_id, str
            ):
                pending_request = request_id

        return {
            **current,
            "pending_actions": [],
            "pending_ingestion_request_id": pending_request,
        }

    async def wait_ingestion(state: ResearchState) -> dict[str, Any]:
        """Wait, within the cap, for this run's ingestion request; then switch."""
        raw_request_id = state.get("pending_ingestion_request_id")
        if raw_request_id is None or deps.ingestion is None:
            return {"pending_ingestion_request_id": None}
        request_id = UUID(raw_request_id)
        span = get_current_span()
        set_id_attribute(span, ATTR_INGESTION_REQUEST_ID, raw_request_id)
        await deps.repository.mark_waiting(deps.run_id)
        started = perf_counter()
        async with deps.pause_active():
            request = await deps.ingestion.get(request_id)
            deadline = (request.created_at or deps.now()) + timedelta(
                seconds=budgets.max_ingestion_wait_seconds
            )
            while request.status not in _TERMINAL:
                remaining = (deadline - deps.now()).total_seconds()
                if remaining <= 0:
                    break
                await deps.sleep(min(_POLL_SECONDS, remaining))
                request = await deps.ingestion.get(request_id)
        await deps.repository.mark_resumed_from_wait(deps.run_id)

        ordinal = state["ledger"].records
        current_generation = state.get("generation") or deps.context.generation
        duration_ms = (perf_counter() - started) * 1000
        set_id_attribute(span, ATTR_INGESTION_WAITED_SECONDS, duration_ms / 1000)
        update: dict[str, Any] = {}
        if request.status not in _TERMINAL:
            set_id_attribute(span, ATTR_INGESTION_STATUS, "wait_cap")
            observation = ToolObservation(
                ordinal=ordinal,
                tool="ingestion_wait",
                arguments={"request_id": raw_request_id},
                status="failed",
                summary={
                    "request_id": raw_request_id,
                    "pending_paper_ids": list(request.paper_ids),
                },
                error_category="ingestion_wait_cap",
                duration_ms=duration_ms,
            )
            update = await record_observation(deps, state, observation)
        else:
            generation = request.result.get("generation")
            snapshot = request.result.get("snapshot_id")
            outcomes = request.result.get("outcomes", [])
            summary: dict[str, Any] = {
                "request_id": raw_request_id,
                "status": request.status,
                "from_generation": current_generation,
                "to_generation": current_generation,
                "outcomes": outcomes if isinstance(outcomes, list) else [],
            }
            switch = (
                isinstance(generation, int)
                and isinstance(snapshot, str)
                and (current_generation is None or generation > current_generation)
            )
            if switch:
                set_id_attribute(span, ATTR_INGESTION_STATUS, "switched")
                assert isinstance(generation, int)
                set_id_attribute(span, ATTR_GENERATION, generation)
                summary["to_generation"] = generation
            else:
                set_id_attribute(span, ATTR_INGESTION_STATUS, request.status)
            observation = ToolObservation(
                ordinal=ordinal,
                tool="ingestion_wait",
                arguments={"request_id": raw_request_id},
                status="succeeded",
                summary=summary,
                duration_ms=duration_ms,
            )
            if switch:
                assert isinstance(generation, int) and isinstance(snapshot, str)
                await deps.repository.switch_generation(
                    deps.run_id,
                    generation=generation,
                    snapshot_id=UUID(snapshot),
                    record=ToolCallRecord(
                        ordinal=observation.ordinal,
                        tool_name=observation.tool,
                        arguments=observation.arguments,
                        status=observation.status,
                        result_summary=observation.summary,
                        duration_ms=observation.duration_ms,
                    ),
                )
                ledger = state["ledger"].model_copy(
                    update={"records": state["ledger"].records + 1}
                )
                update = {
                    "ledger": ledger,
                    "observations": [
                        *state["observations"],
                        format_observation(observation, ()),
                    ][-20:],
                    "generation": generation,
                    "snapshot_id": snapshot,
                }
            else:
                update = await record_observation(deps, state, observation)
        return {
            **update,
            "pending_ingestion_request_id": None,
            "ingestion_waits": state.get("ingestion_waits", 0) + 1,
        }

    async def evaluate(state: ResearchState) -> dict[str, Any]:
        if (
            state["plan_round"] >= budgets.max_plan_rounds
            or remaining_actions(state, budgets) == 0
        ):
            return {"sufficient": True, "pending_actions": []}

        stored = await deps.repository.load_evidence(
            deps.run_id, [ref.handle for ref in state["registry"].refs]
        )
        valid_refs = tuple(
            ref
            for ref in state["registry"].refs
            if (record := stored.get(ref.handle)) is not None
            and record.chunk_id == ref.chunk_id
            and record.text.strip()
        )
        texts = {ref.chunk_id: stored[ref.handle].text for ref in valid_refs}
        packed = pack_evidence(
            valid_refs,
            texts,
            max_tokens=budgets.max_synthesis_tokens // 2,
        )
        try:
            result = await deps.llm.generate(
                StructuredCall(
                    kind=CallKind.EVALUATE,
                    messages=evaluate_messages(
                        question=state["question"],
                        observations=state["observations"][-20:],
                        packed=packed,
                        rounds_left=budgets.max_plan_rounds - state["plan_round"],
                        max_actions=remaining_actions(state, budgets),
                    ),
                    output_model=SufficiencyDecision,
                    think=CallKind.EVALUATE in deps.thinking,
                    max_output_tokens=768,
                    max_repair_attempts=budgets.max_model_retries,
                )
            )
        except LLMInvalidOutput:
            return {
                "sufficient": True,
                "pending_actions": [],
                "model_calls": state["model_calls"] + 1,
                "observations": [
                    *state["observations"],
                    "evaluate fallback: answering with current evidence",
                ][-20:],
            }

        decision = result.value
        if decision.sufficient:
            return {
                "sufficient": True,
                "pending_actions": [],
                "missing": decision.missing,
                "model_calls": state["model_calls"] + 1,
            }

        max_actions = remaining_actions(state, budgets)
        actions = decision.next_actions[:max_actions]
        return {
            "sufficient": False,
            "missing": decision.missing,
            "pending_actions": [action.model_dump(mode="json") for action in actions],
            "plan_round": state["plan_round"] + 1,
            "model_calls": state["model_calls"] + 1,
        }

    async def answer(state: ResearchState) -> dict[str, Any]:
        return await answer_node(deps, state)

    def after_plan(state: ResearchState) -> str:
        return "answer" if not state["pending_actions"] else "execute"

    def after_execute(state: ResearchState) -> str:
        return (
            "wait_ingestion"
            if state.get("pending_ingestion_request_id") is not None
            else "evaluate"
        )

    def after_evaluate(state: ResearchState) -> str:
        return (
            "answer"
            if state["sufficient"] or not state["pending_actions"]
            else "execute"
        )

    builder = StateGraph(ResearchState)
    builder.add_node("plan", cast(Any, traced_node("plan", plan)))
    builder.add_node("execute", cast(Any, traced_node("execute", execute)))
    builder.add_node("evaluate", cast(Any, traced_node("evaluate", evaluate)))
    builder.add_node(
        "wait_ingestion", cast(Any, traced_node("wait_ingestion", wait_ingestion))
    )
    builder.add_node("answer", cast(Any, traced_node("answer", answer)))
    builder.add_edge(START, "plan")
    builder.add_conditional_edges("plan", after_plan)
    builder.add_conditional_edges("execute", after_execute)
    builder.add_edge("wait_ingestion", "evaluate")
    builder.add_conditional_edges("evaluate", after_evaluate)
    builder.add_edge("answer", END)
    return builder
