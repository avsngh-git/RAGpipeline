"""Unit tests for asynchronous lexical branches (P35-13)."""

from __future__ import annotations

import asyncio
from collections.abc import Collection, Mapping
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import pytest

from research_platform.ingestion.generation_index import (
    GenerationMatch,
    GenerationQdrantCollection,
    SparseLexicalSettings,
    SparseVector,
    generation_filter,
    indexed_paper_filter,
)
from research_platform.search.contracts import SearchFilters
from research_platform.search.lexical import LexicalSearchResult
from research_platform.search.lexical_branches import (
    BM25SEvidenceBranch,
    QdrantEvidenceLexicalBranch,
    QdrantPaperLexicalBranch,
)
from research_platform.search.profile_manifest import load_frozen_profile
from research_platform.search.sparse_lexical import VocabularyRepository

ROOT = Path(__file__).resolve().parents[1]
PROFILE = load_frozen_profile(ROOT / "benchmarks/phase2/frozen-profile-v10.toml")
SETTINGS = SparseLexicalSettings("scientific-en", "v1", "vocab", 1.5, 0.75, 30.0, 10.0)


class _Vocabulary:
    def __init__(self, terms: Mapping[str, int]) -> None:
        self.terms = dict(terms)

    async def lookup(
        self, vocabulary_id: str, terms: Collection[str]
    ) -> dict[str, int]:
        return {term: self.terms[term] for term in set(terms) if term in self.terms}


class _Collection:
    """Points have an evidence ID, paper ID, term set and a fixed score."""

    def __init__(self, points: list[dict[str, Any]], *, eligible: int | None = None):
        self.points = points
        self.eligible = eligible
        self.query_limits: list[int] = []
        self.calls: list[tuple[str, Mapping[str, object]]] = []

    def _terms_condition(self, filter_: Mapping[str, object]) -> set[str] | None:
        for condition in cast(list[dict[str, Any]], filter_.get("must", [])):
            if condition.get("key") == "lexical_terms":
                return set(condition["match"]["any"])
        return None

    async def count(self, filter_: Mapping[str, object]) -> int:
        self.calls.append(("count", filter_))
        terms = self._terms_condition(filter_)
        if terms is None:
            return len(self.points) if self.eligible is None else self.eligible
        return sum(1 for point in self.points if point["terms"] & terms)

    async def query_sparse(
        self,
        vector: SparseVector,
        *,
        filter_: Mapping[str, object],
        idf_filter: Mapping[str, object],
        limit: int,
    ):
        self.calls.append(("query", {"filter": filter_, "idf": idf_filter}))
        self.query_limits.append(limit)
        ordered = sorted(self.points, key=lambda p: -p["score"])  # arbitrary tie order
        return tuple(
            GenerationMatch(
                uuid4(),
                point["score"],
                {"evidence_id": point["id"], "paper_id": point["paper"]},
            )
            for point in ordered
            if point["score"] > 0
        )[:limit]


def _points(scores: list[float]) -> list[dict[str, Any]]:
    return [
        {"id": f"e{index:03d}", "paper": "W1", "terms": {"bm25"}, "score": score}
        for index, score in enumerate(scores)
    ]


def _branch(collection: _Collection, terms: Mapping[str, int] | None = None, limit=50):
    return QdrantEvidenceLexicalBranch(
        profile=PROFILE,
        passages=cast(GenerationQdrantCollection, collection),
        vocabulary=cast(VocabularyRepository, _Vocabulary(terms or {"bm25": 1})),
        settings=SETTINGS,
        generation=2,
        candidate_limit=limit,
    )


def _search(
    branch, query="bm25", limit=3, filters=SearchFilters()
) -> LexicalSearchResult:
    return asyncio.run(branch.search_with_stats(query, limit=limit, filters=filters))


def test_bm25s_adapter_returns_identical_results() -> None:
    expected = LexicalSearchResult(
        hits=(), available_count=0, eligible_count=4, limit=5, truncated=False
    )
    retriever = SimpleNamespace(
        profile=PROFILE,
        manifest=SimpleNamespace(
            role="evidence",
            profile_id=PROFILE.profile_id,
            snapshot=PROFILE.snapshot,
            snapshot_status="finalized",
            candidate_limit=50,
        ),
        search_with_stats=lambda query, *, limit, filters: expected,
    )
    branch = BM25SEvidenceBranch(cast(Any, retriever))

    assert asyncio.run(branch.search_with_stats("q", limit=5)) is expected
    assert branch.identity.candidate_limit == 50
    assert branch.profile is PROFILE


def test_empty_eligibility_and_unknown_terms() -> None:
    nothing_eligible = _search(_branch(_Collection(_points([1.0]), eligible=0)))
    assert (nothing_eligible.eligible_count, nothing_eligible.hits) == (0, ())
    unknown = _search(_branch(_Collection(_points([1.0])), terms={}), query="other")
    assert unknown.eligible_count == 1 and unknown.available_count == 0
    empty_query = _search(_branch(_Collection(_points([1.0]))), query="")
    assert empty_query.hits == ()


def test_ties_sorted_by_evidence_id() -> None:
    result = _search(_branch(_Collection(_points([1.0, 2.0, 2.0, 2.0, 0.5]))), limit=3)
    assert [hit.stable_id for hit in result.hits] == ["e001", "e002", "e003"]
    assert [hit.row for hit in result.hits] == [0, 1, 2]
    assert result.available_count == 5 and result.truncated


def test_boundary_tie_triggers_refetch() -> None:
    scores = [1.0] * 70 + [2.0]
    collection = _Collection(_points(scores))
    result = _search(_branch(collection), limit=3)

    assert collection.query_limits == [53, 71]
    assert [hit.stable_id for hit in result.hits] == ["e070", "e000", "e001"]


def test_truncated_flag_and_counts() -> None:
    result = _search(_branch(_Collection(_points([3.0, 2.0]))), limit=3)
    assert (result.available_count, result.truncated, len(result.hits)) == (2, False, 2)


def test_filters_appended_to_generation_filter() -> None:
    collection = _Collection(_points([1.0]))
    _search(_branch(collection), filters=SearchFilters(year_from=2021))
    base = collection.calls[0][1]
    must = cast(list[object], base["must"])
    assert must[:2] == generation_filter(2)["must"]
    assert {"key": "publication_year", "range": {"gte": 2021}} in must
    query = [call for call in collection.calls if call[0] == "query"][0][1]
    assert query["idf"] == generation_filter(2)
    with pytest.raises(ValueError, match="candidate limit"):
        _search(_branch(collection, limit=2), limit=3)


def test_paper_branch_restricts_to_eligible_ids() -> None:
    collection = _Collection(
        [{"id": "W1", "paper": "W1", "terms": {"bm25"}, "score": 1.0}]
    )
    branch = QdrantPaperLexicalBranch(
        profile=PROFILE,
        papers=cast(GenerationQdrantCollection, collection),
        vocabulary=cast(VocabularyRepository, _Vocabulary({"bm25": 1})),
        settings=SETTINGS,
        generation=1,
        candidate_limit=50,
    )
    result = asyncio.run(branch.search_with_stats("bm25", eligible_ids={"W1"}, limit=5))
    assert [hit.stable_id for hit in result.hits] == ["W1"]
    assert result.eligible_count == 1
    query = [call for call in collection.calls if call[0] == "query"][0][1]
    assert query["filter"]["must"] == [
        *indexed_paper_filter(1)["must"],
        {"key": "paper_id", "match": {"any": ["W1"]}},
    ]
    assert query["idf"] == indexed_paper_filter(1)
    empty = asyncio.run(branch.search_with_stats("bm25", eligible_ids=set(), limit=5))
    assert empty.eligible_count == 0
