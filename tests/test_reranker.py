"""Profile, batching, alignment and failure checks for cross-encoder scoring."""

import asyncio
import math
import threading
import time
from dataclasses import replace
from uuid import UUID

import pytest

from research_platform.ingestion.evidence import SourceLocation
from research_platform.ingestion.snapshot_selection import SnapshotSelection
from research_platform.search.contracts import (
    ComponentScores,
    EvidenceHit,
    RankedComponent,
)
from research_platform.search.profiles import (
    CandidateLimits,
    DenseIndexIdentity,
    FusionSettings,
    LexicalIndexIdentity,
    RerankerIdentity,
    RetrievalProfile,
)
from research_platform.search.reranker import (
    CrossEncoderReranker,
    RerankerCandidateLimitExceeded,
    RerankerInferenceFailure,
    RerankerInferenceTimeout,
    RerankerInvalidScoreError,
    RerankerOutputAlignmentError,
    RerankerProfileMismatch,
)
from research_platform.search.reranker_pairs import RerankerPairBudgetExceeded
from research_platform.search.reranker_results import (
    RerankerProvenanceError,
    apply_reranker_scores,
)

SNAPSHOT_ID = UUID("4b11fab3-d4a5-4e7a-a58e-8654accf2c6c")
SNAPSHOT_CONFIG_ID = "sha256:" + "a" * 64
INDEX_CONFIG_ID = "sha256:" + "b" * 64
IDENTITY = RerankerIdentity(
    model="cross-encoder/test-reranker",
    revision="revision-a",
    preprocessing_revision="query-source-chunk-v1",
    maximum_input_tokens=512,
)


class FixedPairCounter:
    def __init__(self, count: int = 16) -> None:
        self.count = count
        self.calls: list[tuple[str, str]] = []
        self.thread_ids: list[int] = []

    def count_pair(self, query: str, evidence_text: str) -> int:
        self.calls.append((query, evidence_text))
        self.thread_ids.append(threading.get_ident())
        return self.count


class FakeScorer:
    def __init__(self, scores: list[float] | None = None) -> None:
        self.scores = scores or []
        self.calls: list[tuple[tuple[str, str], ...]] = []
        self.thread_ids: list[int] = []

    def score_pairs(self, pairs: tuple[tuple[str, str], ...]) -> list[float]:
        self.calls.append(tuple(pairs))
        self.thread_ids.append(threading.get_ident())
        offset = sum(len(batch) for batch in self.calls[:-1])
        return self.scores[offset : offset + len(pairs)]


def _profile(
    *, identity: RerankerIdentity | None = IDENTITY, rerank_limit: int = 5
) -> RetrievalProfile:
    return RetrievalProfile(
        snapshot=SnapshotSelection(
            snapshot_id=SNAPSHOT_ID,
            snapshot_configuration_id=SNAPSHOT_CONFIG_ID,
            chunk_selection_id="sha256:" + "c" * 64,
        ),
        lexical_index=LexicalIndexIdentity(
            implementation="bm25s",
            implementation_revision="0.3.11",
            analyzer="scientific-en-v1",
            analyzer_revision="v1",
            normalization_revision="v1",
            index_format_revision="v1",
        ),
        dense_index=DenseIndexIdentity(
            model="test-embedder",
            revision="revision-a",
            preprocessing_revision="query-passage-v1",
            dimensions=2,
            maximum_input_tokens=512,
            index_configuration_id=INDEX_CONFIG_ID,
        ),
        reranker=identity,
        fusion=FusionSettings(),
        candidate_limits=CandidateLimits(
            lexical_top_k=5,
            dense_top_k=5,
            fused_top_k=5,
            rerank_top_k=rerank_limit if identity is not None else None,
        ),
    )


def _hit(rank: int, number: int, text: str | None = None) -> EvidenceHit:
    stable_id = f"sha256:{number:064x}"
    return EvidenceHit(
        chunk_id=stable_id,
        source_evidence_ids=(stable_id,),
        paper_id="W100",
        document_id=UUID("91a7da33-066d-4c78-838a-413ba2f1b8d4"),
        document_version="published-2025",
        document_version_kind="published",
        extraction_id=UUID("6715a62a-fb8c-41d3-812d-3130baf08f0f"),
        chunking_configuration_id=None,
        kind="text",
        source_location=SourceLocation(page_index_zero_based=rank),
        rank=rank,
        component_scores=ComponentScores(
            fusion=RankedComponent(rank=rank, score=1.0 / (60 + rank))
        ),
        text=text or f"evidence {number}",
    )


def _adapter(
    scorer: FakeScorer,
    *,
    counter: FixedPairCounter | None = None,
    **kwargs: object,
) -> CrossEncoderReranker:
    return CrossEncoderReranker(
        IDENTITY,
        token_counter=counter or FixedPairCounter(),
        scorer=scorer,
        **kwargs,  # type: ignore[arg-type]
    )


def test_scores_batches_off_event_loop_and_stably_ranks_raw_scores() -> None:
    hits = (_hit(3, 3), _hit(1, 1), _hit(2, 2))
    scorer = FakeScorer([0.4, 0.9, 0.9])
    counter = FixedPairCounter()
    adapter = _adapter(scorer, counter=counter, batch_size=2)
    event_loop_thread = threading.get_ident()
    try:
        result = asyncio.run(adapter.rerank(_profile(), "query", hits))
    finally:
        adapter.close()

    assert [item.evidence_hit.chunk_id for item in result] == [
        hits[1].chunk_id,
        hits[2].chunk_id,
        hits[0].chunk_id,
    ]
    assert [item.rank for item in result] == [1, 2, 3]
    assert [item.original_rank for item in result] == [1, 2, 3]
    assert [item.score for item in result] == [0.9, 0.9, 0.4]
    assert result[0].evidence_hit is hits[1]
    assert [len(batch) for batch in scorer.calls] == [2, 1]
    assert counter.calls == [("query", hit.text) for hit in hits]
    assert set(scorer.thread_ids + counter.thread_ids).isdisjoint({event_loop_thread})


def test_profile_identity_and_rerank_candidate_bound_are_enforced() -> None:
    scorer = FakeScorer([0.1] * 6)
    adapter = _adapter(scorer)
    try:
        with pytest.raises(RerankerProfileMismatch):
            asyncio.run(
                adapter.rerank(
                    _profile(
                        identity=RerankerIdentity(
                            model=IDENTITY.model,
                            revision="different-revision",
                            preprocessing_revision=IDENTITY.preprocessing_revision,
                            maximum_input_tokens=512,
                        )
                    ),
                    "query",
                    (_hit(1, 1),),
                )
            )
        with pytest.raises(RerankerCandidateLimitExceeded, match="profile rerank"):
            asyncio.run(
                adapter.rerank(
                    _profile(rerank_limit=1),
                    "query",
                    (_hit(1, 1), _hit(2, 2)),
                )
            )
    finally:
        adapter.close()
    assert scorer.calls == []


@pytest.mark.parametrize(
    ("scores", "error"),
    [
        ([0.5], RerankerOutputAlignmentError),
        ([math.nan, 0.2], RerankerInvalidScoreError),
        ([math.inf, 0.2], RerankerInvalidScoreError),
        ([True, 0.2], RerankerInvalidScoreError),  # type: ignore[list-item]
    ],
)
def test_invalid_output_fails_without_returning_candidates(
    scores: list[float], error: type[Exception]
) -> None:
    adapter = _adapter(FakeScorer(scores))
    try:
        with pytest.raises(error):
            asyncio.run(adapter.rerank(_profile(), "query", (_hit(1, 1), _hit(2, 2))))
    finally:
        adapter.close()


def test_over_budget_pair_fails_as_a_whole_before_inference() -> None:
    scorer = FakeScorer([0.5])
    adapter = _adapter(scorer, counter=FixedPairCounter(513))
    try:
        with pytest.raises(RerankerPairBudgetExceeded):
            asyncio.run(adapter.rerank(_profile(), "query", (_hit(1, 1),)))
    finally:
        adapter.close()
    assert scorer.calls == []


def test_partial_batch_failure_does_not_expose_earlier_scores() -> None:
    class FailsOnSecondBatch:
        def __init__(self) -> None:
            self.calls = 0

        def score_pairs(self, pairs: tuple[tuple[str, str], ...]) -> list[float]:
            self.calls += 1
            if self.calls == 2:
                raise RuntimeError("private model failure")
            return [0.5] * len(pairs)

    adapter = _adapter(FailsOnSecondBatch(), batch_size=1)  # type: ignore[arg-type]
    try:
        with pytest.raises(RerankerInferenceFailure) as error:
            asyncio.run(adapter.rerank(_profile(), "query", (_hit(1, 1), _hit(2, 2))))
    finally:
        adapter.close()
    assert "private model failure" not in str(error.value)


def test_timeout_returns_controlled_error_while_worker_finishes() -> None:
    finished = threading.Event()

    class SlowScorer:
        def score_pairs(self, pairs: tuple[tuple[str, str], ...]) -> list[float]:
            time.sleep(0.04)
            finished.set()
            return [0.5] * len(pairs)

    adapter = _adapter(SlowScorer(), timeout_seconds=0.002)  # type: ignore[arg-type]
    try:
        with pytest.raises(RerankerInferenceTimeout):
            asyncio.run(adapter.rerank(_profile(), "query", (_hit(1, 1),)))
        assert finished.wait(timeout=1)
    finally:
        adapter.close()


def test_empty_pool_returns_empty_without_invoking_the_model() -> None:
    scorer = FakeScorer()
    adapter = _adapter(scorer)
    try:
        assert asyncio.run(adapter.rerank(_profile(), "query", ())) == ()
    finally:
        adapter.close()
    assert scorer.calls == []


def test_apply_reranker_scores_retains_all_prior_component_provenance() -> None:
    first = replace(
        _hit(3, 3),
        component_scores=ComponentScores(
            lexical=RankedComponent(rank=2, score=4.25),
            dense=RankedComponent(rank=1, score=0.875),
            fusion=RankedComponent(rank=3, score=0.032),
        ),
    )
    second = replace(
        _hit(1, 1),
        component_scores=ComponentScores(
            lexical=RankedComponent(rank=1, score=5.5),
            dense=RankedComponent(rank=2, score=0.825),
            fusion=RankedComponent(rank=1, score=0.033),
        ),
    )
    adapter = _adapter(FakeScorer([0.2, 0.9]))
    try:
        scores = asyncio.run(adapter.rerank(_profile(), "query", (first, second)))
    finally:
        adapter.close()

    result = apply_reranker_scores(_profile(), "query", (first, second), scores)

    assert [hit.chunk_id for hit in result] == [second.chunk_id, first.chunk_id]
    assert [hit.rank for hit in result] == [1, 2]
    assert result[0].component_scores == ComponentScores(
        lexical=second.component_scores.lexical,
        dense=second.component_scores.dense,
        fusion=second.component_scores.fusion,
        reranker=RankedComponent(rank=1, score=0.9),
    )
    assert result[1].component_scores.lexical == first.component_scores.lexical
    assert result[1].component_scores.dense == first.component_scores.dense
    assert result[1].component_scores.fusion == first.component_scores.fusion
    assert result[0].source_evidence_ids == second.source_evidence_ids
    assert result[0].source_location == second.source_location


def test_apply_reranker_scores_rejects_pool_changes_and_component_overwrite() -> None:
    original = (_hit(1, 1), _hit(2, 2))
    adapter = _adapter(FakeScorer([0.8, 0.2]))
    try:
        scores = asyncio.run(adapter.rerank(_profile(), "query", original))
    finally:
        adapter.close()

    with pytest.raises(RerankerProvenanceError, match="outside the supplied"):
        apply_reranker_scores(_profile(), "query", (_hit(1, 1), _hit(2, 3)), scores)
    with pytest.raises(RerankerProvenanceError, match="cover the candidate pool"):
        apply_reranker_scores(_profile(), "query", original, scores[:1])

    already_reranked = replace(
        original[0],
        component_scores=ComponentScores(reranker=RankedComponent(rank=1, score=0.8)),
    )
    with pytest.raises(RerankerProvenanceError, match="already reranked"):
        apply_reranker_scores(
            _profile(), "query", (already_reranked, original[1]), scores
        )

    missing_fusion_rank = replace(original[0], component_scores=ComponentScores())
    with pytest.raises(RerankerProvenanceError, match="original fused rank"):
        apply_reranker_scores(
            _profile(), "query", (missing_fusion_rank, original[1]), scores
        )


def test_apply_reranker_scores_rejects_a_different_model_identity() -> None:
    original = (_hit(1, 1),)
    adapter = _adapter(FakeScorer([0.8]))
    try:
        scores = asyncio.run(adapter.rerank(_profile(), "query", original))
    finally:
        adapter.close()

    other_profile = _profile(
        identity=RerankerIdentity(
            model=IDENTITY.model,
            revision="different-revision",
            preprocessing_revision=IDENTITY.preprocessing_revision,
            maximum_input_tokens=IDENTITY.maximum_input_tokens,
        )
    )
    with pytest.raises(RerankerProvenanceError, match="identity differs"):
        apply_reranker_scores(other_profile, "query", original, scores)


def test_apply_reranker_scores_rejects_different_profile_or_query() -> None:
    original = (_hit(1, 1),)
    profile = _profile()
    adapter = _adapter(FakeScorer([0.8]))
    try:
        scores = asyncio.run(adapter.rerank(profile, "query", original))
    finally:
        adapter.close()

    other_profile = replace(profile, fusion=FusionSettings(rank_constant=30))
    with pytest.raises(RerankerProvenanceError, match="profile differs"):
        apply_reranker_scores(other_profile, "query", original, scores)
    with pytest.raises(RerankerProvenanceError, match="query identity"):
        apply_reranker_scores(profile, "different query", original, scores)
