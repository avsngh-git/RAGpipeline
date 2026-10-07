"""Search and citation tracing contract tests."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

from research_platform.ingestion.evidence import ExtractedTable, TableCell
from research_platform.ingestion.indexing import (
    IndexConfiguration,
    IndexInput,
    IndexMatch,
    ReadySnapshotIndex,
)
from research_platform.ingestion.snapshot_selection import SnapshotSelection
from research_platform.observability.content import TraceContent
from research_platform.observability.tracing import (
    ATTR_SEARCH_FALLBACK,
    ATTR_SEARCH_QUERY,
    ATTR_SEARCH_TOP_IDS,
    ATTR_SEARCH_TOP_SCORES,
    SPAN_CITATION_LOOKUP,
    SPAN_SEARCH,
    SPAN_SEARCH_DENSE,
    SPAN_SEARCH_ELIGIBILITY,
    SPAN_SEARCH_FUSION,
    SPAN_SEARCH_HYDRATE,
    SPAN_SEARCH_LEXICAL,
    SPAN_SEARCH_RERANK,
    SPAN_SEARCH_SELECT,
    capture_spans,
)
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
from research_platform.search.dense_search import DenseSearchResponse, HydratedDenseHit
from research_platform.search.hybrid_search import HybridEvidenceSearch
from research_platform.search.lexical import (
    SCIENTIFIC_BM25_IDENTITY,
    LexicalHit,
    LexicalSearchResult,
)
from research_platform.search.lexical_branches import LexicalBranchIdentity
from research_platform.search.paper_graph import CitationDirection, CitationGraphReader
from research_platform.search.profile_manifest import (
    load_frozen_profile,
    load_retrieval_profile_manifest,
)
from research_platform.search.profiles import (
    CandidateLimits,
    DenseIndexIdentity,
    FusionSettings,
    RetrievalProfile,
)
from research_platform.search.reranker import CrossEncoderReranker

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_ID = UUID("4b11fab3-d4a5-4e7a-a58e-8654accf2c6c")
DOCUMENT_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
EXTRACTION_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")


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
        self.profiles = []

    async def search_query(self, profile, query, *, filters, ready_index=None):
        self.profiles.append(profile)
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
        self.requested: list[tuple[tuple[UUID, int], ...]] = []

    async def load_tables_for_search(self, requested_tables):
        key = (EXTRACTION_ID, self.table.ordinal)
        self.requested.append(tuple(requested_tables))
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


def _executor(
    dense_search: object | None = None,
) -> tuple[
    Phase2SearchExecutor,
    CrossEncoderReranker,
    _Hybrid,
    object,
    _EvidenceRepository,
]:
    manifest_dir = ROOT / "benchmarks/phase2"
    from research_platform.search.active_profile import resolve_frozen_profile_path

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
        dense_search=object() if dense_search is None else dense_search,
        reranker=reranker,
        evidence_repository=evidence_repository,
    )
    return executor, reranker, hybrid, profile, evidence_repository


def _request(profile, operation: SearchOperation, *, mode=RetrievalMode.RERANKED):
    return SearchRequest(
        query="synthetic table outcomes",
        snapshot_id=profile.snapshot.snapshot_id,
        retrieval_profile_id=profile.profile_id,
        mode=mode,
        operation=operation,
        filters=SearchFilters(),
        limit=10,
    )


SNAPSHOT_ID = UUID("f1336240-dda0-45fb-a5b1-ff399bd93436")
SNAPSHOT_CONFIG_ID = "sha256:" + "a" * 64
CHUNK_SELECTION_ID = "sha256:" + "b" * 64
DENSE_CONFIG_ID = "sha256:" + "c" * 64


def _profile() -> RetrievalProfile:
    return RetrievalProfile(
        snapshot=SnapshotSelection(
            snapshot_id=SNAPSHOT_ID,
            snapshot_configuration_id=SNAPSHOT_CONFIG_ID,
            chunk_selection_id=CHUNK_SELECTION_ID,
        ),
        lexical_index=SCIENTIFIC_BM25_IDENTITY,
        dense_index=DenseIndexIdentity(
            model="test-model",
            revision="revision-a",
            preprocessing_revision="passage-query-v1",
            dimensions=2,
            maximum_input_tokens=64,
            index_configuration_id=DENSE_CONFIG_ID,
        ),
        fusion=FusionSettings(rank_constant=60),
        candidate_limits=CandidateLimits(
            lexical_top_k=2,
            dense_top_k=3,
            fused_top_k=2,
            rerank_top_k=None,
        ),
    )


def _lexical_hit(evidence_id: str, score: float, row: int) -> LexicalHit:
    return LexicalHit(evidence_id, "W123", row, score)


def _dense_hit(evidence_id: str, rank: int, score: float) -> HydratedDenseHit:
    evidence = IndexInput(
        evidence_id=evidence_id,
        text="evidence text",
        payload={
            "paper_id": "W123",
            "document_id": "document",
            "extraction_id": "extraction",
            "snapshot_id": str(SNAPSHOT_ID),
        },
    )
    return HydratedDenseHit(rank=rank, score=score, evidence=evidence)


class _LexicalBranch:
    def __init__(self, profile: RetrievalProfile, result: LexicalSearchResult) -> None:
        self.profile = profile
        self.identity = LexicalBranchIdentity(
            role="evidence",
            snapshot_status="finalized",
            profile_id=profile.profile_id,
            snapshot=profile.snapshot,
            candidate_limit=profile.candidate_limits.lexical_top_k,
        )
        self.result = result
        self.error: Exception | None = None
        self.calls: list[tuple[str, int, SearchFilters]] = []

    async def search_with_stats(
        self,
        query: str,
        *,
        limit: int,
        filters: SearchFilters = SearchFilters(),
    ) -> LexicalSearchResult:
        self.calls.append((query, limit, filters))
        if self.error is not None:
            raise self.error
        if filters == SearchFilters():
            return self.result
        return replace(
            self.result,
            hits=(),
            available_count=0,
            eligible_count=0,
            truncated=False,
            applied_filters=filters,
        )


class _DenseBranch:
    def __init__(
        self, hits: tuple[HydratedDenseHit, ...], available_count: int
    ) -> None:
        self.hits = hits
        self.available_count = available_count
        self.error: Exception | None = None
        self.calls: list[tuple[RetrievalProfile, str, int, SearchFilters, bool]] = []

    def _response(
        self,
        profile: RetrievalProfile,
        query: str,
        limit: int,
        filters: SearchFilters,
        evaluation: bool,
    ) -> DenseSearchResponse:
        self.calls.append((profile, query, limit, filters, evaluation))
        if self.error is not None:
            raise self.error
        selected_hits = self.hits if filters == SearchFilters() else ()
        available_count = self.available_count if filters == SearchFilters() else 0
        matches = tuple(
            IndexMatch(hit.evidence.evidence_id, hit.score, {}) for hit in selected_hits
        )
        return DenseSearchResponse(
            snapshot_id=profile.snapshot.snapshot_id,
            profile_id=profile.profile_id,
            index_configuration_id=profile.dense_index.index_configuration_id,
            requested_limit=limit,
            hits=matches,
            hydrated_hits=selected_hits,
            candidate_count=available_count,
            truncated=available_count > limit,
            applied_filters=filters,
        )

    async def search_hybrid_component_query(
        self,
        profile: RetrievalProfile,
        query: str,
        *,
        limit: int,
        filters: SearchFilters = SearchFilters(),
    ) -> DenseSearchResponse:
        return self._response(profile, query, limit, filters, False)

    async def evaluate_hybrid_component_query(
        self,
        profile: RetrievalProfile,
        query: str,
        *,
        limit: int,
        filters: SearchFilters = SearchFilters(),
    ) -> DenseSearchResponse:
        return self._response(profile, query, limit, filters, True)


def _service(
    profile: RetrievalProfile,
) -> tuple[HybridEvidenceSearch, _LexicalBranch, _DenseBranch]:
    lexical_result = LexicalSearchResult(
        hits=(_lexical_hit("a", 9.0, 0), _lexical_hit("b", 8.0, 1)),
        available_count=5,
        eligible_count=5,
        limit=2,
        truncated=True,
    )
    lexical = _LexicalBranch(profile, lexical_result)
    dense = _DenseBranch(
        (_dense_hit("b", 1, 0.9), _dense_hit("c", 2, 0.8), _dense_hit("d", 3, 0.7)),
        available_count=5,
    )
    return HybridEvidenceSearch(lexical, dense), lexical, dense


def test_reranked_search_spans() -> None:
    executor, reranker, _hybrid, profile, _evidence_repository = _executor()
    try:
        with capture_spans() as exporter:
            asyncio.run(
                executor.execute(
                    _request(profile, SearchOperation.EVIDENCE_SEARCH),
                    request_id="trace-reranked-search",
                )
            )
    finally:
        reranker.close()

    spans = exporter.get_finished_spans()
    search = next(span for span in spans if span.name == SPAN_SEARCH)
    children = {
        span.name
        for span in spans
        if span.parent is not None and span.parent.span_id == search.context.span_id
    }
    assert {
        SPAN_SEARCH_ELIGIBILITY,
        SPAN_SEARCH_RERANK,
        SPAN_SEARCH_HYDRATE,
        SPAN_SEARCH_SELECT,
    } <= children


def test_search_span_top_ids_and_scores() -> None:
    executor, reranker, _hybrid, profile, _evidence_repository = _executor()
    try:
        with capture_spans() as exporter:
            response = asyncio.run(
                executor.execute(
                    _request(profile, SearchOperation.EVIDENCE_SEARCH),
                    request_id="trace-top-hits",
                )
            )
    finally:
        reranker.close()

    search = next(
        span for span in exporter.get_finished_spans() if span.name == SPAN_SEARCH
    )
    attributes = search.attributes or {}
    assert attributes[ATTR_SEARCH_TOP_IDS] == tuple(
        hit.chunk_id for hit in response.hits
    )
    assert len(attributes[ATTR_SEARCH_TOP_SCORES]) == len(
        attributes[ATTR_SEARCH_TOP_IDS]
    )


def test_query_text_only_at_full() -> None:
    executor, reranker, _hybrid, profile, _evidence_repository = _executor()
    try:
        with capture_spans(TraceContent.IDS) as ids_exporter:
            asyncio.run(
                executor.execute(
                    _request(profile, SearchOperation.EVIDENCE_SEARCH),
                    request_id="trace-query-ids",
                )
            )
        with capture_spans(TraceContent.FULL) as full_exporter:
            asyncio.run(
                executor.execute(
                    _request(profile, SearchOperation.EVIDENCE_SEARCH),
                    request_id="trace-query-full",
                )
            )
    finally:
        reranker.close()

    ids_search = next(
        span for span in ids_exporter.get_finished_spans() if span.name == SPAN_SEARCH
    )
    full_search = next(
        span for span in full_exporter.get_finished_spans() if span.name == SPAN_SEARCH
    )
    assert ATTR_SEARCH_QUERY not in (ids_search.attributes or {})
    assert (full_search.attributes or {})[
        ATTR_SEARCH_QUERY
    ] == "synthetic table outcomes"


def test_fallback_attribute_on_reranker_failure() -> None:
    executor, reranker, _hybrid, profile, _evidence_repository = _executor()
    try:
        with capture_spans() as exporter:
            asyncio.run(
                executor.execute(
                    _request(profile, SearchOperation.EVIDENCE_SEARCH),
                    request_id="trace-reranker-fallback",
                )
            )
    finally:
        reranker.close()

    rerank = next(
        span
        for span in exporter.get_finished_spans()
        if span.name == SPAN_SEARCH_RERANK
    )
    assert (rerank.attributes or {})[ATTR_SEARCH_FALLBACK] is True


def test_hybrid_stage_spans() -> None:
    profile = _profile()
    service, _lexical, _dense = _service(profile)

    with capture_spans() as exporter:
        asyncio.run(service.search_query(profile, "synthetic query"))

    names = {span.name for span in exporter.get_finished_spans()}
    assert {SPAN_SEARCH_LEXICAL, SPAN_SEARCH_DENSE, SPAN_SEARCH_FUSION} <= names


class _EmptyGraphConnection:
    class _Transaction:
        async def __aenter__(self) -> None:
            return None

        async def __aexit__(self, *_args: object) -> None:
            return None

    def transaction(self, **_kwargs: object) -> _Transaction:
        return self._Transaction()

    async def fetchrow(self, _query: str, *_arguments: object) -> dict[str, object]:
        return {
            "snapshot_exists": True,
            "resolved_count": 0,
            "local_paper_id": None,
            "snapshot_paper_id": None,
        }


class _GraphAcquire:
    def __init__(self, connection: _EmptyGraphConnection) -> None:
        self.connection = connection

    async def __aenter__(self) -> _EmptyGraphConnection:
        return self.connection

    async def __aexit__(self, *_args: object) -> None:
        return None


class _GraphPool:
    def acquire(self) -> _GraphAcquire:
        return _GraphAcquire(_EmptyGraphConnection())


def test_citation_lookup_span() -> None:
    with capture_spans() as exporter:
        asyncio.run(
            CitationGraphReader(_GraphPool()).read_one_hop(
                UUID("4b11fab3-d4a5-4e7a-a58e-8654accf2c6c"),
                "W123",
                CitationDirection.REFERENCES,
            )
        )

    assert any(
        span.name == SPAN_CITATION_LOOKUP for span in exporter.get_finished_spans()
    )
