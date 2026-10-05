"""Execute persisted research runs through checkpointed LangGraph workflows."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, cast
from uuid import UUID

import asyncpg  # type: ignore[import-untyped]
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.errors import GraphRecursionError
from langgraph.graph import StateGraph

from research_platform.agents.nodes import (
    IngestionStatusSource,
    NodeDependencies,
    ToolStepFailed,
)
from research_platform.agents.prompts import PROMPT_VERSIONS
from research_platform.agents.state import ResearchState, initial_state
from research_platform.config import Settings
from research_platform.ingestion.generation_index import GenerationIndexConfiguration
from research_platform.ingestion.generation_registry import GenerationRegistry
from research_platform.llm.contracts import (
    LLMClient,
    LLMInvalidOutput,
    LLMRequestRejected,
    LLMTimeout,
    LLMUnavailable,
)
from research_platform.llm.types import CallKind, ModelIdentity
from research_platform.runs.checkpointing import thread_config
from research_platform.runs.contracts import (
    UNINGESTED_SIMILARITY_THRESHOLD,
    FailureCategory,
    ResearchMode,
    ResearchRequest,
    RunBudgets,
    RunProvenance,
    RunStatus,
    RunUsage,
    configuration_id,
)
from research_platform.runs.store import RunStore
from research_platform.search.active_profile import resolve_frozen_profile_path
from research_platform.search.profile_manifest import load_frozen_profile
from research_platform.tools.research_tools import ResearchTools, ToolContext

logger = logging.getLogger(__name__)

_PROVENANCE_CALL_KINDS = (
    CallKind.PLAN,
    CallKind.EVALUATE,
    CallKind.SYNTHESIZE,
)


@dataclass(frozen=True)
class ServingIdentity:
    """Snapshot and frozen retrieval profile used for a newly accepted run."""

    snapshot_id: UUID
    retrieval_profile_id: str
    generation: int | None = None
    retrieval_settings_id: str | None = None


def load_serving_identity(path: Path | None = None) -> ServingIdentity:
    """Load the effective frozen serving profile identity."""
    profile_path = resolve_frozen_profile_path(path)
    profile = load_frozen_profile(profile_path)
    return ServingIdentity(
        snapshot_id=profile.snapshot.snapshot_id,
        retrieval_profile_id=profile.profile_id,
    )


async def resolve_serving_identity(
    settings: Settings, pool: asyncpg.Pool, path: Path | None = None
) -> ServingIdentity:
    """The serving identity; with Qdrant content, the published generation's snapshot."""
    profile = load_frozen_profile(resolve_frozen_profile_path(path))
    if settings.content_source != "qdrant":
        return ServingIdentity(
            snapshot_id=profile.snapshot.snapshot_id,
            retrieval_profile_id=profile.profile_id,
        )
    raw = json.loads(settings.generation_configuration.read_text(encoding="utf-8"))
    configuration = GenerationIndexConfiguration.from_dict(raw)
    registry = GenerationRegistry(pool)
    collection_id = await registry.ensure_collection(settings.generation_collection)
    published = await registry.published(collection_id, configuration.configuration_id)
    if published is None:
        raise RuntimeError("the generation collection has no published generation")
    return ServingIdentity(
        snapshot_id=published.snapshot_id,
        retrieval_profile_id=profile.profile_id,
        generation=published.generation,
        retrieval_settings_id=profile.settings_id,
    )


def build_provenance(
    *,
    run_id: UUID,
    request: ResearchRequest,
    serving: ServingIdentity,
    model: ModelIdentity,
    thinking: frozenset[CallKind],
    budgets: RunBudgets,
    code_revision: str,
) -> RunProvenance:
    """Build stable provenance for the effective run configuration."""
    snapshot_id = request.snapshot_id or serving.snapshot_id
    thinking_map = {kind: kind in thinking for kind in _PROVENANCE_CALL_KINDS}
    prompt_versions = dict(PROMPT_VERSIONS)
    effective_configuration: dict[str, object] = {
        "mode": request.mode.value,
        "filters": request.filters.model_dump(mode="json"),
        "snapshot_id": str(snapshot_id),
        "retrieval_profile_id": serving.retrieval_profile_id,
        "budgets": budgets.model_dump(mode="json"),
        "model": model.model_dump(mode="json"),
        "thinking": {kind.value: enabled for kind, enabled in thinking_map.items()},
        "prompt_versions": prompt_versions,
        "code_revision": code_revision,
    }
    if serving.generation is not None:
        effective_configuration["generation"] = serving.generation
        effective_configuration["retrieval_settings_id"] = serving.retrieval_settings_id
    diagnostic_threshold = (
        UNINGESTED_SIMILARITY_THRESHOLD if request.mode is ResearchMode.QUICK else None
    )
    if diagnostic_threshold is not None:
        effective_configuration["uningested_similarity_threshold"] = (
            diagnostic_threshold
        )
    return RunProvenance(
        snapshot_id=snapshot_id,
        retrieval_profile_id=serving.retrieval_profile_id,
        configuration_id=configuration_id(effective_configuration),
        code_revision=code_revision,
        model=model,
        thinking=thinking_map,
        prompt_versions=prompt_versions,
        budgets=budgets,
        trace_id=str(run_id),
        generation=serving.generation,
        retrieval_settings_id=serving.retrieval_settings_id,
        uningested_similarity_threshold=diagnostic_threshold,
    )


def classify_failure(error: BaseException) -> FailureCategory:
    """Map expected graph and adapter failures to stable run categories."""
    if isinstance(error, (LLMUnavailable, LLMRequestRejected)):
        return FailureCategory.MODEL_UNAVAILABLE
    if isinstance(error, (LLMTimeout, TimeoutError)):
        return FailureCategory.TIMEOUT
    if isinstance(error, LLMInvalidOutput):
        return FailureCategory.INVALID_MODEL_OUTPUT
    if isinstance(error, ToolStepFailed):
        if error.error_category in {
            "retrieval_error",
            "access_denied",
            "invalid_argument",
        }:
            return FailureCategory.RETRIEVAL_ERROR
        return FailureCategory.INTERNAL
    if isinstance(error, GraphRecursionError):
        return FailureCategory.BUDGET_EXHAUSTED
    return FailureCategory.INTERNAL


GraphBuilder = Callable[
    [NodeDependencies], StateGraph[ResearchState, None, ResearchState, ResearchState]
]


@dataclass(frozen=True)
class RunnerDependencies:
    """Services and effective configuration required to execute research runs."""

    repository: RunStore
    tools: ResearchTools
    llm: LLMClient
    checkpointer: BaseCheckpointSaver[Any]
    serving: ServingIdentity
    thinking: frozenset[CallKind]
    code_revision: str
    graphs: Mapping[ResearchMode, GraphBuilder]
    budgets: RunBudgets = field(default_factory=RunBudgets.model_construct)
    clock: Callable[[], float] = time.monotonic
    ingestion: IngestionStatusSource | None = None
    serving_resolver: Callable[[], Awaitable[ServingIdentity]] | None = None


class _ActivePauses:
    """Excludes paused intervals from active time and from the active deadline."""

    def __init__(self, clock: Callable[[], float]) -> None:
        self._clock = clock
        self.paused_seconds = 0.0
        self.timeout: asyncio.Timeout | None = None

    @asynccontextmanager
    async def pause(self) -> AsyncIterator[None]:
        loop = asyncio.get_running_loop()
        started, loop_started = self._clock(), loop.time()
        deadline = None if self.timeout is None else self.timeout.when()
        if self.timeout is not None:
            self.timeout.reschedule(None)
        try:
            yield
        finally:
            self.paused_seconds += max(0.0, self._clock() - started)
            if self.timeout is not None and deadline is not None:
                self.timeout.reschedule(deadline + (loop.time() - loop_started))


class ResearchRunner:
    """Run and persist one queued or interrupted research workflow."""

    def __init__(self, deps: RunnerDependencies) -> None:
        self._deps = deps

    async def run(self, run_id: UUID) -> RunStatus:
        """Execute a run or return its existing terminal state."""
        stored = await self._deps.repository.get_run(run_id)
        if stored.status in (RunStatus.COMPLETED, RunStatus.FAILED):
            self._log_finished(
                run_id,
                stored.mode,
                stored.status,
                None,
                0.0,
                stored.active_seconds,
                RunUsage.model_construct(
                    active_seconds=stored.active_seconds, resumes=stored.resume_count
                ),
            )
            return stored.status

        resuming = stored.status in (
            RunStatus.RUNNING,
            RunStatus.WAITING_FOR_INGESTION,
        )
        resume_count = stored.resume_count
        if resuming:
            resume_count = await self._deps.repository.record_resume(run_id)
            if resume_count > self._deps.budgets.max_resumes:
                return await self._fail_early(
                    run_id,
                    stored.mode,
                    FailureCategory.RESUME_EXHAUSTED,
                    "ResumeLimitExceeded",
                    RunUsage.model_construct(
                        active_seconds=stored.active_seconds,
                        resumes=resume_count,
                    ),
                    stored.active_seconds,
                )

        graph: Any | None = None
        config: RunnableConfig | None = None
        accumulated_seconds = stored.active_seconds
        started = self._deps.clock()
        execution_seconds = 0.0
        active_started = False
        pauses = _ActivePauses(self._deps.clock)
        serving = self._deps.serving
        if not resuming and self._deps.serving_resolver is not None:
            # A new run pins the generation published when it starts.
            serving = await self._deps.serving_resolver()
        if resuming and stored.pinned_snapshot_id is not None:
            # A resumed run keeps the identity it started with, even after a
            # newer generation was published or the run switched generations.
            serving = replace(
                serving,
                snapshot_id=stored.pinned_snapshot_id,
                generation=stored.pinned_generation,
            )
        try:
            model = await self._deps.llm.identity()
            provenance = build_provenance(
                run_id=run_id,
                request=stored.request,
                serving=serving,
                model=model,
                thinking=self._deps.thinking,
                budgets=self._deps.budgets,
                code_revision=self._deps.code_revision,
            )
            if resuming and stored.configuration_id != provenance.configuration_id:
                return await self._fail_early(
                    run_id,
                    stored.mode,
                    FailureCategory.CONFIGURATION_CHANGED,
                    "ConfigurationChanged",
                    RunUsage.model_construct(
                        active_seconds=stored.active_seconds,
                        resumes=resume_count,
                    ),
                    stored.active_seconds,
                )

            await self._deps.repository.mark_running(run_id, provenance=provenance)
            remaining = self._deps.budgets.max_active_seconds - stored.active_seconds
            if remaining <= 0:
                return await self._fail_early(
                    run_id,
                    stored.mode,
                    FailureCategory.TIMEOUT,
                    "ActiveTimeBudgetExceeded",
                    RunUsage.model_construct(
                        active_seconds=stored.active_seconds,
                        resumes=resume_count,
                    ),
                    stored.active_seconds,
                )

            context = ToolContext(
                run_id=run_id,
                snapshot_id=provenance.snapshot_id,
                retrieval_profile_id=provenance.retrieval_profile_id,
                mode=stored.mode,
                question=stored.request.question,
                generation=provenance.generation,
                filters=stored.request.filters,
                budgets=self._deps.budgets,
            )
            node_deps = NodeDependencies(
                run_id=run_id,
                tools=self._deps.tools,
                llm=self._deps.llm,
                repository=self._deps.repository,
                context=context,
                thinking=self._deps.thinking,
                ingestion=self._deps.ingestion,
                pause_active=pauses.pause,
            )
            graph_builder = self._deps.graphs[stored.mode]
            graph = graph_builder(node_deps).compile(
                checkpointer=self._deps.checkpointer
            )
            config = cast(
                RunnableConfig,
                thread_config(run_id) | {"recursion_limit": 50},
            )
            checkpoint = await self._deps.checkpointer.aget_tuple(config)
            graph_input: ResearchState | None = (
                None
                if checkpoint is not None
                else initial_state(stored.request.question)
            )

            started = self._deps.clock()
            active_started = True
            try:
                async with asyncio.timeout(remaining) as timeout:
                    pauses.timeout = timeout
                    final_state = await graph.ainvoke(
                        graph_input, config, durability="sync"
                    )
            finally:
                pauses.timeout = None
                elapsed = max(0.0, self._deps.clock() - started - pauses.paused_seconds)
                execution_seconds = elapsed
                accumulated_seconds = await self._deps.repository.add_active_seconds(
                    run_id, elapsed
                )
                active_started = False

            answer = final_state["answer"]
            if answer is None:
                raise RuntimeError("research graph finished without an answer")
            usage = _usage_from_state(
                final_state,
                active_seconds=accumulated_seconds,
                resumes=resume_count,
            )
            await self._deps.repository.complete_run(
                run_id,
                answer=answer.answer,
                outcome=answer.outcome,
                claims=answer.claims,
                usage=usage,
            )
            status = RunStatus.COMPLETED
            category = None
            self._log_finished(
                run_id,
                stored.mode,
                status,
                category,
                execution_seconds,
                accumulated_seconds,
                usage,
            )
            return status
        except asyncio.CancelledError:
            if active_started:
                elapsed = max(0.0, self._deps.clock() - started - pauses.paused_seconds)
                await self._deps.repository.add_active_seconds(run_id, elapsed)
            raise
        except Exception as error:
            if active_started:
                elapsed = max(0.0, self._deps.clock() - started - pauses.paused_seconds)
                execution_seconds = elapsed
                accumulated_seconds = await self._deps.repository.add_active_seconds(
                    run_id, elapsed
                )
            state_values = await _latest_state(graph, config)
            usage = _usage_from_state(
                state_values,
                active_seconds=accumulated_seconds,
                resumes=resume_count,
            )
            category = classify_failure(error)
            await self._deps.repository.fail_run(
                run_id,
                category=category,
                message=_safe_error_message(error),
                usage=usage,
            )
            self._log_finished(
                run_id,
                stored.mode,
                RunStatus.FAILED,
                category,
                execution_seconds,
                accumulated_seconds,
                usage,
            )
            return RunStatus.FAILED

    async def _fail_early(
        self,
        run_id: UUID,
        mode: ResearchMode,
        category: FailureCategory,
        message: str,
        usage: RunUsage,
        active_seconds: float,
    ) -> RunStatus:
        await self._deps.repository.fail_run(
            run_id, category=category, message=message, usage=usage
        )
        self._log_finished(
            run_id, mode, RunStatus.FAILED, category, 0.0, active_seconds, usage
        )
        return RunStatus.FAILED

    @staticmethod
    async def _latest_state(
        graph: Any | None, config: RunnableConfig | None
    ) -> dict[str, Any]:
        if graph is None or config is None:
            return {}
        try:
            snapshot = await graph.aget_state(config)
        except Exception:
            return {}
        return snapshot.values if isinstance(snapshot.values, dict) else {}

    @staticmethod
    def _log_finished(
        run_id: UUID,
        mode: ResearchMode,
        status: RunStatus,
        category: FailureCategory | None,
        duration_seconds: float,
        active_seconds: float,
        usage: RunUsage,
    ) -> None:
        logger.info(
            "research_run_finished",
            extra={
                "run_id": str(run_id),
                "mode": mode.value,
                "status": status.value,
                "failure_category": category.value if category else None,
                "duration_seconds": round(duration_seconds, 3),
                "active_seconds": round(active_seconds, 3),
                "tool_calls": usage.tool_calls,
                "model_calls": usage.model_calls,
                "plan_rounds": usage.plan_rounds,
                "resumes": usage.resumes,
            },
        )


async def _latest_state(
    graph: Any | None, config: RunnableConfig | None
) -> dict[str, Any]:
    return await ResearchRunner._latest_state(graph, config)


def _usage_from_state(
    values: Mapping[str, Any], *, active_seconds: float, resumes: int
) -> RunUsage:
    ledger = values.get("ledger")
    answer = values.get("answer")
    return RunUsage.model_construct(
        plan_rounds=_nonnegative_int(values.get("plan_round")),
        tool_calls=_nonnegative_int(getattr(ledger, "tool_calls_used", 0)),
        model_calls=_nonnegative_int(values.get("model_calls")),
        active_seconds=max(0.0, active_seconds),
        resumes=max(0, resumes),
        rejected_claims=_nonnegative_int(getattr(answer, "rejected_claims", 0)),
        unsupported_claims=_nonnegative_int(getattr(answer, "unsupported_claims", 0)),
    )


def _nonnegative_int(value: object) -> int:
    return (
        value
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0
        else 0
    )


def _safe_error_message(error: Exception) -> str:
    if isinstance(error, LLMInvalidOutput):
        return f"LLMInvalidOutput after {error.attempts} attempts"
    return type(error).__name__
