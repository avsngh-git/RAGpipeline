"""Offline coverage for the quick graph and research run lifecycle."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from uuid import UUID

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from research_platform.agents.graph_quick import build_quick_graph
from research_platform.agents.nodes import ToolStepFailed
from research_platform.llm.contracts import (
    LLMInvalidOutput,
    LLMRequestRejected,
    LLMTimeout,
    LLMUnavailable,
    StructuredCall,
    ToolCallRequest,
    ToolCallResult,
)
from research_platform.llm.scripted import ScriptedLLM, ScriptedReply
from research_platform.llm.types import CallKind, ModelIdentity
from research_platform.runs.contracts import (
    AnswerOutcome,
    FailureCategory,
    ResearchFilters,
    ResearchMode,
    ResearchRequest,
    RunBudgets,
    RunStatus,
    RunUsage,
)
from research_platform.runs.memory import InMemoryRunStore
from research_platform.runs.repository import (
    InvalidRunTransition,
    ToolCallRecord,
)
from research_platform.runs.runner import (
    ResearchRunner,
    RunnerDependencies,
    ServingIdentity,
    build_provenance,
    classify_failure,
)
from research_platform.tools.fakes import (
    FakeCorpus,
    FakePaper,
    FakePassage,
    fake_services,
)
from research_platform.tools.research_tools import ResearchTools

_SNAPSHOT = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
_PROFILE = "sha256:" + "a" * 64
_IDENTITY = ModelIdentity(name="scripted", runtime="scripted", context_tokens=8192)
_SYNTHESIS = (
    '{"relevant_handles":["E1"],"insufficient_evidence":false,'
    '"claims":[{"handle":"E1","quote":"retrieval improves ranking",'
    '"text":"Retrieval improves ranking"}],"answer":"Retrieval improves ranking [E1]"}'
)
_SUCCESS = (ScriptedReply(kind=CallKind.SYNTHESIZE, content=_SYNTHESIS),)


class RecordingStore(InMemoryRunStore):
    """Record calls while retaining the in-memory store semantics."""

    def __init__(self) -> None:
        super().__init__()
        self.tool_records: list[ToolCallRecord] = []

    async def append_tool_call(self, run_id: UUID, record: ToolCallRecord) -> None:
        self.tool_records.append(record)
        await super().append_tool_call(run_id, record)


class BlockOnceLLM:
    """Block the first answer so the calling task can be cancelled externally."""

    def __init__(self, replies: Sequence[ScriptedReply]) -> None:
        self.script = ScriptedLLM(replies, identity=_IDENTITY)
        self.block = True
        self.started = asyncio.Event()

    async def identity(self) -> ModelIdentity:
        return await self.script.identity()

    async def generate(self, call: StructuredCall):
        if self.block:
            self.block = False
            self.started.set()
            await asyncio.Future()
        return await self.script.generate(call)

    async def call_tools(self, request: ToolCallRequest) -> ToolCallResult:
        return await self.script.call_tools(request)


class IdentityFailureLLM:
    async def identity(self) -> ModelIdentity:
        raise LLMUnavailable("private adapter details")

    async def generate(self, call: StructuredCall):
        raise AssertionError("identity failure should happen before generation")

    async def call_tools(self, request: ToolCallRequest) -> ToolCallResult:
        raise AssertionError("quick graph never plans tool calls")


class FailingGenerateLLM(ScriptedLLM):
    """Convenience subclass retaining scripted identity with an injected reply."""


class StepClock:
    def __init__(self, step: float = 0.25) -> None:
        self.value = 0.0
        self.step = step

    def __call__(self) -> float:
        current = self.value
        self.value += self.step
        return current


def _corpus(*, fails: bool = False) -> FakeCorpus:
    return FakeCorpus(
        snapshot_id=_SNAPSHOT,
        papers=(FakePaper("W123", "Retrieval study", 2024),),
        passages=(FakePassage("chunk-1", "W123", "retrieval improves ranking"),),
        failing_queries=frozenset({"retrieval"}) if fails else frozenset(),
    )


def _request(*, mode: ResearchMode = ResearchMode.QUICK) -> ResearchRequest:
    return ResearchRequest(
        question="retrieval",
        mode=mode,
        filters=ResearchFilters(year_from=2020, year_to=2025),
    )


def _runner(
    store: InMemoryRunStore,
    llm,
    *,
    budgets: RunBudgets | None = None,
    corpus: FakeCorpus | None = None,
    clock=None,
) -> ResearchRunner:
    search, papers, citations, related = fake_services(corpus or _corpus())
    tools = ResearchTools(
        search=search, papers=papers, citations=citations, related=related
    )
    deps = RunnerDependencies(
        repository=store,
        tools=tools,
        llm=llm,
        checkpointer=InMemorySaver(),
        serving=ServingIdentity(_SNAPSHOT, _PROFILE),
        thinking=frozenset(),
        code_revision="test-revision",
        graphs={ResearchMode.QUICK: build_quick_graph},
        budgets=budgets or RunBudgets(),
        clock=clock or StepClock(),
    )
    return ResearchRunner(deps)


async def _create_run(store: InMemoryRunStore) -> UUID:
    return await store.create_run(_request())


async def _mark_running(
    store: InMemoryRunStore,
    run_id: UUID,
    *,
    request: ResearchRequest | None = None,
    code_revision: str = "test-revision",
    budgets: RunBudgets | None = None,
) -> None:
    provenance = build_provenance(
        run_id=run_id,
        request=request or _request(),
        serving=ServingIdentity(_SNAPSHOT, _PROFILE),
        model=_IDENTITY,
        thinking=frozenset(),
        budgets=budgets or RunBudgets(),
        code_revision=code_revision,
    )
    await store.mark_running(run_id, provenance=provenance)


@pytest.mark.anyio
async def test_in_memory_store_matches_repository_transitions() -> None:
    store = InMemoryRunStore()
    run_id = await _create_run(store)

    with pytest.raises(InvalidRunTransition):
        await store.complete_run(
            run_id,
            answer="not running",
            outcome=AnswerOutcome.ANSWERED,
            claims=(),
            usage=RunUsage(),
        )
    await store.fail_run(
        run_id,
        category=FailureCategory.MODEL_UNAVAILABLE,
        message="identity unavailable",
        usage=RunUsage(),
    )
    assert (await store.get_run_view(run_id)).status is RunStatus.FAILED
    with pytest.raises(InvalidRunTransition):
        await store.fail_run(
            run_id,
            category=FailureCategory.INTERNAL,
            message="terminal runs stay terminal",
            usage=RunUsage(),
        )

    running = await _create_run(store)
    await _mark_running(store, running)
    assert await store.record_resume(running) == 1
    assert await store.add_active_seconds(running, 1.25) == 1.25


@pytest.mark.anyio
async def test_quick_run_completes_and_persists_claims() -> None:
    store = RecordingStore()
    run_id = await _create_run(store)
    runner = _runner(store, ScriptedLLM(_SUCCESS, identity=_IDENTITY))

    assert await runner.run(run_id) is RunStatus.COMPLETED
    view = await store.get_run_view(run_id)

    assert view.status is RunStatus.COMPLETED
    assert view.answer_outcome is AnswerOutcome.ANSWERED
    assert view.claims[0].claim_id == "claim-1"
    assert view.claims[0].evidence[0].handle == "E1"
    assert view.papers[0].paper_id == "W123"
    assert [record.tool_name for record in store.tool_records] == [
        "search_papers",
        "search_evidence",
    ]


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (LLMUnavailable("offline"), FailureCategory.MODEL_UNAVAILABLE),
        (LLMRequestRejected("rejected"), FailureCategory.MODEL_UNAVAILABLE),
        (LLMTimeout("late"), FailureCategory.TIMEOUT),
        (TimeoutError(), FailureCategory.TIMEOUT),
        (
            LLMInvalidOutput("bad output", attempts=3, content_preview="private"),
            FailureCategory.INVALID_MODEL_OUTPUT,
        ),
        (
            ToolStepFailed("retrieval_error"),
            FailureCategory.RETRIEVAL_ERROR,
        ),
        (ToolStepFailed("access_denied"), FailureCategory.RETRIEVAL_ERROR),
        (ToolStepFailed("invalid_argument"), FailureCategory.RETRIEVAL_ERROR),
        (ToolStepFailed("unknown"), FailureCategory.INTERNAL),
        (RuntimeError("internal"), FailureCategory.INTERNAL),
    ],
)
def test_classify_failure_table(
    error: BaseException, expected: FailureCategory
) -> None:
    assert classify_failure(error) is expected


@pytest.mark.anyio
async def test_each_failure_category_is_persisted() -> None:
    cases: tuple[tuple[object, FakeCorpus, FailureCategory], ...] = (
        (IdentityFailureLLM(), _corpus(), FailureCategory.MODEL_UNAVAILABLE),
        (
            ScriptedLLM(
                (ScriptedReply(kind=CallKind.SYNTHESIZE, content="invalid json"),),
                identity=_IDENTITY,
            ),
            _corpus(),
            FailureCategory.INVALID_MODEL_OUTPUT,
        ),
        (
            ScriptedLLM(
                (ScriptedReply(kind=CallKind.SYNTHESIZE, error=LLMTimeout("late")),),
                identity=_IDENTITY,
            ),
            _corpus(),
            FailureCategory.TIMEOUT,
        ),
        (
            ScriptedLLM(_SUCCESS, identity=_IDENTITY),
            _corpus(fails=True),
            FailureCategory.RETRIEVAL_ERROR,
        ),
    )
    for llm, corpus, expected in cases:
        store = InMemoryRunStore()
        run_id = await _create_run(store)
        status = await _runner(store, llm, corpus=corpus).run(run_id)  # type: ignore[arg-type]
        view = await store.get_run_view(run_id)
        assert status is RunStatus.FAILED
        assert view.failure_category is expected
        assert view.error_message is not None
        assert "private" not in view.error_message


@pytest.mark.anyio
async def test_terminal_run_is_returned_unchanged() -> None:
    store = InMemoryRunStore()
    run_id = await _create_run(store)
    await store.fail_run(
        run_id,
        category=FailureCategory.INTERNAL,
        message="already failed",
        usage=RunUsage(),
    )
    llm = ScriptedLLM((), identity=_IDENTITY)

    assert await _runner(store, llm).run(run_id) is RunStatus.FAILED
    assert llm.calls == []


@pytest.mark.anyio
async def test_resume_continues_from_checkpoint_without_repeating_tools() -> None:
    store = RecordingStore()
    run_id = await _create_run(store)
    llm = BlockOnceLLM(_SUCCESS)
    runner = _runner(store, llm)

    task = asyncio.create_task(runner.run(run_id))
    await asyncio.wait_for(llm.started.wait(), timeout=2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert (await store.get_run(run_id)).status is RunStatus.RUNNING

    assert await runner.run(run_id) is RunStatus.COMPLETED
    assert [record.tool_name for record in store.tool_records] == [
        "search_papers",
        "search_evidence",
    ]
    assert (await store.get_run(run_id)).resume_count == 1


@pytest.mark.anyio
async def test_resume_limit_fails_with_resume_exhausted() -> None:
    store = InMemoryRunStore()
    budgets = RunBudgets(max_resumes=0)
    run_id = await _create_run(store)
    await _mark_running(store, run_id, budgets=budgets)

    status = await _runner(
        store, ScriptedLLM(_SUCCESS, identity=_IDENTITY), budgets=budgets
    ).run(run_id)

    assert status is RunStatus.FAILED
    assert (await store.get_run_view(run_id)).failure_category is (
        FailureCategory.RESUME_EXHAUSTED
    )


@pytest.mark.anyio
async def test_configuration_change_blocks_resume() -> None:
    store = InMemoryRunStore()
    run_id = await _create_run(store)
    await _mark_running(store, run_id, code_revision="old-revision")

    status = await _runner(store, ScriptedLLM(_SUCCESS, identity=_IDENTITY)).run(run_id)

    assert status is RunStatus.FAILED
    assert (await store.get_run_view(run_id)).failure_category is (
        FailureCategory.CONFIGURATION_CHANGED
    )


@pytest.mark.anyio
async def test_active_time_budget_counts_across_attempts() -> None:
    store = InMemoryRunStore()
    run_id = await _create_run(store)
    clock = StepClock(step=0.25)
    llm = BlockOnceLLM(_SUCCESS)
    runner = _runner(store, llm, clock=clock)

    task = asyncio.create_task(runner.run(run_id))
    await asyncio.wait_for(llm.started.wait(), timeout=2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    first_total = (await store.get_run(run_id)).active_seconds
    assert first_total == pytest.approx(0.25)

    assert await runner.run(run_id) is RunStatus.COMPLETED
    view = await store.get_run_view(run_id)
    assert view.usage.active_seconds == pytest.approx(0.5)
    assert view.usage.resumes == 1


@pytest.mark.anyio
async def test_cancellation_leaves_run_running() -> None:
    store = InMemoryRunStore()
    run_id = await _create_run(store)
    llm = BlockOnceLLM(_SUCCESS)
    runner = _runner(store, llm)

    task = asyncio.create_task(runner.run(run_id))
    await asyncio.wait_for(llm.started.wait(), timeout=2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert (await store.get_run(run_id)).status is RunStatus.RUNNING


def test_provenance_configuration_id_is_stable_for_same_inputs() -> None:
    request = _request()
    values = {
        "run_id": UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"),
        "request": request,
        "serving": ServingIdentity(_SNAPSHOT, _PROFILE),
        "model": _IDENTITY,
        "thinking": frozenset({CallKind.PLAN}),
        "budgets": RunBudgets(),
        "code_revision": "test-revision",
    }

    first = build_provenance(**values)
    second = build_provenance(**values)

    assert first.configuration_id == second.configuration_id
    assert first.trace_id == str(values["run_id"])
    assert first.snapshot_id == _SNAPSHOT


@pytest.mark.anyio
async def test_repository_failure_before_mark_running_is_persisted() -> None:
    store = InMemoryRunStore()
    run_id = await _create_run(store)

    status = await _runner(store, IdentityFailureLLM()).run(run_id)

    assert status is RunStatus.FAILED
    view = await store.get_run_view(run_id)
    assert view.failure_category is FailureCategory.MODEL_UNAVAILABLE
    assert (await store.get_run(run_id)).status is RunStatus.FAILED


def test_provenance_records_generation_and_settings_id() -> None:
    values = {
        "run_id": UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"),
        "request": _request(),
        "model": _IDENTITY,
        "thinking": frozenset({CallKind.PLAN}),
        "budgets": RunBudgets(),
        "code_revision": "test-revision",
    }
    plain = build_provenance(serving=ServingIdentity(_SNAPSHOT, _PROFILE), **values)
    pinned = build_provenance(
        serving=ServingIdentity(
            _SNAPSHOT,
            _PROFILE,
            generation=2,
            retrieval_settings_id="sha256:" + "f" * 64,
        ),
        **values,
    )

    assert (plain.generation, plain.retrieval_settings_id) == (None, None)
    assert pinned.generation == 2
    assert pinned.retrieval_settings_id == "sha256:" + "f" * 64
    assert pinned.configuration_id != plain.configuration_id


@pytest.mark.anyio
async def test_wait_time_not_counted_as_active() -> None:
    import json
    from datetime import UTC, datetime

    from research_platform.agents.graph_deep import build_deep_graph
    from research_platform.tools.fakes import FakeIngestionPolicy
    from research_platform.worker.queue import IngestionRequest

    class ManualClock:
        def __init__(self) -> None:
            self.value = 0.0

        def __call__(self) -> float:
            return self.value

    clock = ManualClock()

    class SlowQueue:
        """Each poll represents 100 seconds of waiting for the worker."""

        def __init__(self) -> None:
            self.polls = 0

        async def get(self, request_id: UUID) -> IngestionRequest:
            self.polls += 1
            clock.value += 100.0
            return IngestionRequest(
                request_id,
                UUID(int=1),
                None,
                "run",
                ("W501",),
                "succeeded" if self.polls >= 2 else "claimed",
                1,
                {"generation": 2, "snapshot_id": str(UUID(int=7)), "outcomes": []},
                created_at=datetime.now(UTC),
            )

    store = InMemoryRunStore()
    run_id = await store.create_run(_request(mode=ResearchMode.DEEP_RESEARCH))
    synthesis = (
        '{"relevant_handles":[],"insufficient_evidence":true,"claims":[],'
        '"answer":"Insufficient evidence."}'
    )
    llm = ScriptedLLM(
        (
            ScriptedReply(
                kind=CallKind.PLAN,
                tool_calls=(
                    {
                        "function": {
                            "name": "request_ingestion",
                            "arguments": {"paper_ids": ["W501"], "reason": "gap"},
                        }
                    },
                ),
            ),
            ScriptedReply(
                kind=CallKind.EVALUATE,
                content=json.dumps(
                    {"sufficient": True, "missing": "", "next_actions": []}
                ),
            ),
            ScriptedReply(kind=CallKind.SYNTHESIZE, content=synthesis),
        ),
        identity=_IDENTITY,
    )
    search, papers, citations, related = fake_services(_corpus())
    tools = ResearchTools(
        search=search,
        papers=papers,
        citations=citations,
        related=related,
        ingestion=FakeIngestionPolicy({"W501": (False, 2024, "en")}),
    )
    queue = SlowQueue()
    runner = ResearchRunner(
        RunnerDependencies(
            repository=store,
            tools=tools,
            llm=llm,
            checkpointer=InMemorySaver(),
            serving=ServingIdentity(_SNAPSHOT, _PROFILE, generation=1),
            thinking=frozenset(),
            code_revision="test-revision",
            graphs={ResearchMode.DEEP_RESEARCH: build_deep_graph},
            budgets=RunBudgets.model_construct(
                max_active_seconds=150.0, max_ingestion_wait_seconds=1.0
            ),
            clock=clock,
            ingestion=queue,
        )
    )

    assert await runner.run(run_id) is RunStatus.COMPLETED
    assert clock.value >= 200.0
    view = await store.get_run_view(run_id)
    assert view.usage.active_seconds == pytest.approx(0.0)
    assert view.generation == 2
