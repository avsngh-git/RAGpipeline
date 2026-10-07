"""Phase 4 gate contract for a scripted research run's traces and logs."""

from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

from opentelemetry.sdk.trace import ReadableSpan

from research_platform.evaluation.phase3_regression import (
    CaseRun,
    RegressionCase,
    load_cases,
    load_corpus,
    run_case_detailed,
)
from research_platform.ingestion.evidence import ExtractedTable, TableCell
from research_platform.ingestion.indexing import (
    IndexConfiguration,
    IndexInput,
    ReadySnapshotIndex,
)
from research_platform.observability.content import TraceContent
from research_platform.observability.logging_config import JsonFormatter
from research_platform.observability.tracing import (
    ATTR_ANSWER_OUTCOME,
    ATTR_CODE_REVISION,
    ATTR_CONFIGURATION_ID,
    ATTR_LLM_KIND,
    ATTR_LLM_ORDINAL,
    ATTR_LLM_PROMPT_VERSION,
    ATTR_MODE,
    ATTR_RESUME_COUNT,
    ATTR_RETRIEVAL_PROFILE_ID,
    ATTR_RUN_ID,
    ATTR_SNAPSHOT_ID,
    ATTR_STATUS,
    GEN_AI_REQUEST_MODEL,
    LF_INPUT,
    LF_OBSERVATION_TYPE,
    LF_SESSION_ID,
    LF_TRACE_NAME,
    SPAN_RUN,
    capture_spans,
)
from research_platform.runs.contracts import configuration_id
from research_platform.search.active_profile import resolve_frozen_profile_path
from research_platform.search.application import (
    Phase2SearchExecutor,
    SnapshotEligibility,
)
from research_platform.search.contracts import (
    ComponentScores,
    RankedComponent,
    RetrievalMode,
    SearchFilters,
    SearchOperation,
    SearchRequest,
)
from research_platform.search.profile_manifest import (
    load_frozen_profile,
    load_retrieval_profile_manifest,
)
from research_platform.search.profiles import RetrievalProfile
from research_platform.search.reranker import CrossEncoderReranker
from research_platform.tools.fakes import FakeCorpus

ROOT = Path(__file__).resolve().parents[1]
CASES_PATH = ROOT / "benchmarks/phase3/regression-cases-v2.json"
QUESTION_MARKER = "zq7731 private question marker"
PASSAGE_TEXT = "retrieval improves ranking with evidence and citations"
SNAPSHOT_ID = UUID("4b11fab3-d4a5-4e7a-a58e-8654accf2c6c")
DOCUMENT_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
EXTRACTION_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")


def _scripted_case() -> tuple[RegressionCase, FakeCorpus]:
    cases = load_cases(CASES_PATH)
    corpus = load_corpus(CASES_PATH)
    case = next(item for item in cases if item.case_id == "route-01-search-path")
    case = dataclasses.replace(
        case,
        request=case.request.model_copy(update={"question": QUESTION_MARKER}),
    )
    return case, corpus


def _run(
    content: TraceContent = TraceContent.IDS,
) -> tuple[CaseRun, tuple[ReadableSpan, ...], tuple[str, ...]]:
    case, corpus = _scripted_case()
    lines: list[str] = []

    class CollectingHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            lines.append(JsonFormatter().format(record))

    handler = CollectingHandler(level=logging.INFO)
    root_logger = logging.getLogger()
    original_level = root_logger.level
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(handler)
    try:
        with capture_spans(content) as exporter:
            case_run = await_run_case(case, corpus)
            spans = tuple(exporter.get_finished_spans())
    finally:
        root_logger.removeHandler(handler)
        root_logger.setLevel(original_level)
    assert case_run.result.passed, case_run.result.mismatches
    return case_run, spans, tuple(lines)


def await_run_case(case: RegressionCase, corpus: FakeCorpus) -> CaseRun:
    return asyncio.run(run_case_detailed(case, corpus))


def _attributes(span: ReadableSpan) -> dict[str, object]:
    return dict(span.attributes or {})


def test_required_spans_present() -> None:
    _, spans, _ = _run()

    assert {
        "research_run",
        "node.plan",
        "node.execute",
        "node.evaluate",
        "node.answer",
        "tool.search_papers",
        "tool.search_evidence",
        "llm.plan",
        "llm.evaluate",
        "llm.synthesize",
        "synthesize",
        "verify_citations",
        "persist.complete_run",
    } <= {span.name for span in spans}


def test_single_connected_tree() -> None:
    _, spans, _ = _run()
    trace_ids = {span.context.trace_id for span in spans}
    roots = [span for span in spans if span.parent is None]
    span_ids = {span.context.span_id for span in spans}

    assert len(trace_ids) == 1
    assert len(roots) == 1
    assert roots[0].name == "research_run"
    assert all(span.parent is None or span.parent.span_id in span_ids for span in spans)


def test_root_attributes_complete() -> None:
    case_run, spans, _ = _run()
    root = next(span for span in spans if span.name == SPAN_RUN)
    attributes = _attributes(root)

    assert {
        ATTR_RUN_ID,
        ATTR_MODE,
        ATTR_STATUS,
        ATTR_CONFIGURATION_ID,
        ATTR_SNAPSHOT_ID,
        ATTR_RETRIEVAL_PROFILE_ID,
        ATTR_CODE_REVISION,
        ATTR_RESUME_COUNT,
        ATTR_ANSWER_OUTCOME,
        LF_TRACE_NAME,
        LF_SESSION_ID,
    } <= attributes.keys()
    assert attributes[ATTR_RUN_ID] == str(case_run.run_id)


def test_generation_spans_complete() -> None:
    _, spans, _ = _run()
    generation_spans = [span for span in spans if span.name.startswith("llm.")]

    assert generation_spans
    for span in generation_spans:
        attributes = _attributes(span)
        assert attributes[LF_OBSERVATION_TYPE] == "generation"
        assert {
            GEN_AI_REQUEST_MODEL,
            ATTR_LLM_KIND,
            ATTR_LLM_ORDINAL,
            ATTR_LLM_PROMPT_VERSION,
        } <= attributes.keys()


def test_no_text_in_ids_mode() -> None:
    _, spans, _ = _run(TraceContent.IDS)

    for span in spans:
        for value in _attributes(span).values():
            assert "zq7731" not in str(value)
            assert PASSAGE_TEXT not in str(value)


def test_full_mode_captures_prompt_text() -> None:
    _, spans, _ = _run(TraceContent.FULL)
    synthesize = next(span for span in spans if span.name == "llm.synthesize")

    assert PASSAGE_TEXT in str(_attributes(synthesize)[LF_INPUT])


def test_logs_have_run_and_trace_fields() -> None:
    _, spans, lines = _run()
    root = next(span for span in spans if span.name == SPAN_RUN)
    finished = [line for line in lines if '"message": "research_run_finished"' in line]

    assert len(finished) == 1
    payload = json.loads(finished[0])
    assert {
        "run_id",
        "trace_id",
        "mode",
        "status",
        "duration_seconds",
        "tool_calls",
        "model_calls",
    } <= payload.keys()
    assert payload["trace_id"] == format(root.context.trace_id, "032x")


def test_no_text_in_logs() -> None:
    _, _, lines = _run()

    assert all("zq7731" not in line and PASSAGE_TEXT not in line for line in lines)


def test_run_records_match_trace() -> None:
    case_run, spans, _ = _run()
    root = next(span for span in spans if span.name == SPAN_RUN)

    async def inspect_records() -> None:
        calls = await case_run.store.list_llm_calls(case_run.run_id)
        view = await case_run.store.get_run_view(case_run.run_id)
        assert view.provenance is not None
        assert len(calls) == sum(span.name.startswith("llm.") for span in spans)
        assert view.provenance.trace_id == format(root.context.trace_id, "032x")
        loaded = await case_run.store.load_run_configuration(
            view.provenance.configuration_id
        )
        assert configuration_id(loaded) == view.provenance.configuration_id

    asyncio.run(inspect_records())


class _TokenCounter:
    def count_pair(self, query: str, evidence_text: str) -> int:
        return 16


class _FailingScorer:
    def __init__(self, repository: _Repository) -> None:
        self.repository = repository

    def score_pairs(self, pairs: tuple[tuple[str, str], ...]) -> list[float]:
        assert self.repository.active_scope is None
        raise RuntimeError("private model failure")


class _Repository:
    def __init__(self, evidence: tuple[IndexInput, ...]) -> None:
        self.by_id = {item.evidence_id: item for item in evidence}
        self.active_scope: ReadySnapshotIndex | None = None

    @asynccontextmanager
    async def serving_index(
        self, snapshot_selection, configuration
    ) -> AsyncIterator[ReadySnapshotIndex]:
        ready = ReadySnapshotIndex(
            snapshot_status="finalized",
            snapshot_selection=snapshot_selection,
            configuration_id=configuration.configuration_id,
            collection_name=configuration.collection_name,
            expected_count=len(self.by_id),
            selected_chunk_ids=frozenset(self.by_id),
        )
        self.active_scope = ready
        try:
            yield ready
        finally:
            self.active_scope = None

    def read_index_scope_is_active(self, ready: ReadySnapshotIndex) -> bool:
        return self.active_scope is ready

    async def hydrate_snapshot_matches(self, snapshot, configuration, matches):
        assert self.active_scope is not None
        return tuple(self.by_id[match.evidence_id] for match in matches)


class _Eligibility:
    async def read(self, snapshot_id: UUID, *, filters: SearchFilters):
        return SnapshotEligibility(
            paper_metadata={"W123": ("Synthetic paper", 2025)},
            evidence_counts_by_paper={"W123": 3},
        )


class _Hybrid:
    def __init__(self, hits: tuple[object, ...]) -> None:
        self.hits = hits

    async def search_query(self, profile, query, *, filters, ready_index=None):
        return SimpleNamespace(
            hits=self.hits,
            lexical_pool=SimpleNamespace(available_count=len(self.hits)),
            dense_pool=SimpleNamespace(available_count=len(self.hits)),
            fused_pool=SimpleNamespace(available_count=len(self.hits)),
            truncated=False,
            lexical_duration_ms=1.0,
            dense_duration_ms=2.0,
            fusion_duration_ms=3.0,
        )


class _PaperLexical:
    async def search_with_stats(self, query, *, eligible_ids, limit):
        assert eligible_ids == {"W123"}
        return SimpleNamespace(
            hits=(SimpleNamespace(paper_id="W123", score=1.0),), truncated=False
        )


class _EvidenceRepository:
    def __init__(self, table: ExtractedTable) -> None:
        self.table = table

    async def load_tables_for_search(self, requested_tables):
        key = (EXTRACTION_ID, self.table.ordinal)
        return {key: self.table} if key in requested_tables else {}


def _table() -> ExtractedTable:
    return ExtractedTable(
        ordinal=0,
        caption="Synthetic outcomes",
        units="count",
        footnotes=(),
        header_rows=1,
        cells=(
            TableCell(0, 0, "Group"),
            TableCell(0, 1, "Outcome"),
            TableCell(1, 0, "Treatment"),
            TableCell(1, 1, "42"),
        ),
    )


def _evidence_input(index: int, *, table: bool = False) -> IndexInput:
    evidence_id = f"sha256:{index:064x}"
    metadata: dict[str, object] = {}
    kind = "text"
    text = f"synthetic evidence {index}"
    if table:
        kind = "table_row_group"
        text = "Treatment | 42"
        metadata = {
            "table_ordinal": 0,
            "header_rows_repeated": 1,
            "row_start_inclusive": 1,
            "row_end_exclusive": 2,
        }
    return IndexInput(
        evidence_id=evidence_id,
        text=text,
        payload={
            "paper_id": "W123",
            "document_id": str(DOCUMENT_ID),
            "extraction_id": str(EXTRACTION_ID),
            "snapshot_id": str(SNAPSHOT_ID),
            "source_location": {"page_index_zero_based": 4},
            "source_spans": [],
            "evidence_metadata": metadata,
            "evidence_kind": kind,
            "document_version": "published-2025",
            "document_version_kind": "published",
            "chunking_configuration_id": None,
            "section_ordinal": 0,
            "start_offset": 0,
            "end_offset": len(text),
        },
    )


def _executor() -> tuple[Phase2SearchExecutor, CrossEncoderReranker, RetrievalProfile]:
    manifest_dir = ROOT / "benchmarks/phase2"
    profile = load_frozen_profile(
        resolve_frozen_profile_path(manifest_dir / "active-profile.toml")
    )
    hybrid_profile = load_retrieval_profile_manifest(
        manifest_dir / "hybrid-e5-profile-v1.toml"
    )
    inputs = (_evidence_input(1, table=True), _evidence_input(2), _evidence_input(3))
    hybrid_hits = tuple(
        SimpleNamespace(
            evidence_id=item.evidence_id,
            score=1.0 / rank,
            component_scores=ComponentScores(
                lexical=RankedComponent(rank=rank, score=1.0 / rank),
                dense=RankedComponent(rank=rank, score=0.9 / rank),
                fusion=RankedComponent(rank=rank, score=1.0 / (60 + rank)),
            ),
        )
        for rank, item in enumerate(inputs, start=1)
    )
    hybrid = _Hybrid(hybrid_hits)
    repository = _Repository(inputs)
    reranker = CrossEncoderReranker(
        profile.reranker,
        token_counter=_TokenCounter(),
        scorer=_FailingScorer(repository),
        timeout_seconds=1.0,
    )
    evidence_repository = _EvidenceRepository(_table())
    configuration = IndexConfiguration(
        collection_name="phase2-executor-test",
        embedding_model=profile.dense_index.model,
        embedding_revision=profile.dense_index.revision,
        preprocessing_revision=profile.dense_index.preprocessing_revision,
        vector_size=profile.dense_index.dimensions,
        distance="Cosine",
        batch_size=2,
        maximum_input_tokens=profile.dense_index.maximum_input_tokens,
    )
    executor = Phase2SearchExecutor(
        pool=object(),
        index_configuration=configuration,
        repository=repository,
        eligibility_reader=_Eligibility(),
        profiles_by_id={profile.profile_id: profile},
        modes_by_profile_id={profile.profile_id: RetrievalMode.RERANKED},
        lexical_evidence={},
        lexical_papers={profile.profile_id: _PaperLexical()},
        hybrid_profile=hybrid_profile,
        hybrid_search=hybrid,
        dense_search=object(),
        reranker=reranker,
        evidence_repository=evidence_repository,
    )
    return executor, reranker, profile


def test_search_stage_tree() -> None:
    executor, reranker, profile = _executor()
    request = SearchRequest(
        query="synthetic table outcomes",
        snapshot_id=profile.snapshot.snapshot_id,
        retrieval_profile_id=profile.profile_id,
        mode=RetrievalMode.RERANKED,
        operation=SearchOperation.EVIDENCE_SEARCH,
        filters=SearchFilters(),
        limit=10,
    )
    try:
        with capture_spans() as exporter:
            asyncio.run(executor.execute(request, request_id="trace-gate-search"))
        spans = exporter.get_finished_spans()
    finally:
        reranker.close()

    search = next(span for span in spans if span.name == "search")
    children = {
        span.name
        for span in spans
        if span.parent is not None and span.parent.span_id == search.context.span_id
    }
    assert {
        "search.eligibility",
        "search.rerank",
        "search.hydrate",
        "search.select",
    } <= children
