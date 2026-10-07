"""Domain metrics emitted by research runs and ingestion workers."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from research_platform.evaluation.phase3_regression import (
    load_cases,
    load_corpus,
    run_case,
)
from research_platform.observability.metrics import REGISTRY
from research_platform.worker.main import _process_request
from research_platform.worker.queue import IngestionRequest

_CASE_PATH = (
    Path(__file__).parents[1] / "benchmarks" / "phase3" / "regression-cases-v2.json"
)
_CASES = {case.case_id: case for case in load_cases(_CASE_PATH)}
_CORPUS = load_corpus(_CASE_PATH)


def _value(name: str, labels: dict[str, str]) -> float:
    value = REGISTRY.get_sample_value(name, labels)
    return 0 if value is None else value


@pytest.mark.anyio
async def test_finished_run_is_counted() -> None:
    labels = {
        "mode": "deep_research",
        "status": "completed",
        "failure_category": "none",
    }
    before = _value("research_runs_finished_total", labels)

    await run_case(_CASES["route-01-search-path"], _CORPUS)

    assert _value("research_runs_finished_total", labels) == before + 1


@pytest.mark.anyio
async def test_failed_run_is_counted_with_category() -> None:
    labels = {
        "mode": "deep_research",
        "status": "failed",
        "failure_category": "model_unavailable",
    }
    before = _value("research_runs_finished_total", labels)

    await run_case(_CASES["failure-01-model-unavailable"], _CORPUS)

    assert _value("research_runs_finished_total", labels) == before + 1


@pytest.mark.anyio
async def test_tool_calls_are_counted() -> None:
    labels = {"tool": "search_papers", "status": "succeeded"}
    before = _value("research_tool_calls_total", labels)

    await run_case(_CASES["route-01-search-path"], _CORPUS)

    assert _value("research_tool_calls_total", labels) > before


@pytest.mark.anyio
async def test_llm_calls_are_counted() -> None:
    labels = {"kind": "synthesize", "status": "succeeded"}
    before = _value("research_llm_calls_total", labels)

    await run_case(_CASES["route-01-search-path"], _CORPUS)

    assert _value("research_llm_calls_total", labels) > before


@pytest.mark.anyio
async def test_claim_verdicts_are_counted() -> None:
    labels = {"verdict": "kept"}
    before = _value("research_claim_verdicts_total", labels)

    await run_case(_CASES["route-01-search-path"], _CORPUS)

    assert _value("research_claim_verdicts_total", labels) > before


@pytest.mark.anyio
async def test_worker_counts_completed_requests() -> None:
    class Queue:
        async def complete(
            self,
            request_id: object,
            worker_id: str,
            *,
            status: str,
            result: dict[str, object],
        ) -> None:
            del request_id, worker_id, status, result

        async def heartbeat(
            self, request_id: object, worker_id: str, *, lease_seconds: float = 300
        ) -> bool:
            del request_id, worker_id, lease_seconds
            return True

    class Handler:
        async def handle(
            self, request: IngestionRequest
        ) -> tuple[str, dict[str, object]]:
            del request
            return "succeeded", {}

    request = IngestionRequest(
        id=uuid4(),
        collection_id=uuid4(),
        run_id=None,
        requested_by="terminal",
        paper_ids=("W123",),
        status="claimed",
        attempts=1,
        result={},
    )
    labels = {"status": "succeeded"}
    before = _value("research_ingestion_requests_total", labels)

    await _process_request(Queue(), Handler(), request, "worker-1")  # type: ignore[arg-type]

    assert _value("research_ingestion_requests_total", labels) == before + 1
