"""Tracing coverage for ingestion requests, papers, and deep wait nodes."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any, cast
from uuid import UUID, uuid4

import pytest

from research_platform.ingestion.online_ingestion import PaperIngestOutcome
from research_platform.observability.tracing import (
    ATTR_GENERATION,
    ATTR_INGESTION_PAPER_ID,
    ATTR_INGESTION_REQUEST_ID,
    ATTR_INGESTION_STATUS,
    ATTR_INGESTION_WAITED_SECONDS,
    SPAN_INGESTION_PAPER,
    SPAN_INGESTION_REQUEST,
    capture_spans,
)
from research_platform.worker.handlers import PaperIngester, _ingest_traced
from research_platform.worker.main import IngestionHandler, _process_request
from research_platform.worker.queue import IngestionRequest


def _attributes(span: Any) -> Mapping[str, Any]:
    attributes = span.attributes
    assert attributes is not None
    return cast(Mapping[str, Any], attributes)


def _request() -> IngestionRequest:
    return IngestionRequest(
        id=uuid4(),
        collection_id=uuid4(),
        run_id=uuid4(),
        requested_by="terminal",
        paper_ids=("W123", "W456"),
        status="claimed",
        attempts=1,
        result={},
    )


class _Queue:
    async def heartbeat(
        self, request_id: UUID, worker_id: str, *, lease_seconds: float
    ) -> bool:
        del request_id, worker_id, lease_seconds
        await asyncio.sleep(3600)
        return True

    async def complete(
        self,
        request_id: UUID,
        worker_id: str,
        *,
        status: str,
        result: dict[str, object],
    ) -> None:
        del request_id, worker_id, status, result


class _Ingester:
    async def ingest_paper(
        self, paper_id: str, *, run_id: UUID | None
    ) -> PaperIngestOutcome:
        del run_id
        return cast(
            PaperIngestOutcome,
            type("Outcome", (), {"status": "ingested", "reason": None})(),
        )


class _Handler:
    async def handle(self, request: IngestionRequest) -> tuple[str, dict[str, object]]:
        for paper_id in request.paper_ids:
            await _ingest_traced(
                cast(PaperIngester, _Ingester()), paper_id, request.run_id
            )
        return "succeeded", {}


@pytest.mark.anyio
async def test_request_span_has_status() -> None:
    request = _request()
    with capture_spans() as exporter:
        await _process_request(
            cast(Any, _Queue()), cast(IngestionHandler, _Handler()), request, "worker"
        )

    spans = exporter.get_finished_spans()
    request_span = next(span for span in spans if span.name == SPAN_INGESTION_REQUEST)
    attributes = _attributes(request_span)
    assert attributes[ATTR_INGESTION_REQUEST_ID] == str(request.id)
    assert attributes[ATTR_INGESTION_STATUS] == "succeeded"


@pytest.mark.anyio
async def test_paper_spans_are_children_of_request() -> None:
    with capture_spans() as exporter:
        await _process_request(
            cast(Any, _Queue()),
            cast(IngestionHandler, _Handler()),
            _request(),
            "worker",
        )

    spans = exporter.get_finished_spans()
    request_span = next(span for span in spans if span.name == SPAN_INGESTION_REQUEST)
    paper_spans = [span for span in spans if span.name == SPAN_INGESTION_PAPER]
    assert len(paper_spans) == 2
    assert all(
        span.parent is not None and span.parent.span_id == request_span.context.span_id
        for span in paper_spans
    )
    assert {_attributes(span)[ATTR_INGESTION_PAPER_ID] for span in paper_spans} == {
        "W123",
        "W456",
    }


@pytest.mark.anyio
async def test_wait_node_records_switch() -> None:
    from test_agent_graph_deep import (
        _IDENTITY,
        _PUBLISHED,
        RecordingStore,
        _answer_replies,
        _create_run,
        _evaluation,
        _FakeQueue,
        _ingestion_runner,
        _plan,
    )
    from test_agent_graph_deep import (
        _request as ingestion_tool_request,
    )

    from research_platform.llm.scripted import ScriptedLLM
    from research_platform.runs.contracts import RunStatus

    store = RecordingStore()
    run_id = await _create_run(store)
    llm = ScriptedLLM(
        (
            _plan(ingestion_tool_request()),
            _evaluation(sufficient=True),
            *_answer_replies(),
        ),
        identity=_IDENTITY,
    )
    runner, _search = _ingestion_runner(store, llm, _FakeQueue("succeeded", _PUBLISHED))
    with capture_spans() as exporter:
        assert await runner.run(run_id) is RunStatus.COMPLETED

    wait_span = next(
        span
        for span in exporter.get_finished_spans()
        if span.name == "node.wait_ingestion"
    )
    attributes = _attributes(wait_span)
    assert attributes[ATTR_INGESTION_STATUS] == "switched"
    assert attributes[ATTR_GENERATION] == 2
    assert attributes[ATTR_INGESTION_WAITED_SECONDS] >= 0
    assert ATTR_INGESTION_REQUEST_ID in attributes


@pytest.mark.anyio
async def test_wait_node_records_cap() -> None:
    from test_agent_graph_deep import (
        _IDENTITY,
        RecordingStore,
        _answer_replies,
        _create_run,
        _evaluation,
        _FakeQueue,
        _ingestion_runner,
        _plan,
    )
    from test_agent_graph_deep import (
        _request as ingestion_tool_request,
    )

    from research_platform.llm.scripted import ScriptedLLM
    from research_platform.runs.contracts import RunBudgets, RunStatus

    store = RecordingStore()
    run_id = await _create_run(store)
    llm = ScriptedLLM(
        (
            _plan(ingestion_tool_request()),
            _evaluation(sufficient=True),
            *_answer_replies(),
        ),
        identity=_IDENTITY,
    )
    runner, _search = _ingestion_runner(
        store,
        llm,
        _FakeQueue("pending"),
        budgets=RunBudgets.model_construct(max_ingestion_wait_seconds=0.01),
    )
    with capture_spans() as exporter:
        assert await runner.run(run_id) is RunStatus.COMPLETED

    wait_span = next(
        span
        for span in exporter.get_finished_spans()
        if span.name == "node.wait_ingestion"
    )
    attributes = _attributes(wait_span)
    assert attributes[ATTR_INGESTION_STATUS] == "wait_cap"
    assert attributes[ATTR_INGESTION_WAITED_SECONDS] >= 0
