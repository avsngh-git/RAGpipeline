"""Run-level traces cover the research workflow and persisted outcome."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.trace import StatusCode

from research_platform.evaluation.phase3_regression import (
    CaseRun,
    RegressionCase,
    load_cases,
    load_corpus,
    run_case_detailed,
)
from research_platform.observability.content import TraceContent
from research_platform.observability.logging_config import JsonFormatter
from research_platform.observability.tracing import (
    ATTR_ANSWER_OUTCOME,
    ATTR_CODE_REVISION,
    ATTR_CONFIGURATION_ID,
    ATTR_FAILURE_CATEGORY,
    ATTR_MODE,
    ATTR_RUN_ID,
    ATTR_SNAPSHOT_ID,
    ATTR_STATUS,
    ATTR_TOOL_ARGUMENTS,
    SPAN_PERSIST_COMPLETE,
    SPAN_PERSIST_FAIL,
    SPAN_RUN,
    capture_spans,
    get_tracer,
)
from research_platform.runs.contracts import ResearchMode
from research_platform.tools.fakes import FakeCorpus

_CASES_PATH = Path(__file__).parents[1] / "benchmarks/phase3/regression-cases-v2.json"


def _case(case_id: str) -> tuple[RegressionCase, FakeCorpus]:
    cases = load_cases(_CASES_PATH)
    corpus = load_corpus(_CASES_PATH)
    return next(item for item in cases if item.case_id == case_id), corpus


def _quick_case_id() -> str:
    return next(
        case.case_id
        for case in load_cases(_CASES_PATH)
        if case.request.mode is ResearchMode.QUICK
    )


def _run(
    case_id: str, content: TraceContent = TraceContent.IDS
) -> tuple[CaseRun, tuple[ReadableSpan, ...]]:
    case, corpus = _case(case_id)

    async def exercise() -> tuple[CaseRun, tuple[ReadableSpan, ...]]:
        with capture_spans(content) as exporter:
            case_run = await run_case_detailed(case, corpus)
            spans = tuple(exporter.get_finished_spans())
        assert case_run.result.passed, case_run.result.mismatches
        return case_run, spans

    return asyncio.run(exercise())


def test_one_root_span_per_run() -> None:
    _, spans = _run("route-01-search-path")
    roots = [span for span in spans if span.name == SPAN_RUN]

    assert len(roots) == 1
    assert all(span.context.trace_id != 0 for span in spans)
    assert {span.context.trace_id for span in spans} == {roots[0].context.trace_id}


def test_root_span_attributes() -> None:
    case_run, spans = _run("route-01-search-path")
    root = next(span for span in spans if span.name == SPAN_RUN)
    attributes = root.attributes or {}

    assert attributes[ATTR_RUN_ID] == str(case_run.run_id)
    assert attributes[ATTR_MODE] == "deep_research"
    assert attributes[ATTR_STATUS] == "completed"
    assert str(attributes[ATTR_CONFIGURATION_ID]).startswith("sha256:")
    assert attributes[ATTR_SNAPSHOT_ID]
    assert attributes[ATTR_CODE_REVISION]
    assert attributes[ATTR_ANSWER_OUTCOME] == "answered"


def test_provenance_trace_id_is_root_trace_id() -> None:
    async def exercise() -> None:
        with capture_spans() as exporter:
            case, corpus = _case("route-01-search-path")
            case_run = await run_case_detailed(case, corpus)
            root = next(
                span for span in exporter.get_finished_spans() if span.name == SPAN_RUN
            )
            view = await case_run.store.get_run_view(case_run.run_id)

        assert view.provenance is not None
        assert view.provenance.trace_id == format(root.context.trace_id, "032x")

    asyncio.run(exercise())


def test_node_and_tool_spans_nest() -> None:
    _, spans = _run("route-01-search-path")
    by_name = {span.name: span for span in spans}

    assert {
        "node.plan",
        "node.execute",
        "tool.search_papers",
        "tool.search_evidence",
    } <= set(by_name)
    assert by_name["tool.search_papers"].parent is not None
    assert (
        by_name["tool.search_papers"].parent.span_id
        == by_name["node.execute"].context.span_id
    )


def test_persist_complete_span() -> None:
    _, spans = _run(_quick_case_id())

    assert any(span.name == SPAN_PERSIST_COMPLETE for span in spans)


def test_failed_run_marks_root_error() -> None:
    _, spans = _run("failure-01-model-unavailable")
    root = next(span for span in spans if span.name == SPAN_RUN)

    assert root.status.status_code is StatusCode.ERROR
    assert root.attributes[ATTR_FAILURE_CATEGORY] == "model_unavailable"
    assert any(span.name == SPAN_PERSIST_FAIL for span in spans)


def test_tool_arguments_only_at_full() -> None:
    case_id = _quick_case_id()
    _, ids_spans = _run(case_id, TraceContent.IDS)
    _, full_spans = _run(case_id, TraceContent.FULL)
    ids_tool = next(span for span in ids_spans if span.name == "tool.search_papers")
    full_tool = next(span for span in full_spans if span.name == "tool.search_papers")

    assert ATTR_TOOL_ARGUMENTS not in (ids_tool.attributes or {})
    assert ATTR_TOOL_ARGUMENTS in (full_tool.attributes or {})


def test_quick_graph_nodes_traced() -> None:
    cases = load_cases(_CASES_PATH)
    quick_case = next(case for case in cases if case.request.mode is ResearchMode.QUICK)
    _, spans = _run(quick_case.case_id)
    root = next(span for span in spans if span.name == SPAN_RUN)
    answer_node = next(span for span in spans if span.name == "node.answer")

    assert answer_node.parent is not None
    assert answer_node.parent.span_id == root.context.span_id


def test_quick_tool_spans_nest_under_nodes() -> None:
    _, spans = _run(_quick_case_id())
    by_name = {span.name: span for span in spans}

    for tool_name, node_name in (
        ("tool.search_papers", "node.search_papers"),
        ("tool.search_evidence", "node.search_evidence"),
    ):
        assert by_name[tool_name].parent is not None
        assert by_name[tool_name].parent.span_id == by_name[node_name].context.span_id


def test_log_line_has_trace_id_inside_span() -> None:
    records: list[str] = []
    logger = logging.getLogger("test_tracing_runs")

    class CollectingHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(JsonFormatter().format(record))

    collecting = CollectingHandler()
    original_level = logger.level
    logger.addHandler(collecting)
    logger.setLevel(logging.INFO)
    try:
        with capture_spans():
            with get_tracer().start_as_current_span("log-contract") as span:
                logger.info("trace-contract")
                expected_trace_id = format(span.get_span_context().trace_id, "032x")
                expected_span_id = format(span.get_span_context().span_id, "016x")
    finally:
        logger.removeHandler(collecting)
        logger.setLevel(original_level)

    payload = json.loads(records[0])
    assert payload["trace_id"] == expected_trace_id
    assert payload["span_id"] == expected_span_id
