"""Budgeted plan, execute, and evaluate graph for deep research runs."""

from __future__ import annotations

from typing import Any, cast

from langgraph.graph import END, START, StateGraph
from pydantic import TypeAdapter

from research_platform.agents.actions import Action, SufficiencyDecision
from research_platform.agents.evidence import pack_evidence
from research_platform.agents.nodes import NodeDependencies, answer_node, run_action
from research_platform.agents.prompts import evaluate_messages, plan_messages
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
from research_platform.runs.contracts import ResearchFilters, RunBudgets

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
        for raw_action in state["pending_actions"]:
            action_state = cast(ResearchState, {**state, **current})
            if remaining_actions(action_state, budgets) == 0:
                break
            action = _ACTION_ADAPTER.validate_python(raw_action)
            update = await run_action(deps, action_state, action)
            current.update(update)

        return {**current, "pending_actions": []}

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

    def after_evaluate(state: ResearchState) -> str:
        return (
            "answer"
            if state["sufficient"] or not state["pending_actions"]
            else "execute"
        )

    builder = StateGraph(ResearchState)
    builder.add_node("plan", plan)
    builder.add_node("execute", execute)
    builder.add_node("evaluate", evaluate)
    builder.add_node("answer", answer)
    builder.add_edge(START, "plan")
    builder.add_conditional_edges("plan", after_plan)
    builder.add_edge("execute", "evaluate")
    builder.add_conditional_edges("evaluate", after_evaluate)
    builder.add_edge("answer", END)
    return builder
