"""Focused tests for shared LangGraph research nodes and the quick graph."""

from __future__ import annotations

from dataclasses import replace
from uuid import uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from research_platform.agents.actions import SearchPapersAction
from research_platform.agents.answering import VerifiedAnswer
from research_platform.agents.evidence import EvidenceRegistry
from research_platform.agents.graph_quick import build_quick_graph
from research_platform.agents.nodes import (
    NodeDependencies,
    ToolStepFailed,
    answer_node,
    run_action,
    to_tool_call_record,
)
from research_platform.agents.state import initial_state
from research_platform.llm.scripted import ScriptedLLM, ScriptedReply
from research_platform.llm.types import CallKind
from research_platform.runs.contracts import (
    AnswerOutcome,
    ResearchFilters,
    ResearchMode,
    ResearchRequest,
    RunBudgets,
)
from research_platform.runs.memory import InMemoryRunStore
from research_platform.runs.repository import EvidenceRecord, ToolCallRecord
from research_platform.tools.fakes import (
    FakeCorpus,
    FakePaper,
    FakePassage,
    fake_services,
)
from research_platform.tools.research_tools import (
    CollectedEvidence,
    ResearchTools,
    ToolContext,
    ToolLedger,
    ToolObservation,
)

_SNAPSHOT = uuid4()
_PROFILE = "sha256:" + "a" * 64
_SUCCESS_SCRIPT = (
    ScriptedReply(
        kind=CallKind.SYNTHESIZE,
        content=(
            '{"answer":"Retrieval improves ranking [E1]",'
            '"claims":[{"text":"Retrieval improves ranking",'
            '"handles":["E1"]}],"insufficient_evidence":false}'
        ),
    ),
    ScriptedReply(
        kind=CallKind.JUDGE,
        content='{"judgements":[{"claim_index":1,"label":"supported"}]}',
    ),
)


class _RecordingStore(InMemoryRunStore):
    def __init__(self) -> None:
        super().__init__()
        self.calls: list[ToolCallRecord] = []

    async def append_tool_call(self, run_id, record: ToolCallRecord) -> None:  # type: ignore[no-untyped-def]
        self.calls.append(record)
        await super().append_tool_call(run_id, record)


def _corpus(*, failing: bool = False) -> FakeCorpus:
    return FakeCorpus(
        snapshot_id=_SNAPSHOT,
        papers=(FakePaper("W123", "Retrieval study", 2024),),
        passages=(FakePassage("chunk-1", "W123", "retrieval improves ranking"),),
        failing_queries=frozenset({"retrieval"}) if failing else frozenset(),
    )


def _deps(
    *,
    store: InMemoryRunStore | None = None,
    llm: ScriptedLLM | None = None,
    corpus: FakeCorpus | None = None,
    budgets: RunBudgets | None = None,
) -> tuple[NodeDependencies, InMemoryRunStore, ScriptedLLM]:
    selected_store = store or InMemoryRunStore()
    selected_llm = llm or ScriptedLLM(())
    search, papers, citations, related = fake_services(corpus or _corpus())
    tools = ResearchTools(
        search=search, papers=papers, citations=citations, related=related
    )
    run_id = uuid4()
    selected_budgets = budgets or RunBudgets()
    context = ToolContext(
        run_id=run_id,
        snapshot_id=_SNAPSHOT,
        retrieval_profile_id=_PROFILE,
        filters=ResearchFilters(),
        budgets=selected_budgets,
    )
    return (
        NodeDependencies(
            run_id=run_id,
            tools=tools,
            llm=selected_llm,
            repository=selected_store,
            context=context,
            thinking=frozenset(),
        ),
        selected_store,
        selected_llm,
    )


async def _bind_run(
    deps: NodeDependencies, store: InMemoryRunStore, question: str
) -> NodeDependencies:
    run_id = await store.create_run(
        ResearchRequest(question=question, mode=ResearchMode.QUICK)
    )
    context = deps.context.model_copy(update={"run_id": run_id})
    return replace(deps, run_id=run_id, context=context)


def test_to_tool_call_record_maps_every_field() -> None:
    observation = ToolObservation(
        ordinal=7,
        tool="search_evidence",
        arguments={"query": "retrieval"},
        status="failed",
        summary={"eligible_count": 0},
        error_category="retrieval_error",
        retryable=True,
        duration_ms=2.5,
    )

    assert to_tool_call_record(observation) == ToolCallRecord(
        ordinal=7,
        tool_name="search_evidence",
        arguments={"query": "retrieval"},
        status="failed",
        result_summary={"eligible_count": 0},
        duration_ms=2.5,
        error_category="retrieval_error",
    )


@pytest.mark.anyio
async def test_run_action_registers_evidence_and_persists_call() -> None:
    store = _RecordingStore()
    deps, _, _ = _deps(store=store)
    deps = await _bind_run(deps, store, "retrieval")
    run_id = deps.run_id
    state = initial_state("retrieval")

    update = await run_action(
        deps,
        state,
        SearchPapersAction(tool="search_papers", query="retrieval", limit=10),
    )

    assert update["ledger"].tool_calls_used == 1
    assert tuple(ref.handle for ref in update["registry"].refs) == ("E1",)
    assert len(store.calls) == 1
    evidence = await store.load_evidence(run_id)
    assert evidence["E1"].text == "retrieval improves ranking"
    assert evidence["E1"].metadata == {
        "title": "Retrieval study",
        "publication_year": 2024,
        "kind": "text",
        "source_location": {
            "page_index_zero_based": 0,
            "printed_page_label": None,
            "bounding_box": None,
            "coordinate_system": None,
        },
    }


@pytest.mark.anyio
async def test_run_action_keeps_last_20_observations() -> None:
    deps, store, _ = _deps()
    deps = await _bind_run(deps, store, "retrieval")
    state = initial_state("retrieval")

    for index in range(21):
        update = await run_action(
            deps,
            state,
            SearchPapersAction(tool="search_papers", query=f"query {index}", limit=10),
        )
        state = {**state, **update}

    assert len(state["observations"]) == 20
    assert "query 0" not in state["observations"][0]
    assert "query 20" in state["observations"][-1]


@pytest.mark.anyio
async def test_answer_node_ignores_mismatched_chunk_text() -> None:
    llm = ScriptedLLM(
        (
            ScriptedReply(
                kind=CallKind.SYNTHESIZE,
                content='{"answer":"insufficient","claims":[],"insufficient_evidence":true}',
            ),
        )
    )
    deps, store, _ = _deps(llm=llm)
    deps = await _bind_run(deps, store, "retrieval")
    registry, _ = EvidenceRegistry().register(
        (
            CollectedEvidence(
                chunk_id="chunk-expected",
                paper_id="W123",
                text="expected text",
                title="Retrieval study",
                publication_year=2024,
                kind="text",
                source_location={},
                reranker_score=None,
            ),
        ),
        max_passages=10,
    )
    await store.save_evidence(
        deps.run_id,
        [
            EvidenceRecord(
                handle="E1",
                chunk_id="chunk-different",
                paper_id="W123",
                text="must never be sent to the model",
                metadata={},
            )
        ],
    )
    state = initial_state("retrieval")
    state["registry"] = registry

    update = await answer_node(deps, state)

    assert isinstance(update["answer"], VerifiedAnswer)
    assert update["answer"].outcome is AnswerOutcome.INSUFFICIENT_EVIDENCE
    assert llm.calls == []
    assert update["answer"].answer == "No evidence was found for this question."


@pytest.mark.anyio
async def test_answer_node_packs_only_evidence_with_matching_nonempty_text() -> None:
    llm = ScriptedLLM(
        (
            ScriptedReply(
                kind=CallKind.SYNTHESIZE,
                content='{"answer":"insufficient","claims":[],"insufficient_evidence":true}',
            ),
        )
    )
    deps, store, _ = _deps(llm=llm)
    deps = await _bind_run(deps, store, "retrieval")
    registry, _ = EvidenceRegistry().register(
        (
            CollectedEvidence(
                chunk_id="chunk-valid",
                paper_id="W123",
                text="valid passage",
                title="Valid paper",
                publication_year=2024,
                kind="text",
                source_location={},
                reranker_score=None,
            ),
            CollectedEvidence(
                chunk_id="chunk-invalid",
                paper_id="W123",
                text="registry passage",
                title="Invalid paper",
                publication_year=2024,
                kind="text",
                source_location={},
                reranker_score=None,
            ),
        ),
        max_passages=10,
    )
    await store.save_evidence(
        deps.run_id,
        [
            EvidenceRecord(
                handle="E1",
                chunk_id="chunk-valid",
                paper_id="W123",
                text="valid passage",
                metadata={},
            ),
            EvidenceRecord(
                handle="E2",
                chunk_id="other-chunk",
                paper_id="W123",
                text="secret mismatched passage",
                metadata={},
            ),
        ],
    )
    state = initial_state("retrieval")
    state["registry"] = registry

    await answer_node(deps, state)

    assert len(llm.calls) == 1
    prompt = "\n".join(message.content for message in llm.calls[0].messages)
    assert 'handle="E1"' in prompt
    assert 'handle="E2"' not in prompt
    assert "valid passage" in prompt
    assert "secret mismatched passage" not in prompt


@pytest.mark.anyio
async def test_quick_graph_runs_three_nodes_in_order() -> None:
    store = _RecordingStore()
    llm = ScriptedLLM(_SUCCESS_SCRIPT)
    deps, _, _ = _deps(store=store, llm=llm)
    deps = await _bind_run(deps, store, "retrieval")
    graph = build_quick_graph(deps).compile(checkpointer=InMemorySaver())

    result = await graph.ainvoke(
        initial_state("retrieval"), {"configurable": {"thread_id": str(deps.run_id)}}
    )

    assert result["answer"].outcome is AnswerOutcome.ANSWERED
    assert [record.tool_name for record in store.calls] == [
        "search_papers",
        "search_evidence",
    ]
    assert [call.kind for call in llm.calls] == [CallKind.SYNTHESIZE, CallKind.JUDGE]
    assert result["candidate_paper_ids"] == ["W123"]


@pytest.mark.anyio
async def test_quick_graph_failed_search_raises_tool_step_failed() -> None:
    deps, store, _ = _deps(corpus=_corpus(failing=True))
    deps = await _bind_run(deps, store, "retrieval")
    graph = build_quick_graph(deps).compile(checkpointer=InMemorySaver())

    with pytest.raises(ToolStepFailed, match="retrieval_error"):
        await graph.ainvoke(
            initial_state("retrieval"),
            {"configurable": {"thread_id": str(deps.run_id)}},
        )


@pytest.mark.anyio
async def test_quick_graph_rejected_search_still_answers() -> None:
    budgets = RunBudgets(max_tool_calls=1)
    store = _RecordingStore()
    deps, _, llm = _deps(store=store, budgets=budgets)
    deps = await _bind_run(deps, store, "retrieval")
    state = initial_state("retrieval")
    state["ledger"] = ToolLedger(tool_calls_used=1)
    graph = build_quick_graph(deps).compile(checkpointer=InMemorySaver())

    result = await graph.ainvoke(
        state, {"configurable": {"thread_id": str(deps.run_id)}}
    )

    assert result["answer"].outcome is AnswerOutcome.INSUFFICIENT_EVIDENCE
    assert llm.calls == []
    assert [call.status for call in store.calls] == ["rejected", "rejected"]
