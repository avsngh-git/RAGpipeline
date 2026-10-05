"""CPU-only regressions for the composed Phase 2 search executor."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

from research_platform.ingestion.embeddings import EmbeddingInferenceBusy
from research_platform.ingestion.evidence import ExtractedTable, TableCell
from research_platform.ingestion.indexing import (
    IndexConfiguration,
    IndexInput,
    ReadySnapshotIndex,
)
from research_platform.search.application import (
    Phase2SearchExecutor,
    RetrievalExecutionFailure,
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
from research_platform.search.generation_search import GenerationDenseSearch
from research_platform.search.profile_manifest import (
    load_frozen_profile,
    load_retrieval_profile_manifest,
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


def test_executor_composes_fallback_table_context_and_paper_fusion() -> None:
    executor, reranker, hybrid, profile, evidence_repository = _executor()
    try:
        evidence_response = asyncio.run(
            executor.execute(
                _request(profile, SearchOperation.EVIDENCE_SEARCH),
                request_id="synthetic-evidence",
            )
        )
        paper_response = asyncio.run(
            executor.execute(
                _request(profile, SearchOperation.PAPER_SEARCH),
                request_id="synthetic-paper",
            )
        )
    finally:
        reranker.close()

    assert [hit.chunk_id for hit in evidence_response.hits] == [
        f"sha256:{index:064x}" for index in (1, 2)
    ]
    assert evidence_response.requested_mode is RetrievalMode.RERANKED
    assert evidence_response.effective_mode is RetrievalMode.HYBRID
    assert evidence_response.effective_configuration_id == hybrid.profiles[0].profile_id
    table_hit = evidence_response.hits[0]
    assert table_hit.table_context is not None
    assert table_hit.table_context.caption == "Synthetic outcomes"
    assert [hit.paper_id for hit in paper_response.hits] == ["W123"]
    assert paper_response.effective_mode is RetrievalMode.HYBRID
    assert paper_response.hits[0].component_scores.fusion.score == 2 / 11
    assert paper_response.hits[0].supporting_evidence[0].table_context is not None

    # Hybrid E5 ranks upstream evidence at k=60; the selected profile's final
    # paper metadata/evidence fusion uses k=10.
    assert len(hybrid.profiles) == 2
    assert hybrid.profiles[0] == hybrid.profiles[1]
    assert hybrid.profiles[0].fusion.rank_constant == 60
    assert profile.fusion.rank_constant == 10
    assert evidence_repository.requested == [
        ((EXTRACTION_ID, 0),),
        ((EXTRACTION_ID, 0),),
    ]


def test_executor_rejects_incompatible_profile_mode_before_search() -> None:
    executor, reranker, hybrid, profile, _evidence_repository = _executor()
    try:
        try:
            asyncio.run(
                executor.execute(
                    _request(
                        profile,
                        SearchOperation.EVIDENCE_SEARCH,
                        mode=RetrievalMode.HYBRID,
                    ),
                    request_id="synthetic-incompatible",
                )
            )
        except ValueError as error:
            assert "mode does not match" in str(error)
        else:
            raise AssertionError("an incompatible profile mode must fail closed")
    finally:
        reranker.close()

    assert hybrid.profiles == []


class _BusyDense:
    async def search_query(self, profile, query, *, limit, filters):
        raise EmbeddingInferenceBusy("synthetic occupied worker")


def test_dense_embedding_saturation_is_a_safe_retrieval_failure() -> None:
    executor, reranker, _hybrid, profile, _evidence_repository = _executor()
    executor._modes[profile.profile_id] = RetrievalMode.DENSE
    executor._dense = _BusyDense()
    try:
        try:
            asyncio.run(
                executor.execute(
                    _request(
                        profile,
                        SearchOperation.EVIDENCE_SEARCH,
                        mode=RetrievalMode.DENSE,
                    ),
                    request_id="synthetic-dense-busy",
                )
            )
        except RetrievalExecutionFailure as error:
            assert str(error) == "the required dense stage failed"
        else:
            raise AssertionError("embedding saturation must fail closed")
    finally:
        reranker.close()


class _GenerationDense(GenerationDenseSearch):
    def __init__(self, inputs: dict[str, IndexInput]) -> None:
        self.inputs = inputs
        self.reads: list[tuple[UUID, tuple[str, ...]]] = []

    async def read_evidence(self, snapshot_id, evidence_ids):
        self.reads.append((snapshot_id, tuple(evidence_ids)))
        return tuple(self.inputs[evidence_id] for evidence_id in evidence_ids)


class _NoLeaseRepository(_Repository):
    def serving_index(self, snapshot_selection, configuration):
        raise AssertionError("the Qdrant content path must not open a snapshot lease")

    async def hydrate_snapshot_matches(self, snapshot, configuration, matches):
        raise AssertionError("the Qdrant content path must not read PostgreSQL text")


def test_qdrant_content_source_reads_evidence_from_generation_search() -> None:
    inputs = (_evidence_input(1, table=True), _evidence_input(2), _evidence_input(3))
    dense = _GenerationDense({item.evidence_id: item for item in inputs})
    executor, reranker, _hybrid, profile, _evidence = _executor(dense)
    executor._repository = _NoLeaseRepository(inputs)  # type: ignore[assignment]
    try:
        response = asyncio.run(
            executor.execute(
                _request(profile, SearchOperation.EVIDENCE_SEARCH),
                request_id="synthetic-qdrant-content",
            )
        )
    finally:
        reranker.close()

    assert [hit.chunk_id for hit in response.hits] == [
        f"sha256:{index:064x}" for index in (1, 2)
    ]
    assert dense.reads == [
        (profile.snapshot.snapshot_id, tuple(item.evidence_id for item in inputs))
    ]


LATER_SNAPSHOT = UUID("99999999-9999-4999-8999-999999999999")


class _LaterGenerationDense(_GenerationDense):
    def __init__(self, inputs: dict[str, IndexInput]) -> None:
        super().__init__(inputs)
        self.profiles: list[object] = []

    async def is_published(self, snapshot_id: UUID) -> bool:
        return snapshot_id == LATER_SNAPSHOT

    async def search_query(self, profile, query, *, limit, filters=SearchFilters()):
        from research_platform.ingestion.indexing import IndexMatch
        from research_platform.search.dense_search import (
            DenseSearchResponse,
            HydratedDenseHit,
        )

        self.profiles.append(profile)
        items = list(self.inputs.values())[:limit]
        return DenseSearchResponse(
            snapshot_id=profile.snapshot.snapshot_id,
            profile_id=profile.profile_id,
            index_configuration_id=profile.dense_index.index_configuration_id,
            requested_limit=limit,
            hits=tuple(IndexMatch(i.evidence_id, 0.5, i.payload) for i in items),
            candidate_count=len(items),
            truncated=False,
            applied_filters=filters,
            hydrated_hits=tuple(
                HydratedDenseHit(rank=rank, score=0.5, evidence=item)
                for rank, item in enumerate(items, start=1)
            ),
        )


class _ExistingSnapshots:
    def acquire(self):
        class _Connection:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_exc):
                return None

            async def fetchval(self, _sql, snapshot_id):
                return snapshot_id in {SNAPSHOT_ID, LATER_SNAPSHOT, UNPUBLISHED}

        return _Connection()


UNPUBLISHED = UUID("88888888-8888-4888-8888-888888888888")


def _dense_profile_executor():
    from dataclasses import replace as dataclass_replace

    inputs = (_evidence_input(1), _evidence_input(2))
    dense = _LaterGenerationDense({item.evidence_id: item for item in inputs})
    executor, reranker, _hybrid, profile, _evidence = _executor(dense)
    dense_profile = dataclass_replace(
        profile,
        lexical_index=None,
        fusion=None,
        reranker=None,
        candidate_limits=dataclass_replace(
            profile.candidate_limits,
            lexical_top_k=None,
            fused_top_k=None,
            rerank_top_k=None,
        ),
    )
    executor._profiles[dense_profile.profile_id] = dense_profile
    executor._modes[dense_profile.profile_id] = RetrievalMode.DENSE
    executor._pool = _ExistingSnapshots()  # type: ignore[assignment]

    async def selection_for(snapshot_id):
        return dataclass_replace(profile.snapshot, snapshot_id=snapshot_id)

    executor._repository.snapshot_selection_for = selection_for  # type: ignore[attr-defined]
    return executor, reranker, dense, profile, dense_profile


def _later_request(profile, snapshot_id, mode):
    return SearchRequest(
        query="synthetic later generation",
        snapshot_id=snapshot_id,
        retrieval_profile_id=profile.profile_id,
        mode=mode,
        operation=SearchOperation.EVIDENCE_SEARCH,
        filters=SearchFilters(),
        limit=10,
    )


def test_published_generation_snapshot_is_served_in_dense_mode() -> None:
    executor, reranker, dense, _profile, dense_profile = _dense_profile_executor()
    try:
        response = asyncio.run(
            executor.execute(
                _later_request(dense_profile, LATER_SNAPSHOT, RetrievalMode.DENSE),
                request_id="later-dense",
            )
        )
    finally:
        reranker.close()

    assert response.snapshot_id == LATER_SNAPSHOT
    assert dense.profiles[0].snapshot.snapshot_id == LATER_SNAPSHOT
    assert dense.profiles[0].settings_id == dense_profile.settings_id
    assert response.hits and response.hits[0].chunk_id in dense.inputs


def test_lexical_mode_for_other_generation_is_unavailable_with_bm25s() -> None:
    executor, reranker, _dense, profile, _dense_profile = _dense_profile_executor()
    try:
        try:
            asyncio.run(
                executor.execute(
                    _later_request(profile, LATER_SNAPSHOT, RetrievalMode.RERANKED),
                    request_id="later-reranked",
                )
            )
        except Exception as error:
            assert "lexical index is not available" in str(error)
        else:
            raise AssertionError("BM25S cannot serve another generation")
    finally:
        reranker.close()


def test_unpublished_snapshot_is_incompatible() -> None:
    executor, reranker, _dense, _profile, dense_profile = _dense_profile_executor()
    try:
        try:
            asyncio.run(
                executor.execute(
                    _later_request(dense_profile, UNPUBLISHED, RetrievalMode.DENSE),
                    request_id="unpublished",
                )
            )
        except ValueError as error:
            assert "different snapshot" in str(error)
        else:
            raise AssertionError("an unpublished snapshot must not be served")
    finally:
        reranker.close()


def test_qdrant_engine_requires_qdrant_content_and_lexical_configuration() -> None:
    import json

    import pytest

    from research_platform.config import Settings
    from research_platform.ingestion.generation_index import (
        GenerationIndexConfiguration,
    )
    from research_platform.search.application import (
        SearchDependencyUnavailable,
        _require_lexical_engine,
    )

    def configuration(name: str) -> GenerationIndexConfiguration:
        raw = json.loads((ROOT / "configs" / name).read_text(encoding="utf-8"))
        return GenerationIndexConfiguration.from_dict(raw)

    dense_only = configuration("phase35-generation-index.example.json")
    lexical = configuration("phase35-generation-index-lexical.example.json")
    v10 = load_frozen_profile(ROOT / "benchmarks/phase2/frozen-profile-v10.toml")
    qdrant = load_frozen_profile(
        ROOT / "benchmarks/phase2/frozen-profile-v10-qdrant.toml"
    )
    engine = Settings(lexical_engine="qdrant", content_source="qdrant")
    failures = (
        (Settings(lexical_engine="qdrant", content_source="postgres"), qdrant, None),
        (engine, qdrant, dense_only),
        (engine, v10, lexical),
        (Settings(lexical_engine="bm25s", content_source="qdrant"), qdrant, lexical),
    )
    for settings, profile, generation_configuration in failures:
        with pytest.raises(SearchDependencyUnavailable):
            _require_lexical_engine(settings, profile, generation_configuration)

    _require_lexical_engine(engine, qdrant, lexical)
    _require_lexical_engine(
        Settings(lexical_engine="bm25s", content_source="postgres"), v10, None
    )
    defaults = Settings()
    assert (defaults.lexical_engine, defaults.content_source) == ("qdrant", "qdrant")
    with pytest.raises(ValueError, match="lexical_engine"):
        Settings(lexical_engine="elasticsearch")


class _HybridGenerationDense(_LaterGenerationDense):
    async def search_hybrid_component_query(
        self, profile, query, *, limit, filters=SearchFilters(), ready_index=None
    ):
        return await self.search_query(profile, query, limit=limit, filters=filters)


class _GenerationLexical:
    def __init__(self, profile, evidence_ids: tuple[str, ...]) -> None:
        from research_platform.search.lexical_branches import LexicalBranchIdentity

        self.profile = profile
        self.evidence_ids = evidence_ids
        self.identity = LexicalBranchIdentity(
            role="evidence",
            profile_id=profile.profile_id,
            snapshot=profile.snapshot,
            snapshot_status="finalized",
            candidate_limit=profile.candidate_limits.lexical_top_k,
        )

    async def search_with_stats(self, query, *, limit, filters=SearchFilters()):
        from research_platform.search.lexical import LexicalHit, LexicalSearchResult

        return LexicalSearchResult(
            hits=tuple(
                LexicalHit(evidence_id, "W123", row, 2.0 - row)
                for row, evidence_id in enumerate(reversed(self.evidence_ids))
            ),
            available_count=len(self.evidence_ids),
            eligible_count=len(self.evidence_ids),
            limit=limit,
            truncated=False,
            applied_filters=filters,
        )


class _QdrantLexicalFactory:
    def __init__(self, evidence_ids: tuple[str, ...]) -> None:
        self.evidence_ids = evidence_ids
        self.profiles: list[object] = []

    async def evidence(self, profile):
        self.profiles.append(profile)
        return _GenerationLexical(profile, self.evidence_ids)

    async def paper(self, profile):
        raise AssertionError("evidence search does not rank paper metadata")


def test_qdrant_engine_serves_hybrid_for_other_generation() -> None:
    inputs = (_evidence_input(1), _evidence_input(2))
    dense = _HybridGenerationDense({item.evidence_id: item for item in inputs})
    executor, reranker, hybrid, profile, _evidence = _executor(dense)
    executor._pool = _ExistingSnapshots()  # type: ignore[assignment]
    executor._repository = _NoLeaseRepository(inputs)  # type: ignore[assignment]

    async def selection_for(snapshot_id):
        from dataclasses import replace as dataclass_replace

        return dataclass_replace(profile.snapshot, snapshot_id=snapshot_id)

    executor._repository.snapshot_selection_for = selection_for  # type: ignore[attr-defined]
    lexical = _QdrantLexicalFactory(tuple(item.evidence_id for item in inputs))
    executor._qdrant_lexical = lexical  # type: ignore[assignment]
    try:
        response = asyncio.run(
            executor.execute(
                _later_request(profile, LATER_SNAPSHOT, RetrievalMode.RERANKED),
                request_id="later-reranked-qdrant",
            )
        )
    finally:
        reranker.close()

    serving_hybrid = executor._hybrid_profile
    (later_hybrid,) = lexical.profiles
    assert later_hybrid.snapshot.snapshot_id == LATER_SNAPSHOT
    assert later_hybrid.settings_id == serving_hybrid.settings_id
    assert dense.profiles == [later_hybrid]
    assert not hybrid.profiles
    assert response.snapshot_id == LATER_SNAPSHOT
    assert response.effective_mode is RetrievalMode.HYBRID
    assert response.effective_configuration_id == later_hybrid.profile_id
    assert response.hits
    assert {hit.chunk_id for hit in response.hits} <= {
        item.evidence_id for item in inputs
    }
    assert all(hit.component_scores.lexical is not None for hit in response.hits)
