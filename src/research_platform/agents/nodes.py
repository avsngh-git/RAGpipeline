"""Shared node helpers for the bounded research graphs."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Mapping
from contextlib import AbstractAsyncContextManager, nullcontext
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID

from opentelemetry.trace import Status, StatusCode

from research_platform.agents.actions import Action
from research_platform.agents.answering import answer_question
from research_platform.agents.evidence import EvidenceRegistry
from research_platform.agents.prompts import format_observation
from research_platform.agents.state import ResearchState
from research_platform.llm.contracts import LLMClient
from research_platform.llm.types import CallKind
from research_platform.observability.metrics import TOOL_CALLS, TOOL_LATENCY
from research_platform.observability.tracing import (
    ATTR_NODE,
    ATTR_TOOL_ARGUMENTS,
    ATTR_TOOL_ERROR_CATEGORY,
    ATTR_TOOL_NAME,
    ATTR_TOOL_NEW_EVIDENCE,
    ATTR_TOOL_ORDINAL,
    ATTR_TOOL_PAPER_IDS,
    ATTR_TOOL_RESULT_IDS,
    ATTR_TOOL_STATUS,
    LF_LEVEL,
    get_tracer,
    set_id_attribute,
    set_text_attribute,
)
from research_platform.runs.repository import EvidenceRecord, ToolCallRecord
from research_platform.runs.store import RunStore
from research_platform.tools.research_tools import (
    ResearchTools,
    ToolContext,
    ToolObservation,
)
from research_platform.worker.queue import IngestionRequest


class IngestionStatusSource(Protocol):
    """Reads an ingestion request's status and result."""

    async def get(self, request_id: UUID) -> IngestionRequest: ...


def _no_pause() -> AbstractAsyncContextManager[None]:
    return nullcontext()


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class NodeDependencies:
    """Services and run-specific settings used by graph nodes."""

    run_id: UUID
    tools: ResearchTools
    llm: LLMClient
    repository: RunStore
    context: ToolContext
    thinking: frozenset[CallKind]
    ingestion: IngestionStatusSource | None = None
    pause_active: Callable[[], AbstractAsyncContextManager[None]] = _no_pause
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep
    now: Callable[[], datetime] = field(default=_utc_now)


def effective_context(deps: NodeDependencies, state: ResearchState) -> ToolContext:
    """The run's tool context, moved to a newer generation after a switch."""
    generation = state.get("generation")
    snapshot_id = state.get("snapshot_id")
    if generation is None or snapshot_id is None:
        return deps.context
    return deps.context.model_copy(
        update={"generation": generation, "snapshot_id": UUID(snapshot_id)}
    )


class ToolStepFailed(RuntimeError):
    """A required search step failed with a known tool error category."""

    def __init__(self, error_category: str) -> None:
        super().__init__(error_category)
        self.error_category = error_category


NodeFunction = Callable[[ResearchState], Awaitable[dict[str, Any]]]


def traced_node(name: str, node: NodeFunction) -> NodeFunction:
    """Run a graph node inside a span named node.<name>."""

    async def wrapper(state: ResearchState) -> dict[str, Any]:
        with get_tracer().start_as_current_span(f"node.{name}") as span:
            span.set_attribute(ATTR_NODE, name)
            return await node(state)

    return wrapper


def _annotate_tool_span(
    span: Any, observation: ToolObservation, new_refs: tuple[Any, ...]
) -> None:
    span.set_attribute(ATTR_TOOL_NAME, observation.tool)
    span.set_attribute(ATTR_TOOL_ORDINAL, observation.ordinal)
    span.set_attribute(ATTR_TOOL_STATUS, observation.status)
    if observation.error_category is not None:
        span.set_attribute(ATTR_TOOL_ERROR_CATEGORY, observation.error_category)

    paper_ids: list[str] = []
    for key in ("paper_id", "paper_ids"):
        value = observation.arguments.get(key)
        if isinstance(value, str):
            paper_ids.append(value)
        elif isinstance(value, (list, tuple)):
            paper_ids.extend(item for item in value if isinstance(item, str))
    set_id_attribute(span, ATTR_TOOL_PAPER_IDS, paper_ids)

    chunks = observation.summary.get("chunks")
    papers = observation.summary.get("papers")
    rows = chunks if isinstance(chunks, list) else papers
    id_key = "chunk_id" if isinstance(chunks, list) else "paper_id"
    result_ids = [
        row[id_key]
        for row in rows or []
        if isinstance(row, Mapping) and isinstance(row.get(id_key), str)
    ][:50]
    set_id_attribute(span, ATTR_TOOL_RESULT_IDS, result_ids)
    set_id_attribute(
        span,
        ATTR_TOOL_NEW_EVIDENCE,
        [ref.handle for ref in new_refs],
    )
    set_text_attribute(
        span,
        ATTR_TOOL_ARGUMENTS,
        json.dumps(observation.arguments, sort_keys=True, default=str),
    )
    if observation.status == "rejected":
        span.set_attribute(LF_LEVEL, "WARNING")
    elif observation.status == "failed":
        span.set_attribute(LF_LEVEL, "ERROR")
        span.set_status(Status(StatusCode.ERROR))


def to_tool_call_record(observation: ToolObservation) -> ToolCallRecord:
    """Map one tool observation to its text-free persisted record."""
    return ToolCallRecord(
        ordinal=observation.ordinal,
        tool_name=observation.tool,
        arguments=observation.arguments,
        status=observation.status,
        result_summary=observation.summary,
        duration_ms=observation.duration_ms,
        error_category=observation.error_category,
    )


async def _run_action(
    deps: NodeDependencies, state: ResearchState, action: Action
) -> tuple[dict[str, Any], ToolObservation]:
    with get_tracer().start_as_current_span(f"tool.{action.tool}") as span:
        observation, ledger = await deps.tools.execute(
            action, context=effective_context(deps, state), ledger=state["ledger"]
        )
        TOOL_CALLS.labels(observation.tool, observation.status).inc()
        TOOL_LATENCY.labels(observation.tool).observe(observation.duration_ms / 1000)
        registry, new_refs = state["registry"].register(
            observation.evidence,
            max_passages=deps.context.budgets.max_evidence_passages,
        )

        await deps.repository.append_tool_call(
            deps.run_id, to_tool_call_record(observation)
        )
        evidence_by_chunk = {item.chunk_id: item for item in observation.evidence}
        records: list[EvidenceRecord] = []
        for ref in new_refs:
            item = evidence_by_chunk[ref.chunk_id]
            records.append(
                EvidenceRecord(
                    handle=ref.handle,
                    chunk_id=ref.chunk_id,
                    paper_id=ref.paper_id,
                    text=item.text,
                    metadata={
                        "title": item.title,
                        "publication_year": item.publication_year,
                        "kind": item.kind,
                        "source_location": item.source_location,
                    },
                )
            )
        await deps.repository.save_evidence(deps.run_id, records)
        _annotate_tool_span(span, observation, new_refs)

        line = format_observation(observation, new_refs)
        return (
            {
                "ledger": ledger,
                "registry": registry,
                "observations": [*state["observations"], line][-20:],
            },
            observation,
        )


async def run_action(
    deps: NodeDependencies, state: ResearchState, action: Action
) -> dict[str, Any]:
    """Run and persist one action, adding only bounded model-facing history."""
    update, _ = await _run_action(deps, state, action)
    return update


async def run_action_observed(
    deps: NodeDependencies, state: ResearchState, action: Action
) -> tuple[dict[str, Any], ToolObservation]:
    """Like ``run_action``, also returning the observation."""
    return await _run_action(deps, state, action)


async def record_observation(
    deps: NodeDependencies, state: ResearchState, observation: ToolObservation
) -> dict[str, Any]:
    """Persist an observation produced outside the tools; it adds no evidence."""
    with get_tracer().start_as_current_span(f"tool.{observation.tool}") as span:
        await deps.repository.append_tool_call(
            deps.run_id, to_tool_call_record(observation)
        )
        TOOL_CALLS.labels(observation.tool, observation.status).inc()
        TOOL_LATENCY.labels(observation.tool).observe(observation.duration_ms / 1000)
        ledger = state["ledger"].model_copy(
            update={"records": state["ledger"].records + 1}
        )
        line = format_observation(observation, ())
        _annotate_tool_span(span, observation, ())
        return {
            "ledger": ledger,
            "observations": [*state["observations"], line][-20:],
        }


async def answer_node(deps: NodeDependencies, state: ResearchState) -> dict[str, Any]:
    """Load run-owned text and return the verified answer for this state."""
    refs = state["registry"].refs
    stored = await deps.repository.load_evidence(
        deps.run_id, [ref.handle for ref in refs]
    )
    valid_refs = tuple(
        ref
        for ref in refs
        if (record := stored.get(ref.handle)) is not None
        and record.chunk_id == ref.chunk_id
        and record.text.strip()
    )
    texts = {ref.chunk_id: stored[ref.handle].text for ref in valid_refs}
    answer_registry = EvidenceRegistry(
        refs=valid_refs, dropped=state["registry"].dropped
    )
    answer = await answer_question(
        deps.llm,
        question=state["question"],
        registry=answer_registry,
        texts=texts,
        budgets=deps.context.budgets,
        thinking=deps.thinking,
    )
    return {"answer": answer, "model_calls": state["model_calls"] + answer.model_calls}
