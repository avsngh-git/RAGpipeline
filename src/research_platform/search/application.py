"""Phase 2 application services and private-local runtime composition."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from time import perf_counter
from typing import Any, Literal, cast
from uuid import UUID

import asyncpg  # type: ignore[import-untyped]
import httpx

from research_platform.config import Settings
from research_platform.ingestion.embeddings import (
    E5_SMALL_V2_MODEL,
    EmbeddingModelError,
    create_embedder_for_configuration,
    index_configuration_for_model,
)
from research_platform.ingestion.evidence import (
    EvidenceKind,
    EvidenceSourceSpan,
    EvidenceUnit,
    SourceLocation,
)
from research_platform.ingestion.evidence_repository import EvidenceRepository
from research_platform.ingestion.generation_index import (
    GenerationIndexConfiguration,
    GenerationQdrantCollection,
)
from research_platform.ingestion.generation_registry import GenerationRegistry
from research_platform.ingestion.identity import DocumentVersionKind
from research_platform.ingestion.indexing import (
    IndexConfiguration,
    IndexMatch,
    IndexRepository,
    QdrantIndex,
    SnapshotIndexNotReady,
)
from research_platform.search.active_profile import resolve_frozen_profile_path
from research_platform.search.application_errors import (
    IncompatibleRetrievalProfile,
    RetrievalExecutionFailure,
    SearchDependencyUnavailable,
)
from research_platform.search.contracts import (
    ComponentScores,
    EvidenceHit,
    PaperHit,
    PaperMetadataHit,
    RankedComponent,
    RetrievalMode,
    SearchFilters,
    SearchOperation,
    SearchRequest,
    SearchResponse,
)
from research_platform.search.dense_search import SnapshotDenseSearch
from research_platform.search.evidence_budgets import (
    apply_evidence_budgets_to_paper_support,
    select_evidence_results,
)
from research_platform.search.evidence_deduplication import (
    deduplicate_evidence_hits,
)
from research_platform.search.generation_search import (
    GenerationDenseSearch,
    PassageAuthorizer,
    QdrantContentReader,
)
from research_platform.search.hybrid_search import (
    HybridEvidenceSearch,
)
from research_platform.search.lexical import LexicalRetriever
from research_platform.search.lexical_artifacts import load_lexical_index
from research_platform.search.lexical_branches import (
    AsyncLexicalEvidenceBranch,
    AsyncLexicalPaperBranch,
    BM25SEvidenceBranch,
    BM25SPaperBranch,
)
from research_platform.search.paper_fusion import fuse_paper_candidates
from research_platform.search.paper_grouping import group_evidence_by_paper
from research_platform.search.paper_reads import (
    SnapshotNotFound,
)
from research_platform.search.paper_selection import select_paper_results
from research_platform.search.profile_manifest import (
    load_frozen_profile,
    load_retrieval_profile_manifest,
)
from research_platform.search.profiles import (
    CandidateLimits,
    RetrievalProfile,
)
from research_platform.search.reranker import CrossEncoderReranker
from research_platform.search.reranker_models import PinnedSentenceTransformersReranker
from research_platform.search.reranker_service import rerank_with_fallback
from research_platform.search.table_context import (
    TableContextResolutionError,
    attach_table_context,
)

logger = logging.getLogger("research_platform.search")


@dataclass(frozen=True)
class SnapshotEligibility:
    """Exact permitted paper and evidence counts for one snapshot/filter scope."""

    paper_metadata: Mapping[str, tuple[str | None, int | None]]
    evidence_counts_by_paper: Mapping[str, int]

    @property
    def eligible_paper_count(self) -> int:
        return len(self.paper_metadata)

    @property
    def eligible_evidence_count(self) -> int:
        return sum(self.evidence_counts_by_paper.values())


class SnapshotEligibilityReader:
    """Count selected, indexing-permitted rows before candidate limits."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def read(
        self, snapshot_id: UUID, *, filters: SearchFilters
    ) -> SnapshotEligibility:
        async with self._pool.acquire() as connection:
            rows = await connection.fetch(
                _ELIGIBILITY_SQL,
                snapshot_id,
                filters.year_from,
                filters.year_to,
                list(filters.paper_ids) if filters.paper_ids is not None else None,
                list(filters.evidence_kinds)
                if filters.evidence_kinds is not None
                else None,
                list(filters.document_version_kinds)
                if filters.document_version_kinds is not None
                else None,
            )
        metadata: dict[str, tuple[str | None, int | None]] = {}
        evidence_counts: dict[str, int] = {}
        for row in rows:
            paper_id = row["paper_id"]
            title = row["title"]
            year = row["publication_year"]
            count = row["evidence_count"]
            if not isinstance(paper_id, str):
                raise RuntimeError("eligible paper identity is malformed")
            if title is not None and not isinstance(title, str):
                raise RuntimeError("eligible paper title is malformed")
            if year is not None and (
                isinstance(year, bool) or not isinstance(year, int)
            ):
                raise RuntimeError("eligible paper year is malformed")
            if isinstance(count, bool) or not isinstance(count, int) or count < 0:
                raise RuntimeError("eligible evidence count is malformed")
            metadata[paper_id] = (title, year)
            evidence_counts[paper_id] = count
        return SnapshotEligibility(metadata, evidence_counts)


class Phase2SearchExecutor:
    """Compose frozen retrieval stages into bounded paper/evidence responses."""

    def __init__(
        self,
        *,
        pool: asyncpg.Pool,
        index_configuration: IndexConfiguration,
        repository: IndexRepository,
        eligibility_reader: SnapshotEligibilityReader,
        profiles_by_id: Mapping[str, RetrievalProfile],
        modes_by_profile_id: Mapping[str, RetrievalMode],
        lexical_evidence: Mapping[str, AsyncLexicalEvidenceBranch],
        lexical_papers: Mapping[str, AsyncLexicalPaperBranch],
        hybrid_profile: RetrievalProfile,
        hybrid_search: HybridEvidenceSearch,
        dense_search: SnapshotDenseSearch | GenerationDenseSearch,
        reranker: CrossEncoderReranker,
        evidence_repository: EvidenceRepository,
    ) -> None:
        self._pool = pool
        self._configuration = index_configuration
        self._repository = repository
        self._eligibility = eligibility_reader
        self._profiles = dict(profiles_by_id)
        self._modes = dict(modes_by_profile_id)
        self._lexical_evidence = dict(lexical_evidence)
        self._lexical_papers = dict(lexical_papers)
        self._hybrid_profile = hybrid_profile
        self._hybrid = hybrid_search
        self._dense = dense_search
        self._reranker = reranker
        self._evidence_repository = evidence_repository
        self._generation_search = (
            dense_search if isinstance(dense_search, GenerationDenseSearch) else None
        )

    async def execute(
        self, request: SearchRequest, *, request_id: str
    ) -> SearchResponse[Any]:
        started = perf_counter()
        profile = self._profiles.get(request.retrieval_profile_id)
        if profile is None:
            raise IncompatibleRetrievalProfile("retrieval profile is not registered")
        expected_mode = self._modes[profile.profile_id]
        if request.mode is not expected_mode:
            raise IncompatibleRetrievalProfile(
                "mode does not match the retrieval profile"
            )
        if request.snapshot_id != profile.snapshot.snapshot_id:
            profile = await self._profile_for_generation(profile, request)

        eligible = await self._eligibility.read(
            request.snapshot_id, filters=request.filters
        )
        stage_started = perf_counter()
        (
            candidates,
            source_units,
            upstream_truncated,
            stage_counts,
            effective_profile_id,
        ) = await self._evidence_candidates(profile, request)
        retrieval_ms = round((perf_counter() - stage_started) * 1000, 2)
        deduplicated = deduplicate_evidence_hits(
            candidates, source_units_by_id=source_units
        )
        table_ready_hits = await self._attach_table_context(
            deduplicated.hits, source_units
        )

        effective_mode = request.mode
        warnings: list[str] = []
        if request.mode is RetrievalMode.RERANKED:
            if effective_profile_id == self._hybrid_profile.profile_id:
                effective_mode = RetrievalMode.HYBRID
                warnings.append("reranking failed; unchanged hybrid order was returned")
        if deduplicated.omissions:
            warnings.append("duplicate or fully covered source units were omitted")
        if deduplicated.unresolved_source_evidence_ids:
            warnings.append("source coverage could not be resolved for some candidates")
        if upstream_truncated:
            warnings.append("candidate pools were truncated before result selection")

        if request.operation is SearchOperation.EVIDENCE_SEARCH:
            budget = select_evidence_results(
                table_ready_hits,
                result_limit=request.limit,
                selection_rules=profile.selection_rules,
                candidate_pools_truncated=upstream_truncated,
            )
            warnings.extend(budget.warnings)
            omitted_count = len(deduplicated.omissions) + budget.omitted_count
            truncated = (
                upstream_truncated or bool(deduplicated.omissions) or budget.truncated
            )
            hits: tuple[Any, ...] = budget.hits
            eligible_count = eligible.eligible_evidence_count
        elif request.operation is SearchOperation.PAPER_SEARCH:
            paper_candidates, paper_pool_truncated = await self._paper_candidates(
                profile,
                request,
                eligible,
                table_ready_hits,
                upstream_truncated,
            )
            page = select_paper_results(
                paper_candidates,
                limit=request.limit,
                profile=profile,
                candidate_pools_truncated=paper_pool_truncated,
            )
            support = apply_evidence_budgets_to_paper_support(
                page.hits,
                selection_rules=profile.selection_rules,
                candidate_pools_truncated=paper_pool_truncated,
            )
            warnings.extend(page.warnings)
            warnings.extend(support.selection.warnings)
            if deduplicated.omissions:
                warnings.append("duplicate or fully covered source units were omitted")
            hits = support.papers
            omitted_count = (
                page.omitted_count
                + support.selection.omitted_count
                + len(deduplicated.omissions)
            )
            truncated = (
                page.truncated
                or support.selection.truncated
                or bool(deduplicated.omissions)
            )
            eligible_count = eligible.eligible_paper_count
        else:
            raise IncompatibleRetrievalProfile("unsupported search operation")

        response = SearchResponse(
            request_id=request_id,
            snapshot_id=request.snapshot_id,
            retrieval_profile_id=profile.profile_id,
            effective_configuration_id=effective_profile_id,
            requested_mode=request.mode,
            effective_mode=effective_mode,
            hits=hits,
            eligible_count=eligible_count,
            warnings=tuple(dict.fromkeys(warnings)),
            truncated=truncated,
            omitted_count=omitted_count,
        )
        logger.info(
            "search_completed",
            extra={
                "request_id": request_id,
                "snapshot_id": str(request.snapshot_id),
                "retrieval_profile_id": profile.profile_id,
                "effective_configuration_id": effective_profile_id,
                "requested_mode": request.mode.value,
                "effective_mode": effective_mode.value,
                "operation": request.operation.value,
                "eligible_count": eligible_count,
                "candidate_counts": stage_counts,
                "returned_count": len(hits),
                "dedup_omission_count": len(deduplicated.omissions),
                "truncated": truncated,
                "omitted_count": omitted_count,
                "retrieval_duration_ms": retrieval_ms,
                "total_duration_ms": round((perf_counter() - started) * 1000, 2),
                "fallback": effective_mode is not request.mode,
                "failure_category": stage_counts.get("reranker_failure_category")
                if effective_mode is not request.mode
                else None,
            },
        )
        return response

    async def _profile_for_generation(
        self, profile: RetrievalProfile, request: SearchRequest
    ) -> RetrievalProfile:
        """Bind the profile to another published generation's snapshot, if allowed."""
        async with self._pool.acquire() as connection:
            exists = await connection.fetchval(
                "SELECT EXISTS (SELECT 1 FROM snapshots WHERE id = $1)",
                request.snapshot_id,
            )
        if not exists:
            raise SnapshotNotFound("snapshot does not exist")
        if self._generation_search is None or not (
            await self._generation_search.is_published(request.snapshot_id)
        ):
            raise IncompatibleRetrievalProfile(
                "retrieval profile is bound to a different snapshot"
            )
        if request.mode is not RetrievalMode.DENSE:
            raise SearchDependencyUnavailable(
                "lexical index is not available for this generation"
            )
        return profile.with_snapshot(
            await self._repository.snapshot_selection_for(request.snapshot_id)
        )

    async def _evidence_candidates(
        self, profile: RetrievalProfile, request: SearchRequest
    ) -> tuple[
        tuple[EvidenceHit, ...],
        dict[str, EvidenceUnit],
        bool,
        dict[str, int | float | str],
        str,
    ]:
        mode = request.mode
        if mode is RetrievalMode.LEXICAL:
            retriever = self._lexical_evidence.get(profile.profile_id)
            if retriever is None or profile.candidate_limits.lexical_top_k is None:
                raise SearchDependencyUnavailable(
                    "lexical evidence profile is unavailable"
                )
            lexical_started = perf_counter()
            result = await retriever.search_with_stats(
                request.query,
                limit=profile.candidate_limits.lexical_top_k,
                filters=request.filters,
            )
            ranked = tuple(
                (
                    hit.stable_id,
                    hit.score,
                    ComponentScores(
                        lexical=RankedComponent(rank=rank, score=hit.score)
                    ),
                )
                for rank, hit in enumerate(result.hits, start=1)
            )
            hydrated, source_units = await self._hydrate(profile, ranked)
            return (
                hydrated,
                source_units,
                result.truncated,
                {
                    "lexical": result.available_count,
                    "returned": len(result.hits),
                    "lexical_duration_ms": round(
                        (perf_counter() - lexical_started) * 1000, 2
                    ),
                },
                profile.profile_id,
            )

        if mode is RetrievalMode.DENSE:
            dense_started = perf_counter()
            try:
                dense = await self._dense.search_query(
                    profile,
                    request.query,
                    limit=cast(int, profile.candidate_limits.dense_top_k),
                    filters=request.filters,
                )
            except EmbeddingModelError as error:
                logger.error(
                    "retrieval_component_failed",
                    extra={
                        "snapshot_id": str(request.snapshot_id),
                        "retrieval_profile_id": profile.profile_id,
                        "failure_stage": "query_embedding",
                        "failure_type": type(error).__name__,
                    },
                )
                raise RetrievalExecutionFailure(
                    "the required dense stage failed"
                ) from None
            ranked = tuple(
                (
                    item.evidence.evidence_id,
                    item.score,
                    ComponentScores(
                        dense=RankedComponent(rank=item.rank, score=item.score)
                    ),
                )
                for item in dense.hydrated_hits
            )
            pairs = tuple(
                _hit_and_source_unit(item.evidence, rank=item.rank, scores=scores)
                for item, (_identity, _score, scores) in zip(
                    dense.hydrated_hits, ranked, strict=True
                )
            )
            hits = tuple(pair[0] for pair in pairs)
            source_units = {pair[1].id: pair[1] for pair in pairs}
            return (
                hits,
                source_units,
                dense.truncated,
                {
                    "dense": dense.candidate_count,
                    "returned": len(hits),
                    "dense_duration_ms": round(
                        (perf_counter() - dense_started) * 1000, 2
                    ),
                },
                profile.profile_id,
            )

        if mode not in {RetrievalMode.HYBRID, RetrievalMode.RERANKED}:
            raise IncompatibleRetrievalProfile("unsupported retrieval mode")
        lease = (
            contextlib.nullcontext(None)
            if self._generation_search is not None
            else self._repository.serving_index(
                self._hybrid_profile.snapshot, self._configuration
            )
        )
        async with lease as ready_index:
            try:
                hybrid = await self._hybrid.search_query(
                    self._hybrid_profile,
                    request.query,
                    filters=request.filters,
                    ready_index=ready_index,
                )
            except Exception as error:
                from research_platform.search.hybrid_search import HybridSearchFailure

                if isinstance(error, HybridSearchFailure):
                    logger.error(
                        "retrieval_component_failed",
                        extra={
                            "snapshot_id": str(request.snapshot_id),
                            "retrieval_profile_id": self._hybrid_profile.profile_id,
                            "failure_stage": error.details.stage,
                            "failure_type": error.details.error_type,
                        },
                    )
                    raise RetrievalExecutionFailure(
                        "a required hybrid stage failed"
                    ) from None
                raise
            ranked_fused = tuple(
                (hit.evidence_id, hit.score, hit.component_scores)
                for hit in hybrid.hits
            )
            candidates, source_units = await self._hydrate(
                self._hybrid_profile, ranked_fused
            )
        counts: dict[str, int | float | str] = {
            "lexical": hybrid.lexical_pool.available_count,
            "dense": hybrid.dense_pool.available_count,
            "fused": hybrid.fused_pool.available_count,
            "returned": len(candidates),
            "lexical_duration_ms": round(hybrid.lexical_duration_ms, 2),
            "dense_duration_ms": round(hybrid.dense_duration_ms, 2),
            "fusion_duration_ms": round(hybrid.fusion_duration_ms, 2),
        }
        if mode is RetrievalMode.HYBRID:
            return (
                candidates,
                source_units,
                hybrid.truncated,
                counts,
                profile.profile_id,
            )
        reranker_started = perf_counter()
        outcome = await rerank_with_fallback(
            profile, request.query, candidates, self._reranker
        )
        counts["reranker_duration_ms"] = round(
            (perf_counter() - reranker_started) * 1000, 2
        )
        if outcome.effective_mode == "hybrid":
            return (
                outcome.hits,
                source_units,
                hybrid.truncated,
                {
                    **counts,
                    "reranker_fallback_count": 1,
                    "reranker_failure_type": (
                        outcome.failure.error_type
                        if outcome.failure is not None
                        else "unknown"
                    ),
                    "reranker_failure_category": (
                        outcome.failure.failure_category
                        if outcome.failure is not None
                        else "adapter_failure"
                    ),
                },
                self._hybrid_profile.profile_id,
            )
        return (
            outcome.hits,
            source_units,
            hybrid.truncated,
            counts,
            profile.profile_id,
        )

    async def _hydrate(
        self,
        profile: RetrievalProfile,
        ranked: Sequence[tuple[str, float, ComponentScores]],
    ) -> tuple[tuple[EvidenceHit, ...], dict[str, EvidenceUnit]]:
        matches = tuple(
            IndexMatch(evidence_id=identity, score=score, payload={})
            for identity, score, _scores in ranked
        )
        if self._generation_search is not None:
            hydrated = await self._generation_search.read_evidence(
                profile.snapshot.snapshot_id,
                [identity for identity, _score, _scores in ranked],
            )
        else:
            hydrated = await self._repository.hydrate_snapshot_matches(
                profile.snapshot, self._configuration, matches
            )
        if tuple(item.evidence_id for item in hydrated) != tuple(
            identity for identity, _score, _scores in ranked
        ):
            raise RuntimeError("authoritative source rows do not align with candidates")
        pairs = tuple(
            _hit_and_source_unit(item, rank=rank, scores=scores)
            for rank, (item, (_identity, _score, scores)) in enumerate(
                zip(hydrated, ranked, strict=True), start=1
            )
        )
        return (
            tuple(pair[0] for pair in pairs),
            {pair[1].id: pair[1] for pair in pairs},
        )

    async def _attach_table_context(
        self,
        hits: Sequence[EvidenceHit],
        source_units: Mapping[str, EvidenceUnit],
    ) -> tuple[EvidenceHit, ...]:
        table_hits = tuple(
            hit for hit in hits if hit.kind in {"table", "table_row_group"}
        )
        if not table_hits:
            return tuple(hits)
        requested_tables: set[tuple[UUID, int]] = set()
        for hit in table_hits:
            for evidence_id in hit.source_evidence_ids:
                unit = source_units.get(evidence_id)
                ordinal = (
                    unit.metadata.get("table_ordinal") if unit is not None else None
                )
                if (
                    isinstance(ordinal, int)
                    and not isinstance(ordinal, bool)
                    and ordinal >= 0
                ):
                    requested_tables.add((hit.extraction_id, ordinal))
        try:
            tables = await self._evidence_repository.load_tables_for_search(
                tuple(requested_tables)
            )
            return tuple(
                attach_table_context(
                    hit,
                    source_units_by_id=source_units,
                    tables_by_extraction_and_ordinal=tables,
                )
                if hit.kind in {"table", "table_row_group"}
                else hit
                for hit in hits
            )
        except (TableContextResolutionError, TypeError, ValueError):
            raise RetrievalExecutionFailure(
                "table source context could not be resolved"
            ) from None

    async def _paper_candidates(
        self,
        profile: RetrievalProfile,
        request: SearchRequest,
        eligible: SnapshotEligibility,
        evidence_hits: Sequence[EvidenceHit],
        evidence_truncated: bool,
    ) -> tuple[tuple[PaperHit, ...], bool]:
        evidence_papers = tuple(
            replace(
                paper,
                title=eligible.paper_metadata.get(paper.paper_id, (None, None))[0],
                publication_year=eligible.paper_metadata.get(
                    paper.paper_id, (None, None)
                )[1],
            )
            for paper in group_evidence_by_paper(
                evidence_hits, selection_rules=profile.selection_rules
            )
        )
        paper_retriever = self._lexical_papers.get(profile.profile_id)
        metadata_hits: tuple[PaperMetadataHit, ...] = ()
        metadata_truncated = False
        if paper_retriever is not None:
            lexical_limit = profile.candidate_limits.lexical_top_k
            if lexical_limit is None:
                raise IncompatibleRetrievalProfile("paper profile has no lexical limit")
            result = await paper_retriever.search_with_stats(
                request.query,
                eligible_ids=set(eligible.paper_metadata),
                limit=lexical_limit,
            )
            metadata_hits = tuple(
                PaperMetadataHit(
                    paper_id=hit.paper_id,
                    title=eligible.paper_metadata[hit.paper_id][0],
                    publication_year=eligible.paper_metadata[hit.paper_id][1],
                    rank=rank,
                    component_scores=ComponentScores(
                        lexical=RankedComponent(rank=rank, score=hit.score)
                    ),
                )
                for rank, hit in enumerate(result.hits, start=1)
            )
            metadata_truncated = result.truncated

        if profile.fusion is not None and metadata_hits:
            candidates = fuse_paper_candidates(
                metadata_hits, evidence_papers, settings=profile.fusion
            )
        elif profile.profile_id in self._lexical_papers:
            by_paper = {paper.paper_id: paper for paper in evidence_papers}
            candidates = tuple(
                PaperHit(
                    paper_id=hit.paper_id,
                    title=hit.title,
                    publication_year=hit.publication_year,
                    rank=rank,
                    component_scores=hit.component_scores,
                    supporting_evidence=(
                        by_paper[hit.paper_id].supporting_evidence
                        if hit.paper_id in by_paper
                        else ()
                    ),
                    metadata_rank=rank,
                    evidence_rank=(
                        by_paper[hit.paper_id].evidence_rank
                        if hit.paper_id in by_paper
                        else None
                    ),
                )
                for rank, hit in enumerate(metadata_hits, start=1)
            )
        else:
            candidates = evidence_papers
        return candidates, metadata_truncated or evidence_truncated


@dataclass
class Phase2Runtime:
    """Owned local dependencies for the Phase 2 FastAPI lifespan."""

    pool: asyncpg.Pool
    http: httpx.AsyncClient
    api_services: Any
    reranker: CrossEncoderReranker
    embedder: Any

    async def close(self) -> None:
        self.embedder.close()
        self.reranker.close()
        await self.http.aclose()
        await self.pool.close()


async def _warm_phase2_embedder(
    embedder: Any, configuration: IndexConfiguration
) -> None:
    """Load local model weights before warming the deadline-bound query path."""
    probe = "local readiness probe"
    await embedder.embed((probe,), configuration=configuration)
    await embedder.embed_query(probe, configuration=configuration)


@dataclass(frozen=True)
class _ServingProfiles:
    """Profiles, dense configuration and lexical source derived from one freeze."""

    frozen: RetrievalProfile
    bm25: RetrievalProfile
    hybrid: RetrievalProfile
    dense: RetrievalProfile
    lexical_source: RetrievalProfile
    configuration: IndexConfiguration


def _resolve_serving_profiles(frozen_profile_path: Path | None) -> _ServingProfiles:
    """Build serving profiles and the dense stack from the frozen profile manifest."""
    frozen_profile_path = resolve_frozen_profile_path(frozen_profile_path)
    manifest_dir = frozen_profile_path.parent
    frozen = load_frozen_profile(frozen_profile_path)
    legacy_hybrid = load_retrieval_profile_manifest(
        manifest_dir / "hybrid-e5-profile-v1.toml"
    )
    bm25_profile = load_retrieval_profile_manifest(
        manifest_dir / "bm25-profile-v1.toml"
    )
    dense_identity = frozen.dense_index
    if dense_identity is None or frozen.lexical_index is None:
        raise SearchDependencyUnavailable("frozen serving profile is not hybrid")
    is_e5 = dense_identity.model == E5_SMALL_V2_MODEL
    if is_e5:
        hybrid_profile = legacy_hybrid
        configuration = _load_phase2_dense_configuration(manifest_dir)
        expected_names = ("bm25_lexical", "dense_e5", "hybrid_e5")
        frozen_name = "reranked_minilm_hybrid"
    else:
        if (
            frozen.lexical_index != legacy_hybrid.lexical_index
            or frozen.candidate_limits.lexical_top_k
            != legacy_hybrid.candidate_limits.lexical_top_k
        ):
            raise SearchDependencyUnavailable(
                "frozen lexical index differs from the reusable BM25 artifacts"
            )
        hybrid_profile = replace(
            frozen,
            reranker=None,
            candidate_limits=replace(frozen.candidate_limits, rerank_top_k=None),
        )
        try:
            configuration = index_configuration_for_model(
                model=dense_identity.model,
                revision=dense_identity.revision,
                preprocessing_revision=dense_identity.preprocessing_revision,
                dimensions=dense_identity.dimensions,
                maximum_input_tokens=dense_identity.maximum_input_tokens,
            )
        except ValueError:
            raise SearchDependencyUnavailable(
                "frozen dense model has no pinned local adapter"
            ) from None
        expected_names = ("bm25_lexical", "dense_gte", "hybrid_gte")
        frozen_name = "reranked_gte_ettin_hybrid"
    dense_profile = replace(
        hybrid_profile,
        lexical_index=None,
        fusion=None,
        candidate_limits=CandidateLimits(
            lexical_top_k=None,
            dense_top_k=50,
            fused_top_k=None,
            rerank_top_k=None,
        ),
    )
    expected_ids = dict(
        zip(
            expected_names,
            (
                bm25_profile.profile_id,
                dense_profile.profile_id,
                hybrid_profile.profile_id,
            ),
            strict=True,
        )
    )
    expected_ids[frozen_name] = frozen.profile_id
    comparison_ids = _comparison_profiles(frozen_profile_path)
    if any(comparison_ids.get(name) != value for name, value in expected_ids.items()):
        raise SearchDependencyUnavailable(
            "frozen retrieval profile identities disagree"
        )
    if (
        frozen.snapshot != hybrid_profile.snapshot
        or frozen.snapshot != bm25_profile.snapshot
        or frozen.snapshot != legacy_hybrid.snapshot
    ):
        raise SearchDependencyUnavailable("serving profiles target different snapshots")
    if configuration.configuration_id != dense_identity.index_configuration_id:
        raise SearchDependencyUnavailable(
            "local vector configuration differs from freeze"
        )
    return _ServingProfiles(
        frozen,
        bm25_profile,
        hybrid_profile,
        dense_profile,
        legacy_hybrid,
        configuration,
    )


def _bind_lexical_to_profile(index: Any, profile: RetrievalProfile) -> Any:
    """Rebind a dense-independent BM25 artifact to the serving profile identity."""
    return replace(
        index,
        profile=profile,
        manifest=replace(index.manifest, profile_id=profile.profile_id),
    )


def _build_lexical_retrievers(
    serving: _ServingProfiles,
    load: Callable[[RetrievalProfile, Literal["evidence", "paper"]], Any],
) -> tuple[dict[str, LexicalRetriever], dict[str, LexicalRetriever]]:
    """Map serving profile ids to retrievers, reusing the legacy BM25 artifacts."""
    hybrid, frozen, bm25 = serving.hybrid, serving.frozen, serving.bm25
    evidence = load(serving.lexical_source, "evidence")
    paper = load(serving.lexical_source, "paper")
    if hybrid is not serving.lexical_source:
        # Hybrid checks the retriever profile and manifest id against the request.
        evidence = _bind_lexical_to_profile(evidence, hybrid)
        paper = _bind_lexical_to_profile(paper, hybrid)
    return (
        {
            bm25.profile_id: LexicalRetriever(load(bm25, "evidence")),
            hybrid.profile_id: LexicalRetriever(evidence),
        },
        {
            bm25.profile_id: LexicalRetriever(load(bm25, "paper")),
            hybrid.profile_id: LexicalRetriever(paper),
            frozen.profile_id: LexicalRetriever(paper),
        },
    )


async def create_phase2_runtime(
    settings: Settings, *, frozen_profile_path: Path | None = None
) -> Phase2Runtime:
    """Load frozen local indexes/models without migrating or downloading data."""
    serving = _resolve_serving_profiles(frozen_profile_path)
    frozen = serving.frozen
    hybrid_profile = serving.hybrid
    bm25_profile = serving.bm25
    dense_profile = serving.dense
    configuration = serving.configuration

    pool = await asyncpg.create_pool(settings.database_url, min_size=1, max_size=10)
    if pool is None:
        raise SearchDependencyUnavailable("PostgreSQL pool could not be created")
    http = httpx.AsyncClient(
        base_url=settings.qdrant_url.rstrip("/"), timeout=httpx.Timeout(10.0)
    )
    embedder: Any | None = None
    reranker: CrossEncoderReranker | None = None
    try:
        repository = IndexRepository(pool)
        async with pool.acquire() as connection:
            snapshot_status = await connection.fetchval(
                "SELECT status FROM snapshots WHERE id = $1",
                frozen.snapshot.snapshot_id,
            )
        if snapshot_status != "finalized":
            raise SearchDependencyUnavailable(
                "frozen serving snapshot is not finalized"
            )
        if (
            await repository.snapshot_selection_for(frozen.snapshot.snapshot_id)
            != frozen.snapshot
        ):
            raise SearchDependencyUnavailable("frozen snapshot selection has changed")

        root = settings.lexical_index_root
        evidence_retrievers, paper_retrievers = _build_lexical_retrievers(
            serving,
            lambda profile, role: _load_lexical_artifact(
                root, profile, role, mmap=True
            ),
        )
        lexical_evidence: dict[str, AsyncLexicalEvidenceBranch] = {
            profile_id: BM25SEvidenceBranch(retriever)
            for profile_id, retriever in evidence_retrievers.items()
        }
        lexical_papers: dict[str, AsyncLexicalPaperBranch] = {
            profile_id: BM25SPaperBranch(retriever)
            for profile_id, retriever in paper_retrievers.items()
        }
        embedder = create_embedder_for_configuration(
            configuration, device=cast(Any, settings.model_device)
        )
        dense: SnapshotDenseSearch | GenerationDenseSearch
        if settings.content_source == "qdrant":
            dense = await _generation_dense_search(
                settings, pool, http, embedder, frozen.snapshot.snapshot_id
            )
        else:
            dense = SnapshotDenseSearch(
                repository,
                QdrantIndex(configuration, http),
                query_embedder=embedder,
                evidence_hydrator=repository,
            )
        hybrid = HybridEvidenceSearch(
            lexical_evidence[hybrid_profile.profile_id], dense
        )
        reranker_identity = frozen.reranker
        if reranker_identity is None:
            raise SearchDependencyUnavailable("frozen serving profile has no reranker")
        local_reranker = PinnedSentenceTransformersReranker(
            cast(Any, reranker_identity),
            device=cast(Any, settings.model_device),
            cache_folder=settings.reranker_cache_dir,
        )
        reranker = CrossEncoderReranker(
            cast(Any, reranker_identity),
            token_counter=local_reranker,
            scorer=local_reranker,
            batch_size=4 if reranker_identity.precision == "fp32" else 8,
            maximum_candidates=50,
            timeout_seconds=15,
        )
        # Warm the exact pinned local models during startup; their adapters prohibit downloads.
        await _warm_phase2_embedder(embedder, configuration)
        await asyncio.to_thread(local_reranker.count_pair, "local readiness", "probe")
        await asyncio.to_thread(
            local_reranker.score_pairs, (("local readiness", "probe"),)
        )
        executor = Phase2SearchExecutor(
            pool=pool,
            index_configuration=configuration,
            repository=repository,
            eligibility_reader=SnapshotEligibilityReader(pool),
            profiles_by_id={
                bm25_profile.profile_id: bm25_profile,
                dense_profile.profile_id: dense_profile,
                hybrid_profile.profile_id: hybrid_profile,
                frozen.profile_id: frozen,
            },
            modes_by_profile_id={
                bm25_profile.profile_id: RetrievalMode.LEXICAL,
                dense_profile.profile_id: RetrievalMode.DENSE,
                hybrid_profile.profile_id: RetrievalMode.HYBRID,
                frozen.profile_id: RetrievalMode.RERANKED,
            },
            lexical_evidence=lexical_evidence,
            lexical_papers=lexical_papers,
            hybrid_profile=hybrid_profile,
            hybrid_search=hybrid,
            dense_search=dense,
            reranker=reranker,
            evidence_repository=EvidenceRepository(pool),
        )
        from research_platform.api.routes import Phase2APIServices
        from research_platform.search.paper_graph import CitationGraphReader
        from research_platform.search.paper_reads import SnapshotPaperReader

        services = Phase2APIServices(
            search=executor,
            papers=SnapshotPaperReader(pool),
            citations=CitationGraphReader(pool),
        )
        return Phase2Runtime(pool, http, services, reranker, embedder)
    except BaseException:
        if reranker is not None:
            reranker.close()
        if embedder is not None:
            embedder.close()
        await http.aclose()
        await pool.close()
        raise


async def _generation_dense_search(
    settings: Settings,
    pool: asyncpg.Pool,
    http: httpx.AsyncClient,
    embedder: Any,
    snapshot_id: UUID,
) -> GenerationDenseSearch:
    """Dense search and content over the configured collection's generations."""
    try:
        raw = json.loads(settings.generation_configuration.read_text(encoding="utf-8"))
        configuration = GenerationIndexConfiguration.from_dict(raw)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        raise SearchDependencyUnavailable(
            "generation index configuration is unavailable or invalid"
        ) from None
    registry = GenerationRegistry(pool)
    passages = GenerationQdrantCollection(configuration, "passages", http)
    search = GenerationDenseSearch(
        passages=passages,
        reader=QdrantContentReader(passages, PassageAuthorizer(pool), configuration),
        registry=registry,
        configuration=configuration,
        query_embedder=embedder,
    )
    try:
        await search.generation_for(snapshot_id)
    except SnapshotIndexNotReady:
        raise SearchDependencyUnavailable(
            "the serving snapshot has no published generation"
        ) from None
    return search


def _load_lexical_artifact(
    root: Path,
    profile: RetrievalProfile,
    role: Literal["evidence", "paper"],
    *,
    mmap: bool,
) -> Any:
    artifact_root = Path(root) / profile.profile_id.removeprefix("sha256:") / role
    if artifact_root.is_symlink() or not artifact_root.is_dir():
        raise SearchDependencyUnavailable(f"{role} lexical artifact is not built")
    valid: list[Any] = []
    for path in sorted(artifact_root.iterdir()):
        if path.name.startswith(".") or not path.is_dir():
            continue
        try:
            valid.append(
                load_lexical_index(
                    path,
                    expected_profile=profile,
                    expected_role=role,
                    mmap=mmap,
                )
            )
        except (OSError, ValueError, PermissionError):
            continue
    if len(valid) != 1:
        raise SearchDependencyUnavailable(
            f"{role} lexical artifact is missing, invalid or ambiguous"
        )
    return valid[0]


def _load_phase2_dense_configuration(manifest_dir: Path) -> IndexConfiguration:
    """Load the isolated, filter-ready dense index bound by Phase 2 profiles."""
    configuration_path = manifest_dir / "e5-small-v2-filtered-index-v1.json"
    try:
        raw = json.loads(configuration_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("dense index configuration must be an object")
        return IndexConfiguration.from_dict(raw)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        raise SearchDependencyUnavailable(
            "frozen dense index configuration is unavailable or invalid"
        ) from None


def _comparison_profiles(path: Path) -> dict[str, str]:
    import tomllib

    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    table = raw.get("comparison_profiles")
    if not isinstance(table, dict) or any(
        not isinstance(key, str) or not isinstance(value, str)
        for key, value in table.items()
    ):
        raise SearchDependencyUnavailable("comparison profile map is malformed")
    return cast(dict[str, str], table)


def _hit_and_source_unit(
    evidence: Any, *, rank: int, scores: ComponentScores
) -> tuple[EvidenceHit, EvidenceUnit]:
    payload = evidence.payload
    source_location = _source_location(payload.get("source_location"))
    raw_spans = payload.get("source_spans", [])
    raw_metadata = payload.get("evidence_metadata", {})
    if not isinstance(raw_spans, list) or not isinstance(raw_metadata, Mapping):
        raise RuntimeError("hydrated evidence source metadata is malformed")
    try:
        spans = tuple(EvidenceSourceSpan.from_dict(item) for item in raw_spans)
    except (TypeError, ValueError):
        raise RuntimeError("hydrated evidence spans are malformed") from None
    document_id = UUID(cast(str, payload["document_id"]))
    extraction_id = UUID(cast(str, payload["extraction_id"]))
    kind = cast(EvidenceKind, payload["evidence_kind"])
    metadata = dict(raw_metadata)
    metadata.setdefault(
        "chunking_configuration_id", payload.get("chunking_configuration_id")
    )
    section_ordinal = payload.get("section_ordinal")
    start_offset = payload.get("start_offset")
    end_offset = payload.get("end_offset")
    source_unit = EvidenceUnit(
        id=evidence.evidence_id,
        document_id=document_id,
        extraction_id=extraction_id,
        section_ordinal=cast(int | None, section_ordinal),
        ordinal=0,
        kind=kind,
        content=evidence.text,
        start_offset=cast(int | None, start_offset),
        end_offset=cast(int | None, end_offset),
        source_location=source_location,
        metadata=metadata,
    )
    hit = EvidenceHit(
        chunk_id=evidence.evidence_id,
        source_evidence_ids=(evidence.evidence_id,),
        paper_id=cast(str, payload["paper_id"]),
        document_id=document_id,
        document_version=cast(str, payload["document_version"]),
        document_version_kind=cast(
            DocumentVersionKind, payload["document_version_kind"]
        ),
        extraction_id=extraction_id,
        chunking_configuration_id=cast(
            str | None, payload.get("chunking_configuration_id")
        ),
        kind=kind,
        source_location=source_location,
        rank=rank,
        component_scores=scores,
        text=evidence.text,
        source_spans=spans,
    )
    return hit, source_unit


def _source_location(value: object) -> SourceLocation:
    if not isinstance(value, Mapping):
        raise RuntimeError("hydrated source location is malformed")
    box = value.get("bounding_box")
    if box is not None and isinstance(box, list):
        box = tuple(box)
    try:
        return SourceLocation(
            page_index_zero_based=cast(int | None, value.get("page_index_zero_based")),
            printed_page_label=cast(str | None, value.get("printed_page_label")),
            bounding_box=cast(tuple[float, float, float, float] | None, box),
            coordinate_system=cast(str | None, value.get("coordinate_system")),
        )
    except (TypeError, ValueError):
        raise RuntimeError("hydrated source location is malformed") from None


_ELIGIBILITY_SQL = """
SELECT paper.id AS paper_id, paper.title, paper.publication_year,
       count(chunk.id)::bigint AS evidence_count
FROM snapshot_items AS item
JOIN papers AS paper ON paper.id = item.paper_id
JOIN documents AS document
  ON document.id = item.document_id AND document.paper_id = item.paper_id
JOIN extractions AS extraction
  ON extraction.id = item.extraction_id
 AND extraction.document_id = item.document_id
JOIN document_artifacts AS artifact
  ON artifact.id = extraction.source_artifact_id
 AND artifact.document_id = extraction.document_id
JOIN artifacts AS source_file ON source_file.id = artifact.artifact_id
JOIN document_permission_evidence AS permission
  ON permission.id = artifact.permission_evidence_id
 AND permission.document_id = artifact.document_id
JOIN snapshot_item_chunks AS selected
  ON selected.snapshot_id = item.snapshot_id
 AND selected.paper_id = item.paper_id
 AND selected.document_id = item.document_id
 AND selected.extraction_id = item.extraction_id
JOIN chunks AS chunk
  ON chunk.id = selected.chunk_id
 AND chunk.document_id = selected.document_id
 AND chunk.extraction_id = selected.extraction_id
WHERE item.snapshot_id = $1
  AND ($2::integer IS NULL OR paper.publication_year >= $2)
  AND ($3::integer IS NULL OR paper.publication_year <= $3)
  AND ($4::text[] IS NULL OR paper.id = ANY($4::text[]))
  AND ($5::text[] IS NULL OR chunk.kind = ANY($5::text[]))
  AND ($6::text[] IS NULL OR document.version_kind = ANY($6::text[]))
  AND extraction.status IN ('completed', 'partial')
  AND artifact.storage_permitted AND artifact.indexing_permitted
  AND permission.storage_permitted AND permission.indexing_permitted
GROUP BY paper.id, paper.title, paper.publication_year
ORDER BY paper.id
"""
