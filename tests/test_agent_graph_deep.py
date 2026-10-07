"""Offline integration coverage for the bounded deep-research graph."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import Any
from uuid import UUID

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from research_platform.agents.graph_deep import (
    build_deep_graph,
    default_actions,
    remaining_actions,
)
from research_platform.llm.contracts import (
    LLMClient,
    LLMUnavailable,
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
)
from research_platform.runs.memory import InMemoryRunStore
from research_platform.runs.repository import EvidenceRecord, ToolCallRecord
from research_platform.runs.runner import (
    ResearchRunner,
    RunnerDependencies,
    ServingIdentity,
)
from research_platform.search.contracts import SearchRequest
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


class RecordingStore(InMemoryRunStore):
    """Expose accepted tool-call appends for assertions."""

    def __init__(self) -> None:
        super().__init__()
        self.appended: list[tuple[UUID, int, str]] = []

    async def append_tool_call(self, run_id: UUID, record: ToolCallRecord) -> None:
        self.appended.append((run_id, record.ordinal, record.tool_name))
        await super().append_tool_call(run_id, record)


class BlockSecondSearch:
    """Pause the second backend call so a graph execute node can be cancelled."""

    def __init__(self, wrapped: Any) -> None:
        self.wrapped = wrapped
        self.count = 0
        self.block = True
        self.started = asyncio.Event()

    async def execute(self, request: SearchRequest, *, request_id: str) -> Any:
        self.count += 1
        if self.block and self.count == 2:
            self.started.set()
            await asyncio.Future()
        return await self.wrapped.execute(request, request_id=request_id)


def _corpus() -> FakeCorpus:
    return FakeCorpus(
        snapshot_id=_SNAPSHOT,
        papers=(FakePaper("W123", "Retrieval study", 2024),),
        passages=(FakePassage("chunk-1", "W123", "retrieval improves ranking"),),
    )


def _call(name: str, arguments: dict[str, object]) -> dict[str, object]:
    return {"function": {"name": name, "arguments": arguments}}


def _plan(*calls: dict[str, object]) -> ScriptedReply:
    return ScriptedReply(kind=CallKind.PLAN, tool_calls=tuple(calls))


def _answer_replies() -> tuple[ScriptedReply, ...]:
    return (ScriptedReply(kind=CallKind.SYNTHESIZE, content=_SYNTHESIS),)


def _budgets(**overrides: Any) -> RunBudgets:
    return RunBudgets.model_construct(**overrides)


def _evaluation(
    *, sufficient: bool, actions: list[dict[str, object]] | None = None
) -> ScriptedReply:
    import json

    return ScriptedReply(
        kind=CallKind.EVALUATE,
        content=json.dumps(
            {
                "sufficient": sufficient,
                "missing": "more context" if not sufficient else "",
                "next_actions": actions or [],
            }
        ),
    )


def _runner(
    store: InMemoryRunStore,
    llm: LLMClient,
    *,
    budgets: RunBudgets | None = None,
    search: Any = None,
    thinking: frozenset[CallKind] = frozenset(),
    discovery: Any = None,
) -> ResearchRunner:
    search_service, papers, citations, related = fake_services(_corpus())
    tools = ResearchTools(
        search=search or search_service,
        papers=papers,
        citations=citations,
        related=related,
        discovery=discovery,
    )
    return ResearchRunner(
        RunnerDependencies(
            repository=store,
            tools=tools,
            llm=llm,
            checkpointer=InMemorySaver(),
            serving=ServingIdentity(_SNAPSHOT, _PROFILE),
            thinking=thinking,
            code_revision="test-revision",
            graphs={ResearchMode.DEEP_RESEARCH: build_deep_graph},
            budgets=budgets or RunBudgets.model_construct(),
        )
    )


async def _create_run(store: InMemoryRunStore) -> UUID:
    return await store.create_run(
        ResearchRequest(
            question="retrieval",
            mode=ResearchMode.DEEP_RESEARCH,
            filters=ResearchFilters.model_construct(year_from=2020, year_to=2025),
        )
    )


def _first_batch() -> tuple[dict[str, object], ...]:
    return (
        _call("search_papers", {"query": "retrieval", "limit": 10}),
        _call("search_evidence", {"query": "retrieval", "limit": 20}),
    )


@pytest.mark.anyio
async def test_sufficient_after_first_round_answers() -> None:
    store = RecordingStore()
    run_id = await _create_run(store)
    llm = ScriptedLLM(
        (_plan(*_first_batch()), _evaluation(sufficient=True), *_answer_replies()),
        identity=_IDENTITY,
    )

    assert await _runner(store, llm).run(run_id) is RunStatus.COMPLETED
    view = await store.get_run_view(run_id)
    assert view.answer is not None
    assert [name for _, _, name in store.appended] == [
        "search_papers",
        "search_evidence",
    ]
    assert view.usage.plan_rounds == 1
    assert view.usage.model_calls == 3


@pytest.mark.anyio
async def test_replans_until_sufficient() -> None:
    store = RecordingStore()
    run_id = await _create_run(store)
    llm = ScriptedLLM(
        (
            _plan(_call("search_papers", {"query": "retrieval"})),
            _evaluation(
                sufficient=False,
                actions=[{"tool": "get_paper", "paper_id": "W123"}],
            ),
            _evaluation(sufficient=True),
            *_answer_replies(),
        ),
        identity=_IDENTITY,
    )

    assert await _runner(store, llm).run(run_id) is RunStatus.COMPLETED
    view = await store.get_run_view(run_id)
    assert [name for _, _, name in store.appended] == [
        "search_papers",
        "search_evidence",
        "get_paper",
    ]
    assert view.usage.plan_rounds == 2
    assert view.usage.model_calls == 4


@pytest.mark.anyio
async def test_plan_rounds_budget_stops_without_extra_model_call() -> None:
    store = RecordingStore()
    run_id = await _create_run(store)
    llm = ScriptedLLM(
        (_plan(_call("search_papers", {"query": "retrieval"})), *_answer_replies()),
        identity=_IDENTITY,
    )

    status = await _runner(store, llm, budgets=_budgets(max_plan_rounds=1)).run(run_id)

    assert status is RunStatus.COMPLETED
    view = await store.get_run_view(run_id)
    assert view.usage.plan_rounds == 1
    assert view.usage.model_calls == 2
    assert [call.kind for call in llm.calls] == [CallKind.SYNTHESIZE]


@pytest.mark.anyio
async def test_tool_call_budget_truncates_batches_and_stops() -> None:
    store = RecordingStore()
    run_id = await _create_run(store)
    llm = ScriptedLLM((_plan(*_first_batch()), *_answer_replies()), identity=_IDENTITY)

    status = await _runner(store, llm, budgets=_budgets(max_tool_calls=1)).run(run_id)

    assert status is RunStatus.COMPLETED
    assert [name for _, _, name in store.appended] == ["search_papers"]
    assert len(llm.tool_requests) == 1
    assert llm.remaining == 0


@pytest.mark.anyio
async def test_invalid_plan_falls_back_to_default_actions() -> None:
    store = RecordingStore()
    run_id = await _create_run(store)
    llm = ScriptedLLM(
        (
            _plan(_call("unknown_tool", {})),
            *_answer_replies(),
        ),
        identity=_IDENTITY,
    )

    status = await _runner(store, llm, budgets=_budgets(max_tool_calls=1)).run(run_id)

    assert status is RunStatus.COMPLETED
    assert [name for _, _, name in store.appended] == ["search_papers"]


@pytest.mark.anyio
async def test_plan_uses_native_tool_calls_with_thinking() -> None:
    store = RecordingStore()
    run_id = await _create_run(store)
    llm = ScriptedLLM(
        (
            _plan(_call("search_papers", {"query": "retrieval"})),
            _evaluation(sufficient=True),
            *_answer_replies(),
        ),
        identity=_IDENTITY,
    )
    runner = _runner(store, llm, thinking=frozenset({CallKind.PLAN}))

    assert await runner.run(run_id) is RunStatus.COMPLETED
    request = llm.tool_requests[0]
    assert request.think is True
    assert len(request.tools) == 8
    assert request.max_repair_attempts == _budgets().max_model_retries


@pytest.mark.anyio
async def test_invalid_evaluation_answers_with_current_evidence() -> None:
    store = RecordingStore()
    run_id = await _create_run(store)
    llm = ScriptedLLM(
        (
            _plan(_call("search_papers", {"query": "retrieval"})),
            ScriptedReply(kind=CallKind.EVALUATE, content="not-json"),
            *_answer_replies(),
        ),
        identity=_IDENTITY,
    )

    assert await _runner(store, llm).run(run_id) is RunStatus.COMPLETED
    assert llm.remaining == 0
    assert len(llm.calls) == 2


@pytest.mark.anyio
async def test_evaluate_excludes_mismatched_stored_evidence() -> None:
    class MismatchedEvidenceStore(RecordingStore):
        async def load_evidence(
            self, run_id: UUID, handles: Sequence[str] | None = None
        ) -> dict[str, EvidenceRecord]:
            records = await super().load_evidence(run_id, handles)
            return {
                handle: EvidenceRecord(
                    handle=record.handle,
                    chunk_id="different-chunk",
                    paper_id=record.paper_id,
                    text="private mismatched passage",
                    metadata=record.metadata,
                )
                for handle, record in records.items()
            }

    store = MismatchedEvidenceStore()
    run_id = await _create_run(store)
    llm = ScriptedLLM(
        (
            _plan(_call("search_papers", {"query": "retrieval"})),
            _evaluation(sufficient=True),
        ),
        identity=_IDENTITY,
    )

    assert await _runner(store, llm).run(run_id) is RunStatus.COMPLETED
    view = await store.get_run_view(run_id)
    assert view.answer_outcome is AnswerOutcome.INSUFFICIENT_EVIDENCE
    assert llm.remaining == 0
    evaluate_request = llm.calls[0]
    prompt = "\n".join(message.content for message in evaluate_request.messages)
    assert "private mismatched passage" not in prompt
    assert "retrieval improves ranking" not in prompt


@pytest.mark.anyio
async def test_duplicate_actions_are_cached() -> None:
    store = RecordingStore()
    run_id = await _create_run(store)
    search = _call("search_papers", {"query": "retrieval"})
    evidence = _call("search_evidence", {"query": "retrieval"})
    llm = ScriptedLLM(
        (
            _plan(search, search, evidence),
            _evaluation(sufficient=True),
            *_answer_replies(),
        ),
        identity=_IDENTITY,
    )

    assert await _runner(store, llm).run(run_id) is RunStatus.COMPLETED
    view = await store.get_run_view(run_id)
    assert view.usage.tool_calls == 2
    assert len(store.appended) == 3
    assert store.appended[0][1] != store.appended[1][1]


@pytest.mark.anyio
async def test_citation_depth_rejections_are_observed_not_fatal() -> None:
    store = RecordingStore()
    run_id = await _create_run(store)
    llm = ScriptedLLM(
        (
            _plan(_call("get_citations", {"paper_id": "W123", "limit": 10})),
            _evaluation(sufficient=True),
            *_answer_replies(),
        ),
        identity=_IDENTITY,
    )

    assert (
        await _runner(store, llm, budgets=_budgets(max_citation_depth=0)).run(run_id)
        is RunStatus.COMPLETED
    )
    assert store.appended[0][2] == "get_citations"


@pytest.mark.anyio
async def test_model_unavailable_fails_run_with_category() -> None:
    store = InMemoryRunStore()
    run_id = await _create_run(store)
    llm = ScriptedLLM(
        (ScriptedReply(kind=CallKind.PLAN, error=LLMUnavailable("offline")),),
        identity=_IDENTITY,
    )

    assert await _runner(store, llm).run(run_id) is RunStatus.FAILED
    assert (await store.get_run_view(run_id)).failure_category is (
        FailureCategory.MODEL_UNAVAILABLE
    )


@pytest.mark.anyio
async def test_resume_mid_batch_does_not_duplicate_tool_records() -> None:
    store = RecordingStore()
    run_id = await _create_run(store)
    llm = ScriptedLLM(
        (
            _plan(*_first_batch()),
            _evaluation(sufficient=True),
            *_answer_replies(),
        ),
        identity=_IDENTITY,
    )
    search_service, _, _, _ = fake_services(_corpus())
    blocking_search = BlockSecondSearch(search_service)
    runner = _runner(store, llm, search=blocking_search)

    task = asyncio.create_task(runner.run(run_id))
    await asyncio.wait_for(blocking_search.started.wait(), timeout=2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    blocking_search.block = False
    assert await runner.run(run_id) is RunStatus.COMPLETED
    persisted_ordinals = store._tool_calls[run_id]  # noqa: SLF001
    assert sorted(persisted_ordinals) == [0, 1]
    assert blocking_search.count == 4
    evidence = store._evidence[run_id]  # noqa: SLF001
    assert len(evidence) == 1
    assert len({record.handle for record in evidence.values()}) == 1
    assert len({record.chunk_id for record in evidence.values()}) == 1


@pytest.mark.anyio
async def test_model_calls_and_plan_rounds_recorded_in_usage() -> None:
    store = RecordingStore()
    run_id = await _create_run(store)
    llm = ScriptedLLM(
        (
            _plan(_call("search_papers", {"query": "retrieval"})),
            _evaluation(sufficient=True),
            *_answer_replies(),
        ),
        identity=_IDENTITY,
    )

    assert await _runner(store, llm).run(run_id) is RunStatus.COMPLETED
    usage = (await store.get_run_view(run_id)).usage
    assert usage.plan_rounds == 1
    assert usage.model_calls == 3


def test_budget_helpers_and_default_actions_match_quick_mode() -> None:
    from research_platform.agents.state import initial_state
    from research_platform.tools.research_tools import ToolLedger

    state = initial_state("retrieval")
    state["ledger"] = ToolLedger(tool_calls_used=11)
    assert remaining_actions(state, _budgets(max_tool_calls=12)) == 1
    state["ledger"] = ToolLedger(tool_calls_used=12)
    assert remaining_actions(state, _budgets(max_tool_calls=12)) == 0
    actions = default_actions(
        "retrieval", ResearchFilters.model_construct(year_from=2020)
    )
    assert [action.tool for action in actions] == ["search_papers", "search_evidence"]
    assert actions[0].model_dump(mode="json")["limit"] == 10
    assert actions[1].model_dump(mode="json")["limit"] == 20


_NEW_SNAPSHOT = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")


class _FakeQueue:
    """Ingestion request statuses for the wait node."""

    def __init__(self, status: str, result: dict[str, object] | None = None) -> None:
        self.status = status
        self.result = result or {}
        self.gets = 0

    async def get(self, request_id: UUID) -> Any:
        from datetime import UTC, datetime

        from research_platform.worker.queue import IngestionRequest

        self.gets += 1
        return IngestionRequest(
            request_id,
            UUID(int=1),
            None,
            "run",
            ("W501",),
            self.status,  # type: ignore[arg-type]
            1,
            self.result,
            created_at=datetime.now(UTC),
        )


class _SnapshotRecordingSearch:
    """Record each search's snapshot, answering from the fake corpus."""

    def __init__(self, wrapped: Any) -> None:
        self.wrapped = wrapped
        self.snapshots: list[UUID] = []

    async def execute(self, request: SearchRequest, *, request_id: str) -> Any:
        from dataclasses import replace

        self.snapshots.append(request.snapshot_id)
        return await self.wrapped.execute(
            replace(request, snapshot_id=_SNAPSHOT), request_id=request_id
        )


def _ingestion_runner(
    store: InMemoryRunStore,
    llm: LLMClient,
    queue: _FakeQueue,
    *,
    budgets: RunBudgets | None = None,
    clock: Any = None,
) -> tuple[ResearchRunner, _SnapshotRecordingSearch]:
    from research_platform.tools.fakes import FakeIngestionPolicy

    search_service, papers, citations, related = fake_services(_corpus())
    search = _SnapshotRecordingSearch(search_service)
    tools = ResearchTools(
        search=search,
        papers=papers,
        citations=citations,
        related=related,
        ingestion=FakeIngestionPolicy(
            {"W501": (False, 2024, "en"), "W502": (False, 2024, "en")}
        ),
    )
    extra = {} if clock is None else {"clock": clock}
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
            budgets=budgets or RunBudgets.model_construct(),
            ingestion=queue,
            **extra,
        )
    )
    return runner, search


def _request(paper_id: str = "W501") -> dict[str, object]:
    return _call("request_ingestion", {"paper_ids": [paper_id], "reason": "gap"})


_PUBLISHED = {"generation": 2, "snapshot_id": str(_NEW_SNAPSHOT), "outcomes": []}


@pytest.mark.anyio
async def test_successful_ingestion_switches_generation_once() -> None:
    store = RecordingStore()
    run_id = await _create_run(store)
    llm = ScriptedLLM(
        (_plan(_request()), _evaluation(sufficient=True), *_answer_replies()),
        identity=_IDENTITY,
    )
    runner, _search = _ingestion_runner(store, llm, _FakeQueue("succeeded", _PUBLISHED))

    assert await runner.run(run_id) is RunStatus.COMPLETED

    view = await store.get_run_view(run_id)
    waits = [c for c in store.tool_calls(run_id) if c.tool_name == "ingestion_wait"]
    assert len(waits) == 1 and waits[0].status == "succeeded"
    assert waits[0].result_summary["from_generation"] == 1
    assert waits[0].result_summary["to_generation"] == 2
    assert view.generation == 2
    assert view.provenance is not None and view.provenance.generation == 1
    assert (await store.get_run(run_id)).snapshot_id == _NEW_SNAPSHOT


@pytest.mark.anyio
async def test_wait_cap_continues_on_current_generation() -> None:
    store = RecordingStore()
    run_id = await _create_run(store)
    llm = ScriptedLLM(
        (_plan(_request()), _evaluation(sufficient=True), *_answer_replies()),
        identity=_IDENTITY,
    )
    queue = _FakeQueue("pending")
    runner, _search = _ingestion_runner(
        store,
        llm,
        queue,
        budgets=RunBudgets.model_construct(max_ingestion_wait_seconds=0.05),
    )

    assert await runner.run(run_id) is RunStatus.COMPLETED

    waits = [c for c in store.tool_calls(run_id) if c.tool_name == "ingestion_wait"]
    assert [(c.status, c.error_category) for c in waits] == [
        ("failed", "ingestion_wait_cap")
    ]
    assert waits[0].result_summary["pending_paper_ids"] == ["W501"]
    view = await store.get_run_view(run_id)
    assert view.generation == 1 and queue.gets >= 2
    assert (await store.get_run(run_id)).snapshot_id == _SNAPSHOT


@pytest.mark.anyio
async def test_second_request_is_rejected() -> None:
    store = RecordingStore()
    run_id = await _create_run(store)
    llm = ScriptedLLM(
        (
            _plan(_request("W501"), _request("W502")),
            _evaluation(
                sufficient=False,
                actions=[
                    {
                        "tool": "request_ingestion",
                        "paper_ids": ["W502"],
                        "reason": "again",
                    }
                ],
            ),
            _evaluation(sufficient=True),
            *_answer_replies(),
        ),
        identity=_IDENTITY,
    )
    runner, _search = _ingestion_runner(store, llm, _FakeQueue("succeeded", _PUBLISHED))

    assert await runner.run(run_id) is RunStatus.COMPLETED

    calls = store.tool_calls(run_id)
    requests = [c for c in calls if c.tool_name == "request_ingestion"]
    assert [(c.status, c.error_category) for c in requests] == [
        ("succeeded", None),
        ("rejected", "ingestion_already_requested"),
        ("rejected", "ingestion_already_requested"),
    ]
    assert len([c for c in calls if c.tool_name == "ingestion_wait"]) == 1


@pytest.mark.anyio
async def test_later_searches_use_new_generation() -> None:
    store = RecordingStore()
    run_id = await _create_run(store)
    llm = ScriptedLLM(
        (
            _plan(_call("search_papers", {"query": "retrieval"}), _request()),
            _evaluation(
                sufficient=False,
                actions=[{"tool": "search_evidence", "query": "retrieval"}],
            ),
            _evaluation(sufficient=True),
            *_answer_replies(),
        ),
        identity=_IDENTITY,
    )
    runner, search = _ingestion_runner(store, llm, _FakeQueue("succeeded", _PUBLISHED))

    assert await runner.run(run_id) is RunStatus.COMPLETED
    # The first plan's code-added search_evidence runs before the switch.
    assert search.snapshots == [_SNAPSHOT, _SNAPSHOT, _NEW_SNAPSHOT]


@pytest.mark.anyio
async def test_first_plan_adds_discovery_when_configured() -> None:
    from research_platform.tools.fakes import FakeDiscoveryService

    store = RecordingStore()
    run_id = await _create_run(store)
    llm = ScriptedLLM(
        (_plan(*_first_batch()), _evaluation(sufficient=True), *_answer_replies()),
        identity=_IDENTITY,
    )

    runner = _runner(store, llm, discovery=FakeDiscoveryService())
    assert await runner.run(run_id) is RunStatus.COMPLETED
    assert [name for _, _, name in store.appended] == [
        "search_papers",
        "search_evidence",
        "discover_papers",
    ]


@pytest.mark.anyio
async def test_full_first_plan_keeps_first_choice_and_adds_discovery() -> None:
    from research_platform.tools.fakes import FakeDiscoveryService

    store = RecordingStore()
    run_id = await _create_run(store)
    llm = ScriptedLLM(
        (_plan(*_first_batch()), _evaluation(sufficient=True), *_answer_replies()),
        identity=_IDENTITY,
    )

    runner = _runner(
        store,
        llm,
        budgets=_budgets(max_actions_per_plan=2),
        discovery=FakeDiscoveryService(),
    )
    assert await runner.run(run_id) is RunStatus.COMPLETED
    assert [name for _, _, name in store.appended] == [
        "search_papers",
        "discover_papers",
    ]


@pytest.mark.anyio
async def test_evaluate_with_thinking_is_uncapped() -> None:
    store = RecordingStore()
    run_id = await _create_run(store)
    llm = ScriptedLLM(
        (
            _plan(_call("search_papers", {"query": "retrieval"})),
            _evaluation(sufficient=True),
            *_answer_replies(),
        ),
        identity=_IDENTITY,
    )
    runner = _runner(store, llm, thinking=frozenset({CallKind.PLAN, CallKind.EVALUATE}))

    assert await runner.run(run_id) is RunStatus.COMPLETED
    evaluate = next(call for call in llm.calls if call.kind is CallKind.EVALUATE)
    assert evaluate.think is True
    assert evaluate.max_output_tokens is None


@pytest.mark.anyio
async def test_evaluate_without_thinking_keeps_its_cap() -> None:
    store = RecordingStore()
    run_id = await _create_run(store)
    llm = ScriptedLLM(
        (
            _plan(_call("search_papers", {"query": "retrieval"})),
            _evaluation(sufficient=True),
            *_answer_replies(),
        ),
        identity=_IDENTITY,
    )
    runner = _runner(store, llm, thinking=frozenset({CallKind.PLAN}))

    assert await runner.run(run_id) is RunStatus.COMPLETED
    evaluate = next(call for call in llm.calls if call.kind is CallKind.EVALUATE)
    assert evaluate.think is False
    assert evaluate.max_output_tokens == 768
