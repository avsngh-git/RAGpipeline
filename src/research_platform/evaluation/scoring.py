"""Deterministic per-family scoring for reviewed calibration rankings."""

from __future__ import annotations

import math
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import TypeVar
from uuid import UUID

from research_platform.evaluation.calibration import (
    CalibrationDataset,
    EvidenceJudgment,
    PaperJudgment,
    QuestionFamily,
)
from research_platform.evaluation.matching import (
    SourceAnchorMatch,
    SourceEvidenceRegion,
    match_evidence_hit,
    match_evidence_hits,
)
from research_platform.evaluation.source_alignment import SourceAlignmentDataset
from research_platform.ingestion.identity import is_valid_paper_id
from research_platform.search.contracts import EvidenceHit, PaperHit

_CUTOFFS = (10, 20, 50)
_MAX_GAIN = 3
_SCORING_POLICY_ID = "evaluation-scoring-policy-v1"
HitT = TypeVar("HitT", PaperHit, EvidenceHit)


class EvaluationScoringError(ValueError):
    """A ranking or scoring scope is inconsistent with its calibration family."""


@dataclass(frozen=True)
class MetricValue:
    """One metric with its numerator and denominator retained for aggregation."""

    value: float | None
    numerator: float
    denominator: float


@dataclass(frozen=True)
class RankingMetrics:
    """Quality and judgment coverage for one ranked result type."""

    ndcg_at_10: MetricValue
    direct_mrr_at_10: MetricValue
    judged_recall_at_20: MetricValue
    judged_recall_at_50: MetricValue
    judgment_coverage: MetricValue


@dataclass(frozen=True)
class EvidenceGroupCoverage:
    """Required-piece and complete-group coverage at one result cutoff."""

    cutoff: int
    required_pieces: MetricValue
    complete_groups: MetricValue


@dataclass(frozen=True)
class HitGradeCounts:
    """Returned candidate counts by reviewed label, including unjudged hits."""

    returned: int
    judged: int
    unjudged: int
    label_0: int
    label_1: int
    label_2: int


@dataclass(frozen=True)
class UnsupportedRetrievalProfile:
    """Returned-hit characteristics without an acceptance decision threshold."""

    paper_hits: HitGradeCounts
    evidence_hits: HitGradeCounts


@dataclass(frozen=True)
class QueryFamilyScore:
    """Per-query metrics with family identity retained for paired analysis."""

    calibration_dataset_id: str
    snapshot_id: UUID
    source_alignment_id: str
    source_matching_policy_id: str
    scoring_policy_id: str
    family_id: str
    query_id: str
    split: str
    eligible_paper_count: int | None
    empty_eligibility: bool
    paper: RankingMetrics
    evidence: RankingMetrics
    evidence_group_coverage: tuple[EvidenceGroupCoverage, ...]
    unsupported_profile: UnsupportedRetrievalProfile | None


def score_query_family(
    calibration: CalibrationDataset,
    *,
    family_id: str,
    query_id: str,
    paper_result_snapshot_id: UUID,
    evidence_result_snapshot_id: UUID,
    paper_hits: Sequence[PaperHit],
    evidence_hits: Sequence[EvidenceHit],
    regions_by_evidence_id: Mapping[str, SourceEvidenceRegion],
    alignments: SourceAlignmentDataset,
    eligible_paper_ids: Collection[str] | None = None,
) -> QueryFamilyScore:
    """Score one query result against the judgments for its family.

    For metadata filters that cannot be checked on every hit, pass the exact
    eligible paper IDs resolved from the query's accepted snapshot. Rank values are
    consumed as given: missing ranks stay empty and duplicate ranks are rejected.
    """
    if alignments.calibration_dataset_id != calibration.dataset_id:
        raise EvaluationScoringError(
            "source alignment belongs to a different calibration dataset"
        )
    if alignments.snapshot_id != calibration.snapshot_id:
        raise EvaluationScoringError(
            "source alignment belongs to a different snapshot"
        )
    if alignments.policy_id != "source-match-policy-v1":
        raise EvaluationScoringError("unsupported source matching policy")
    if paper_result_snapshot_id != calibration.snapshot_id:
        raise EvaluationScoringError("paper results use a different snapshot")
    if evidence_result_snapshot_id != calibration.snapshot_id:
        raise EvaluationScoringError("evidence results use a different snapshot")
    family = next((item for item in calibration.families if item.id == family_id), None)
    if family is None:
        raise EvaluationScoringError(f"unknown calibration family: {family_id}")
    if query_id not in {query.id for query in family.queries}:
        raise EvaluationScoringError("query_id does not belong to family_id")

    eligible = _resolve_eligible_papers(family, eligible_paper_ids)
    ordered_papers = _ordered_hits(paper_hits, PaperHit, "paper")
    ordered_evidence = _ordered_hits(evidence_hits, EvidenceHit, "evidence")
    _validate_hit_scope(family, ordered_papers, ordered_evidence, eligible)

    paper_labels = _paper_labels(family, eligible)
    evidence_labels = _evidence_labels(family, eligible)
    empty_eligibility = eligible is not None and not eligible
    paper_metrics, paper_counts = _score_papers(ordered_papers, paper_labels)
    evidence_metrics, evidence_groups, evidence_counts = _score_evidence(
        family,
        ordered_evidence,
        evidence_labels,
        regions_by_evidence_id,
        alignments,
        empty_eligibility=empty_eligibility,
    )
    unsupported_profile = None
    if family.unsupported or empty_eligibility:
        unsupported_profile = UnsupportedRetrievalProfile(
            paper_hits=paper_counts,
            evidence_hits=evidence_counts,
        )
    return QueryFamilyScore(
        calibration_dataset_id=calibration.dataset_id,
        snapshot_id=calibration.snapshot_id,
        source_alignment_id=alignments.alignment_id,
        source_matching_policy_id=alignments.policy_id,
        scoring_policy_id=_SCORING_POLICY_ID,
        family_id=family.id,
        query_id=query_id,
        split=family.split,
        eligible_paper_count=len(eligible) if eligible is not None else None,
        empty_eligibility=empty_eligibility,
        paper=paper_metrics,
        evidence=evidence_metrics,
        evidence_group_coverage=evidence_groups,
        unsupported_profile=unsupported_profile,
    )


def _resolve_eligible_papers(
    family: QuestionFamily,
    supplied: Collection[str] | None,
) -> frozenset[str] | None:
    filters = family.filters
    needs_snapshot_resolution = any(
        (
            filters.year_from is not None,
            filters.year_to is not None,
            filters.document_version_kinds is not None,
            filters.evidence_kinds is not None,
        )
    )
    if supplied is None:
        if needs_snapshot_resolution:
            raise EvaluationScoringError(
                "eligible_paper_ids are required for this metadata-filtered family"
            )
        if filters.paper_ids is not None:
            return frozenset(filters.paper_ids)
        return None
    if isinstance(supplied, str):
        raise EvaluationScoringError("eligible_paper_ids must be a collection of IDs")
    resolved = frozenset(supplied)
    if any(not is_valid_paper_id(paper_id) for paper_id in resolved):
        raise EvaluationScoringError("eligible_paper_ids contains an invalid paper ID")
    if filters.paper_ids is not None and not resolved.issubset(filters.paper_ids):
        raise EvaluationScoringError(
            "eligible_paper_ids contains papers outside the explicit paper filter"
        )
    return resolved


def _ordered_hits(
    hits: Sequence[HitT], hit_type: type[HitT], name: str
) -> tuple[HitT, ...]:
    if any(not isinstance(hit, hit_type) for hit in hits):
        raise EvaluationScoringError(f"{name}_hits contains an unsupported result type")
    ranks = [hit.rank for hit in hits]
    if len(set(ranks)) != len(ranks):
        raise EvaluationScoringError(f"{name}_hits contains duplicate result ranks")
    return tuple(sorted(hits, key=lambda hit: hit.rank))


def _validate_hit_scope(
    family: QuestionFamily,
    paper_hits: Sequence[PaperHit],
    evidence_hits: Sequence[EvidenceHit],
    eligible: frozenset[str] | None,
) -> None:
    for hit in (*paper_hits, *evidence_hits):
        if eligible is not None and hit.paper_id not in eligible:
            raise EvaluationScoringError(
                f"returned paper {hit.paper_id} is outside the eligible filter scope"
            )
        if (
            family.filters.paper_ids is not None
            and hit.paper_id not in family.filters.paper_ids
        ):
            raise EvaluationScoringError(
                f"returned paper {hit.paper_id} is outside the explicit paper filter"
            )
    for hit in paper_hits:
        year = hit.publication_year
        if family.filters.year_from is not None and (
            year is None or year < family.filters.year_from
        ):
            raise EvaluationScoringError("paper hit is outside the year_from filter")
        if family.filters.year_to is not None and (
            year is None or year > family.filters.year_to
        ):
            raise EvaluationScoringError("paper hit is outside the year_to filter")
    for hit in evidence_hits:
        if (
            family.filters.evidence_kinds is not None
            and hit.kind not in family.filters.evidence_kinds
        ):
            raise EvaluationScoringError(
                "evidence hit is outside the evidence_kinds filter"
            )
        if (
            family.filters.document_version_kinds is not None
            and hit.document_version_kind not in family.filters.document_version_kinds
        ):
            raise EvaluationScoringError(
                "evidence hit is outside the document_version_kinds filter"
            )


def _paper_labels(
    family: QuestionFamily, eligible: frozenset[str] | None
) -> dict[str, int]:
    return {
        judgment.paper_id: judgment.label
        for judgment in family.paper_judgments
        if eligible is None or judgment.paper_id in eligible
    }


def _evidence_labels(
    family: QuestionFamily, eligible: frozenset[str] | None
) -> dict[str, EvidenceJudgment]:
    return {
        judgment.source_anchor_id: judgment
        for judgment in family.evidence_judgments
        if eligible is None or judgment.paper_id in eligible
    }


def _score_papers(
    hits: Sequence[PaperHit], labels: Mapping[str, int]
) -> tuple[RankingMetrics, HitGradeCounts]:
    actual_dcg = 0.0
    seen_papers: set[str] = set()
    for hit in hits:
        if hit.rank > 10 or hit.paper_id in seen_papers:
            continue
        seen_papers.add(hit.paper_id)
        actual_dcg += _gain(labels.get(hit.paper_id, 0)) / math.log2(hit.rank + 1)
    ideal_gains = sorted(
        (_gain(label) for label in labels.values() if label > 0), reverse=True
    )
    ndcg = _ndcg_metric(actual_dcg, ideal_gains)
    positive_papers = {
        paper_id for paper_id, label in labels.items() if label == 2
    }
    first_positive_rank = min(
        (hit.rank for hit in hits if hit.paper_id in positive_papers), default=None
    )
    mrr = _reciprocal_rank(first_positive_rank, bool(positive_papers))
    recall20 = _recall(
        positive_papers,
        {hit.paper_id for hit in hits if hit.rank <= 20},
    )
    recall50 = _recall(
        positive_papers,
        {hit.paper_id for hit in hits if hit.rank <= 50},
    )
    judged_count = sum(hit.paper_id in labels for hit in hits)
    coverage = _ratio(float(judged_count), float(len(hits)))
    counts = _grade_counts(labels.get(hit.paper_id) for hit in hits)
    return (
        RankingMetrics(ndcg, mrr, recall20, recall50, coverage),
        counts,
    )


def _score_evidence(
    family: QuestionFamily,
    hits: Sequence[EvidenceHit],
    labels: Mapping[str, EvidenceJudgment],
    regions_by_evidence_id: Mapping[str, SourceEvidenceRegion],
    alignments: SourceAlignmentDataset,
    *,
    empty_eligibility: bool,
) -> tuple[
    RankingMetrics,
    tuple[EvidenceGroupCoverage, ...],
    HitGradeCounts,
]:
    per_hit_matches = tuple(
        match_evidence_hit(hit, regions_by_evidence_id, alignments) for hit in hits
    )
    judged_count = sum(
        any(
            match.directly_supported and match.anchor_id in labels
            for match in matches
        )
        for matches in per_hit_matches
    )
    coverage = _ratio(float(judged_count), float(len(hits)))
    grade_counts = _grade_counts(
        _best_direct_label(matches, labels) for matches in per_hit_matches
    )

    first_direct_rank: dict[str, int] = {}
    first_full_rank: dict[str, int] = {}
    cumulative_hits: list[EvidenceHit] = []
    actual_dcg = 0.0
    for hit in hits:
        if hit.rank > 50:
            break
        cumulative_hits.append(hit)
        prefix_matches = match_evidence_hits(
            cumulative_hits, regions_by_evidence_id, alignments
        )
        rank_gains: list[int] = []
        for match in prefix_matches:
            judgment = labels.get(match.anchor_id)
            if judgment is None:
                continue
            if match.directly_supported:
                if match.anchor_id not in first_direct_rank:
                    first_direct_rank[match.anchor_id] = hit.rank
                    rank_gains.append(_gain(judgment.label))
            if match.fully_supported:
                first_full_rank.setdefault(match.anchor_id, hit.rank)
        if hit.rank <= 10 and rank_gains:
            rank_gain = min(_MAX_GAIN, max(rank_gains))
            actual_dcg += rank_gain / math.log2(hit.rank + 1)

    ideal_gains = sorted(
        (_gain(judgment.label) for judgment in labels.values() if judgment.label > 0),
        reverse=True,
    )
    ndcg = _ndcg_metric(actual_dcg, ideal_gains)
    positive_anchors = {
        anchor_id for anchor_id, judgment in labels.items() if judgment.label == 2
    }
    first_positive_rank = min(
        (
            rank
            for anchor_id, rank in first_direct_rank.items()
            if anchor_id in positive_anchors
        ),
        default=None,
    )
    mrr = _reciprocal_rank(first_positive_rank, bool(positive_anchors))
    recall20 = _recall(
        positive_anchors,
        {anchor_id for anchor_id, rank in first_direct_rank.items() if rank <= 20},
    )
    recall50 = _recall(positive_anchors, set(first_direct_rank))
    group_coverage = _score_evidence_groups(
        family, labels, first_full_rank, empty_eligibility=empty_eligibility
    )
    return (
        RankingMetrics(ndcg, mrr, recall20, recall50, coverage),
        group_coverage,
        grade_counts,
    )


def _score_evidence_groups(
    family: QuestionFamily,
    labels: Mapping[str, EvidenceJudgment],
    first_full_rank: Mapping[str, int],
    *,
    empty_eligibility: bool,
) -> tuple[EvidenceGroupCoverage, ...]:
    eligible_groups: list[tuple[tuple[str, ...], ...]] = []
    groups_to_score = () if empty_eligibility else family.evidence_groups
    for group in groups_to_score:
        pieces: list[tuple[str, ...]] = []
        for alternatives in group.required_pieces:
            eligible_alternatives = tuple(
                anchor_id
                for anchor_id in alternatives
                if anchor_id in labels and labels[anchor_id].label == 2
            )
            if not eligible_alternatives:
                raise EvaluationScoringError(
                    f"required piece in {group.id} has no eligible label-2 anchor"
                )
            pieces.append(eligible_alternatives)
        eligible_groups.append(tuple(pieces))

    scores: list[EvidenceGroupCoverage] = []
    for cutoff in _CUTOFFS:
        supported = {
            anchor_id
            for anchor_id, rank in first_full_rank.items()
            if rank <= cutoff
        }
        total_pieces = sum(len(group) for group in eligible_groups)
        satisfied_pieces = sum(
            bool(supported.intersection(alternatives))
            for group in eligible_groups
            for alternatives in group
        )
        complete_groups = sum(
            all(supported.intersection(alternatives) for alternatives in group)
            for group in eligible_groups
        )
        scores.append(
            EvidenceGroupCoverage(
                cutoff=cutoff,
                required_pieces=_ratio(
                    float(satisfied_pieces), float(total_pieces)
                ),
                complete_groups=_ratio(
                    float(complete_groups), float(len(eligible_groups))
                ),
            )
        )
    return tuple(scores)


def _best_direct_label(
    matches: Sequence[SourceAnchorMatch], labels: Mapping[str, EvidenceJudgment]
) -> int | None:
    matched_labels = [
        labels[match.anchor_id].label
        for match in matches
        if match.anchor_id in labels and match.directly_supported
    ]
    return max(matched_labels) if matched_labels else None


def _grade_counts(labels: Iterable[int | None]) -> HitGradeCounts:
    values = tuple(labels)
    label_0 = sum(label == 0 for label in values)
    label_1 = sum(label == 1 for label in values)
    label_2 = sum(label == 2 for label in values)
    judged = label_0 + label_1 + label_2
    return HitGradeCounts(
        returned=len(values),
        judged=judged,
        unjudged=len(values) - judged,
        label_0=label_0,
        label_1=label_1,
        label_2=label_2,
    )


def _gain(label: int) -> int:
    return 2**label - 1


def _ndcg_metric(actual_dcg: float, ideal_gains: Sequence[int]) -> MetricValue:
    ideal_dcg = sum(
        gain / math.log2(rank + 1)
        for rank, gain in enumerate(ideal_gains[:10], start=1)
    )
    if actual_dcg > ideal_dcg + 1e-12:
        raise EvaluationScoringError("nDCG actual DCG exceeds ideal DCG")
    return _ratio(actual_dcg, ideal_dcg)


def _reciprocal_rank(rank: int | None, has_positive: bool) -> MetricValue:
    if not has_positive:
        return _ratio(0.0, 0.0)
    if rank is None or rank > 10:
        return _ratio(0.0, 1.0)
    return _ratio(1.0 / rank, 1.0)


def _recall(positives: set[str], retrieved: set[str]) -> MetricValue:
    numerator = len(positives.intersection(retrieved))
    return _ratio(float(numerator), float(len(positives)))


def _ratio(numerator: float, denominator: float) -> MetricValue:
    return MetricValue(
        value=numerator / denominator if denominator > 0 else None,
        numerator=numerator,
        denominator=denominator,
    )
