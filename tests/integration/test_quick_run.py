"""PostgreSQL integration coverage for completed and resumed quick runs."""

from __future__ import annotations

import asyncio
import os
from uuid import UUID, uuid4

import asyncpg
import pytest

from research_platform.agents.answering import VerifiedAnswer
from research_platform.agents.evidence import EvidenceRegistry
from research_platform.agents.graph_quick import build_quick_graph
from research_platform.llm.contracts import (
    StructuredCall,
    ToolCallRequest,
    ToolCallResult,
)
from research_platform.llm.scripted import ScriptedLLM, ScriptedReply
from research_platform.llm.types import CallKind, ModelIdentity
from research_platform.persistence.migrations import apply_migrations
from research_platform.runs.checkpointing import (
    delete_run_checkpoints,
    open_checkpointer,
    setup_checkpoints,
)
from research_platform.runs.contracts import (
    AnswerOutcome,
    ResearchFilters,
    ResearchMode,
    ResearchRequest,
    RunBudgets,
    RunStatus,
)
from research_platform.runs.repository import RunRepository
from research_platform.runs.runner import (
    ResearchRunner,
    RunnerDependencies,
    ServingIdentity,
)
from research_platform.tools.fakes import (
    FakeCorpus,
    FakePaper,
    FakePassage,
    fake_services,
)
from research_platform.tools.research_tools import ResearchTools, ToolLedger

TEST_DATABASE_URL = os.environ.get("RESEARCH_PLATFORM_TEST_DATABASE_URL")
_IDENTITY = ModelIdentity(name="scripted", runtime="scripted", context_tokens=8192)
_SYNTHESIS = (
    '{"relevant_handles":["E1"],"insufficient_evidence":false,'
    '"claims":[{"handle":"E1","quote":"retrieval improves ranking",'
    '"text":"Retrieval improves ranking"}],"answer":"Retrieval improves ranking [E1]"}'
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not TEST_DATABASE_URL,
        reason="requires the dedicated disposable PostgreSQL service",
    ),
]


class BlockOnceLLM:
    """Block the first answer until the runner task is cancelled externally."""

    def __init__(self) -> None:
        self.script = ScriptedLLM(
            (ScriptedReply(kind=CallKind.SYNTHESIZE, content=_SYNTHESIS),),
            identity=_IDENTITY,
        )
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


def test_quick_run_completes_and_resumes_with_postgres_checkpoint() -> None:
    assert TEST_DATABASE_URL is not None
    snapshot_id = uuid4()
    paper_id = f"W{uuid4().int}"
    document_id = uuid4()
    chunk_id = f"chunk-{uuid4().hex}"

    async def exercise() -> None:
        await apply_migrations(TEST_DATABASE_URL)
        pool = await asyncpg.create_pool(TEST_DATABASE_URL, min_size=1, max_size=3)
        try:
            async with pool.acquire() as connection:
                await connection.execute(
                    """
                    INSERT INTO snapshots (id, name, configuration_id, configuration,
                                          code_revision)
                    VALUES ($1, $2, 'quick-run-test', '{}'::jsonb, 'integration')
                    """,
                    snapshot_id,
                    f"quick-run-{snapshot_id}",
                )
                await connection.execute(
                    """
                    INSERT INTO papers (id, title, publication_year, metadata)
                    VALUES ($1, 'Integration retrieval study', 2024, '{}'::jsonb)
                    """,
                    paper_id,
                )
                await connection.execute(
                    """
                    INSERT INTO documents (id, paper_id, source_type, version)
                    VALUES ($1, $2, 'integration', 'v1')
                    """,
                    document_id,
                    paper_id,
                )
                await connection.execute(
                    "INSERT INTO chunks (id, document_id, text) VALUES ($1, $2, $3)",
                    chunk_id,
                    document_id,
                    "retrieval improves ranking",
                )

            await setup_checkpoints(TEST_DATABASE_URL)
            async with open_checkpointer(TEST_DATABASE_URL) as checkpointer:
                repository = RunRepository(pool)
                corpus = FakeCorpus(
                    snapshot_id=snapshot_id,
                    papers=(FakePaper(paper_id, "Integration retrieval study", 2024),),
                    passages=(
                        FakePassage(chunk_id, paper_id, "retrieval improves ranking"),
                    ),
                )
                search, papers, citations, related = fake_services(corpus)
                tools = ResearchTools(
                    search=search,
                    papers=papers,
                    citations=citations,
                    related=related,
                )
                serving = ServingIdentity(snapshot_id, "sha256:" + "a" * 64)

                def make_runner(llm) -> ResearchRunner:  # type: ignore[no-untyped-def]
                    return ResearchRunner(
                        RunnerDependencies(
                            repository=repository,
                            tools=tools,
                            llm=llm,
                            checkpointer=checkpointer,
                            serving=serving,
                            thinking=frozenset(),
                            code_revision="integration-test",
                            graphs={ResearchMode.QUICK: build_quick_graph},
                            budgets=RunBudgets(),
                        )
                    )

                completed_id = await repository.create_run(
                    _request(snapshot_id, "retrieval")
                )
                completed_runner = make_runner(
                    ScriptedLLM(
                        (ScriptedReply(kind=CallKind.SYNTHESIZE, content=_SYNTHESIS),),
                        identity=_IDENTITY,
                    )
                )
                assert await completed_runner.run(completed_id) is RunStatus.COMPLETED
                completed = await repository.get_run_view(completed_id)
                assert completed.answer_outcome is AnswerOutcome.ANSWERED
                assert completed.claims[0].evidence[0].chunk_id == chunk_id

                resumed_id = await repository.create_run(
                    _request(snapshot_id, "retrieval")
                )
                blocked_llm = BlockOnceLLM()
                resumed_runner = make_runner(blocked_llm)
                task = asyncio.create_task(resumed_runner.run(resumed_id))
                await asyncio.wait_for(blocked_llm.started.wait(), timeout=10)
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
                assert (
                    await repository.get_run(resumed_id)
                ).status is RunStatus.RUNNING
                assert await resumed_runner.run(resumed_id) is RunStatus.COMPLETED
                resumed = await repository.get_run_view(resumed_id)
                assert resumed.claims[0].evidence[0].chunk_id == chunk_id
                assert resumed.usage.resumes == 1

                calls = await pool.fetch(
                    "SELECT tool_name FROM tool_calls WHERE run_id = $1 ORDER BY ordinal",
                    resumed_id,
                )
                assert [row["tool_name"] for row in calls] == [
                    "search_papers",
                    "search_evidence",
                ]

                models = (
                    ToolLedger(tool_calls_used=2),
                    EvidenceRegistry(),
                    VerifiedAnswer(
                        answer="No evidence",
                        outcome=AnswerOutcome.INSUFFICIENT_EVIDENCE,
                        claims=(),
                        rejected_claims=0,
                        unsupported_claims=0,
                        model_calls=0,
                    ),
                )
                for model in models:
                    serialized = checkpointer.serde.dumps_typed(model)
                    assert checkpointer.serde.loads_typed(serialized) == model

                await delete_run_checkpoints(checkpointer, completed_id)
                await delete_run_checkpoints(checkpointer, resumed_id)
        finally:
            await pool.close()

    asyncio.run(exercise())


def _request(snapshot_id: UUID, question: str) -> ResearchRequest:
    return ResearchRequest(
        question=question,
        mode=ResearchMode.QUICK,
        snapshot_id=snapshot_id,
        filters=ResearchFilters(year_from=2020, year_to=2025),
    )
