"""Asynchronous lexical branches: BM25S adapters and Qdrant sparse search (P35-13).

The Qdrant branches reproduce ``LexicalRetriever.search_with_stats`` exactly: the same
eligibility, positive-match counts, ``(-score, stable_id)`` ordering and truncation
(ADR-0022 item 3). Every sparse query sends the generation as the IDF corpus filter.
"""

from __future__ import annotations

import asyncio
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from typing import Literal, Protocol

from research_platform.ingestion.generation_index import (
    GenerationMatch,
    GenerationQdrantCollection,
    SparseLexicalSettings,
    SparseVector,
    generation_filter,
    indexed_paper_filter,
    with_conditions,
)
from research_platform.ingestion.snapshot_selection import SnapshotSelection
from research_platform.search.contracts import SearchFilters, SearchOperation
from research_platform.search.dense_search import _qdrant_payload_conditions
from research_platform.search.lexical import (
    IndexRole,
    LexicalHit,
    LexicalRetriever,
    LexicalSearchResult,
)
from research_platform.search.lexical_analyzer import tokenize_scientific_english
from research_platform.search.profiles import RetrievalProfile
from research_platform.search.sparse_lexical import (
    VocabularyRepository,
    query_term_weights,
    to_sparse_vector,
)

TIE_MARGIN = 50


@dataclass(frozen=True)
class LexicalBranchIdentity:
    role: IndexRole
    profile_id: str
    snapshot: SnapshotSelection
    snapshot_status: Literal["draft", "finalized"]
    candidate_limit: int


class AsyncLexicalEvidenceBranch(Protocol):
    @property
    def profile(self) -> RetrievalProfile: ...

    @property
    def identity(self) -> LexicalBranchIdentity: ...

    async def search_with_stats(
        self,
        query: str,
        *,
        limit: int,
        filters: SearchFilters = SearchFilters(),
    ) -> LexicalSearchResult: ...


class AsyncLexicalPaperBranch(Protocol):
    @property
    def identity(self) -> LexicalBranchIdentity: ...

    async def search_with_stats(
        self, query: str, *, eligible_ids: Collection[str], limit: int
    ) -> LexicalSearchResult: ...


def _identity_from_retriever(retriever: LexicalRetriever) -> LexicalBranchIdentity:
    manifest = retriever.manifest
    return LexicalBranchIdentity(
        role=manifest.role,
        profile_id=manifest.profile_id,
        snapshot=manifest.snapshot,
        snapshot_status=manifest.snapshot_status,
        candidate_limit=manifest.candidate_limit,
    )


class BM25SEvidenceBranch:
    """The in-process BM25S evidence index behind the asynchronous protocol."""

    def __init__(self, retriever: LexicalRetriever) -> None:
        self._retriever = retriever
        self._identity = _identity_from_retriever(retriever)

    @property
    def profile(self) -> RetrievalProfile:
        return self._retriever.profile

    @property
    def identity(self) -> LexicalBranchIdentity:
        return self._identity

    async def search_with_stats(
        self,
        query: str,
        *,
        limit: int,
        filters: SearchFilters = SearchFilters(),
    ) -> LexicalSearchResult:
        return await asyncio.to_thread(
            self._retriever.search_with_stats, query, limit=limit, filters=filters
        )


class BM25SPaperBranch:
    """The in-process BM25S paper index behind the asynchronous protocol."""

    def __init__(self, retriever: LexicalRetriever) -> None:
        self._retriever = retriever
        self._identity = _identity_from_retriever(retriever)

    @property
    def identity(self) -> LexicalBranchIdentity:
        return self._identity

    async def search_with_stats(
        self, query: str, *, eligible_ids: Collection[str], limit: int
    ) -> LexicalSearchResult:
        return await asyncio.to_thread(
            self._retriever.search_with_stats,
            query,
            eligible_ids=eligible_ids,
            limit=limit,
        )


class _QdrantLexical:
    def __init__(
        self,
        *,
        profile: RetrievalProfile,
        collection: GenerationQdrantCollection,
        vocabulary: VocabularyRepository,
        settings: SparseLexicalSettings,
        generation: int,
        candidate_limit: int,
        role: IndexRole,
    ) -> None:
        self._profile = profile
        self._collection = collection
        self._vocabulary = vocabulary
        self._settings = settings
        self._generation = generation
        self._identity = LexicalBranchIdentity(
            role=role,
            profile_id=profile.profile_id,
            snapshot=profile.snapshot,
            snapshot_status="finalized",
            candidate_limit=candidate_limit,
        )

    @property
    def profile(self) -> RetrievalProfile:
        return self._profile

    @property
    def identity(self) -> LexicalBranchIdentity:
        return self._identity

    def _validate(self, query: str, limit: int) -> None:
        if not isinstance(query, str):
            raise TypeError("query must be text")
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise ValueError("limit must be a positive integer")
        if limit > self._identity.candidate_limit:
            raise ValueError("limit exceeds the profile lexical candidate limit")

    async def _search(
        self,
        query: str,
        *,
        limit: int,
        base: Mapping[str, object],
        corpus: Mapping[str, object],
        stable_key: str,
        filters: SearchFilters,
        eligible_count: int,
    ) -> LexicalSearchResult:
        tokens = tokenize_scientific_english(query)
        term_ids = await self._vocabulary.lookup(self._settings.vocabulary_id, tokens)
        empty = LexicalSearchResult(
            hits=(),
            available_count=0,
            eligible_count=eligible_count,
            limit=limit,
            truncated=False,
            applied_filters=filters,
        )
        if eligible_count == 0 or not term_ids:
            return empty
        available = await self._collection.count(
            with_conditions(
                base,
                [{"key": "lexical_terms", "match": {"any": sorted(term_ids)}}],
            )
        )
        if available == 0:
            return empty
        vector = to_sparse_vector(query_term_weights(tokens), term_ids)
        ranked = await self._ranked(vector, base, corpus, stable_key, limit, available)
        hits = tuple(
            LexicalHit(stable_id=stable_id, paper_id=paper_id, row=row, score=score)
            for row, (stable_id, paper_id, score) in enumerate(ranked[:limit])
        )
        return LexicalSearchResult(
            hits=hits,
            available_count=available,
            eligible_count=eligible_count,
            limit=limit,
            truncated=available > limit,
            applied_filters=filters,
        )

    async def _ranked(
        self,
        vector: SparseVector,
        base: Mapping[str, object],
        corpus: Mapping[str, object],
        stable_key: str,
        limit: int,
        available: int,
    ) -> list[tuple[str, str, float]]:
        """Fetch enough candidates that no score tie crosses the ``limit`` boundary."""
        fetch = min(available, limit + TIE_MARGIN)
        while True:
            matches = await self._collection.query_sparse(
                vector, filter_=base, idf_filter=corpus, limit=fetch
            )
            if len(matches) != fetch:
                raise RuntimeError(
                    "sparse matches differ from the positive-match count"
                )
            ranked = sorted(
                (_hit_fields(match, stable_key) for match in matches),
                key=lambda item: (-item[2], item[0]),
            )
            boundary_tied = fetch < available and ranked[limit - 1][2] == ranked[-1][2]
            if not boundary_tied:
                return ranked
            fetch = min(available, fetch * 2)


class QdrantEvidenceLexicalBranch(_QdrantLexical):
    """Scientific BM25 over a generation's passages, executed by Qdrant."""

    def __init__(
        self,
        *,
        profile: RetrievalProfile,
        passages: GenerationQdrantCollection,
        vocabulary: VocabularyRepository,
        settings: SparseLexicalSettings,
        generation: int,
        candidate_limit: int,
    ) -> None:
        super().__init__(
            profile=profile,
            collection=passages,
            vocabulary=vocabulary,
            settings=settings,
            generation=generation,
            candidate_limit=candidate_limit,
            role="evidence",
        )

    async def search_with_stats(
        self,
        query: str,
        *,
        limit: int,
        filters: SearchFilters = SearchFilters(),
    ) -> LexicalSearchResult:
        if not isinstance(filters, SearchFilters):
            raise ValueError("filters must be SearchFilters")
        filters.validate_for(SearchOperation.EVIDENCE_SEARCH)
        self._validate(query, limit)
        corpus = generation_filter(self._generation)
        base = with_conditions(corpus, generation_conditions(filters))
        return await self._search(
            query,
            limit=limit,
            base=base,
            corpus=corpus,
            stable_key="evidence_id",
            filters=filters,
            eligible_count=await self._collection.count(base),
        )


class QdrantPaperLexicalBranch(_QdrantLexical):
    """Scientific BM25 over a generation's indexed papers, executed by Qdrant."""

    def __init__(
        self,
        *,
        profile: RetrievalProfile,
        papers: GenerationQdrantCollection,
        vocabulary: VocabularyRepository,
        settings: SparseLexicalSettings,
        generation: int,
        candidate_limit: int,
    ) -> None:
        super().__init__(
            profile=profile,
            collection=papers,
            vocabulary=vocabulary,
            settings=settings,
            generation=generation,
            candidate_limit=candidate_limit,
            role="paper",
        )

    async def search_with_stats(
        self, query: str, *, eligible_ids: Collection[str], limit: int
    ) -> LexicalSearchResult:
        self._validate(query, limit)
        if any(not isinstance(paper_id, str) for paper_id in eligible_ids):
            raise ValueError("eligible IDs must be strings")
        corpus = indexed_paper_filter(self._generation)
        paper_ids = sorted(set(eligible_ids))
        if not paper_ids:
            return LexicalSearchResult(
                hits=(),
                available_count=0,
                eligible_count=0,
                limit=limit,
                truncated=False,
            )
        base = with_conditions(
            corpus, [{"key": "paper_id", "match": {"any": paper_ids}}]
        )
        return await self._search(
            query,
            limit=limit,
            base=base,
            corpus=corpus,
            stable_key="paper_id",
            filters=SearchFilters(),
            eligible_count=len(paper_ids),
        )


def generation_conditions(filters: SearchFilters) -> list[dict[str, object]]:
    """Search filter conditions for generation points (no per-snapshot revision tag)."""
    return [
        condition
        for condition in _qdrant_payload_conditions(filters)
        if condition.get("key") != "filter_payload_revision"
    ]


def _hit_fields(match: GenerationMatch, stable_key: str) -> tuple[str, str, float]:
    stable_id = match.payload.get(stable_key)
    paper_id = match.payload.get("paper_id")
    if not isinstance(stable_id, str) or not isinstance(paper_id, str):
        raise RuntimeError("sparse match is missing its identity payload")
    return stable_id, paper_id, match.score
