"""Focused coverage for the quick graph's known-not-ingested diagnostic."""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID, uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from research_platform.agents.graph_quick import build_quick_graph
from research_platform.agents.nodes import NodeDependencies
from research_platform.agents.state import initial_state
from research_platform.llm.scripted import ScriptedLLM, ScriptedReply
from research_platform.llm.types import CallKind, ModelIdentity
from research_platform.runs.contracts import (
    UNINGESTED_SIMILARITY_THRESHOLD,
    AnswerOutcome,
    PaperSummary,
    ResearchFilters,
    ResearchMode,
    ResearchRequest,
    RunBudgets,
    RunProvenance,
)
from research_platform.runs.memory import InMemoryRunStore
from research_platform.runs.repository import ToolCallRecord
from research_platform.search.paper_similarity import SimilarPaper
from research_platform.tools.fakes import (
    FakeCorpus,
    FakePaper,
    FakePassage,
    FakeSimilarityReader,
    fake_services,
)
from research_platform.tools.research_tools import ResearchTools, ToolContext

_SNAPSHOT = uuid4()
_PROFILE = "sha256:" + "a" * 64
_QUESTION = "Which retrieval methods improve ranking?"
_IDENTITY = ModelIdentity(name="scripted", runtime="scripted", context_tokens=8192)
_SUCCESS_SCRIPT = (
    ScriptedReply(
        kind=CallKind.SYNTHESIZE,
        content=(
            '{"relevant_handles":["E1"],"insufficient_evidence":false,'
            '"claims":[{"handle":"E1","quote":"retrieval improves ranking",'
            '"text":"Retrieval improves ranking"}],'
            '"answer":"Retrieval improves ranking [E1]"}'
        ),
    ),
)
_CANDIDATE = SimilarPaper(
    paper_id="W9876543210",
    title="Known metadata-only retrieval study",
    publication_year=2025,
    similarity=0.83,
    catalog_status="metadata_only",
)


class _RecordingStore(InMemoryRunStore):
    def __init__(self) -> None:
        super().__init__()
        self.tool_calls: list[ToolCallRecord] = []

    async def append_tool_call(self, run_id: UUID, record: ToolCallRecord) -> None:
        self.tool_calls.append(record)
        await super().append_tool_call(run_id, record)


class _FailingDiagnosticStore(_RecordingStore):
    async def save_uningested_candidates(
        self,
        run_id: UUID,
        candidates: Sequence[PaperSummary],
        *,
        minimum_similarity: float,
    ) -> None:
        raise ValueError(f"could not save {candidates[0].title}")


class _FailingSimilarityReader(FakeSimilarityReader):
    async def uningested_for_question(
        self,
        question: str,
        *,
        limit: int = 5,
        minimum_similarity: float = 0.5,
    ) -> tuple[SimilarPaper, ...]:
        self.uningested_calls.append(
            {
                "question": question,
                "limit": limit,
                "minimum_similarity": minimum_similarity,
            }
        )
        raise RuntimeError(f"lookup failed for {question} and {_CANDIDATE.title}")


def _provenance(run_id: UUID) -> RunProvenance:
    return RunProvenance(
        snapshot_id=_SNAPSHOT,
        retrieval_profile_id=_PROFILE,
        configuration_id="sha256:" + "b" * 64,
        code_revision="synthetic-test-revision",
        model=_IDENTITY,
        thinking={kind: False for kind in CallKind},
        prompt_versions={},
        budgets=RunBudgets.model_construct(),
        trace_id=str(run_id),
        generation=None,
        uningested_similarity_threshold=UNINGESTED_SIMILARITY_THRESHOLD,
    )


async def _dependencies(
    *,
    store: _RecordingStore | None = None,
    similarity: FakeSimilarityReader | None = None,
) -> tuple[NodeDependencies, _RecordingStore, FakeSimilarityReader, ScriptedLLM]:
    selected_store = store or _RecordingStore()
    selected_similarity = similarity or FakeSimilarityReader(
        uningested_papers=(_CANDIDATE,)
    )
    request = ResearchRequest(question=_QUESTION, mode=ResearchMode.QUICK)
    run_id = await selected_store.create_run(request)
    await selected_store.mark_running(run_id, provenance=_provenance(run_id))

    corpus = FakeCorpus(
        snapshot_id=_SNAPSHOT,
        papers=(FakePaper("W123", "Retrieval study", 2024),),
        passages=(FakePassage("chunk-1", "W123", "retrieval improves ranking"),),
    )
    search, papers, citations, related = fake_services(corpus)
    tools = ResearchTools(
        search=search,
        papers=papers,
        citations=citations,
        related=related,
        similarity=selected_similarity,
    )
    context = ToolContext(
        run_id=run_id,
        snapshot_id=_SNAPSHOT,
        retrieval_profile_id=_PROFILE,
        mode=ResearchMode.QUICK,
        question=_QUESTION,
        filters=ResearchFilters.model_construct(),
        budgets=RunBudgets.model_construct(),
    )
    llm = ScriptedLLM(_SUCCESS_SCRIPT, identity=_IDENTITY)
    deps = NodeDependencies(
        run_id=run_id,
        tools=tools,
        llm=llm,
        repository=selected_store,
        context=context,
        thinking=frozenset(),
    )
    return deps, selected_store, selected_similarity, llm


@pytest.mark.anyio
async def test_quick_run_records_uningested_candidates() -> None:
    deps, store, similarity, llm = await _dependencies()
    graph = build_quick_graph(deps).compile(checkpointer=InMemorySaver())

    result = await graph.ainvoke(
        initial_state(_QUESTION),
        {"configurable": {"thread_id": str(deps.run_id)}},
    )

    view = await store.get_run_view(deps.run_id)
    assert result["answer"].outcome is AnswerOutcome.ANSWERED
    assert view.uningested_candidates == (
        PaperSummary(
            paper_id=_CANDIDATE.paper_id,
            title=_CANDIDATE.title,
            publication_year=_CANDIDATE.publication_year,
        ),
    )
    assert view.provenance is not None
    assert (
        view.provenance.uningested_similarity_threshold
        == UNINGESTED_SIMILARITY_THRESHOLD
    )
    assert similarity.uningested_calls == [
        {
            "question": _QUESTION,
            "limit": 5,
            "minimum_similarity": UNINGESTED_SIMILARITY_THRESHOLD,
        }
    ]
    assert result["ledger"].tool_calls_used == 2
    assert [record.tool_name for record in store.tool_calls] == [
        "search_papers",
        "search_evidence",
    ]
    assert len(llm.calls) == 1


@pytest.mark.anyio
@pytest.mark.parametrize("failure_stage", ("lookup", "persistence"))
async def test_uningested_failure_does_not_fail_run(
    failure_stage: str, caplog: pytest.LogCaptureFixture
) -> None:
    similarity: FakeSimilarityReader
    store: _RecordingStore
    if failure_stage == "lookup":
        similarity = _FailingSimilarityReader(uningested_papers=(_CANDIDATE,))
        store = _RecordingStore()
    else:
        similarity = FakeSimilarityReader(uningested_papers=(_CANDIDATE,))
        store = _FailingDiagnosticStore()

    deps, store, similarity, llm = await _dependencies(
        store=store, similarity=similarity
    )
    graph = build_quick_graph(deps).compile(checkpointer=InMemorySaver())

    with caplog.at_level("ERROR", logger="research_platform.agents.graph_quick"):
        result = await graph.ainvoke(
            initial_state(_QUESTION),
            {"configurable": {"thread_id": str(deps.run_id)}},
        )

    view = await store.get_run_view(deps.run_id)
    assert result["answer"].outcome is AnswerOutcome.ANSWERED
    assert view.provenance is not None
    assert (
        view.provenance.uningested_similarity_threshold
        == UNINGESTED_SIMILARITY_THRESHOLD
    )
    assert len(similarity.uningested_calls) == 1
    assert result["ledger"].tool_calls_used == 2
    assert [record.tool_name for record in store.tool_calls] == [
        "search_papers",
        "search_evidence",
    ]
    assert len(llm.calls) == 1
    assert len(caplog.records) == 1
    assert caplog.records[0].message == "quick_uningested_candidates_failed"
    assert getattr(caplog.records[0], "run_id") == str(deps.run_id)
    assert getattr(caplog.records[0], "error_type") in {"RuntimeError", "ValueError"}
    assert caplog.records[0].exc_info is None
    assert _QUESTION not in caplog.text
    assert (_CANDIDATE.title or "") not in caplog.text
