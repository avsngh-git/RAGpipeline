"""Coverage-only judged/unjudged accounting for pooled held-out candidates.

Everything here reports how many returned results carry a reviewed judgment. No
metric values, labels, question text or rank-with-label pairs leave this module;
unjudged candidates are exposed only as unordered identifier sets so that missing
review can be closed blind to profile and rank.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from research_platform.evaluation.calibration import CalibrationDataset
from research_platform.evaluation.matching import (
    SourceEvidenceRegion,
    match_evidence_hit,
)
from research_platform.evaluation.scoring import (
    _evidence_labels,
    _paper_labels,
    _resolve_eligible_papers,
)
from research_platform.evaluation.source_alignment import SourceAlignmentDataset
from research_platform.search.contracts import EvidenceHit, PaperHit

COVERAGE_CUTOFFS = (10, 20)
COVERAGE_KINDS = ("paper", "evidence")
PAPER_POOL_DEPTH = 20
EVIDENCE_POOL_DEPTH = 50
PAPER_REVIEW_CAP = 80
EVIDENCE_REVIEW_CAP = 200


class CoverageError(ValueError):
    """Coverage inputs or a recorded coverage table are inconsistent."""


@dataclass(frozen=True)
class CoverageRequirements:
    """ADR 0014 pre-freeze judgment coverage thresholds."""

    minimum_micro_at_10: float = 0.95
    minimum_micro_at_20: float = 0.90
    minimum_selected_family_at_10: float = 0.80

    def to_dict(self) -> dict[str, float]:
        return {
            "minimum_micro_at_10": self.minimum_micro_at_10,
            "minimum_micro_at_20": self.minimum_micro_at_20,
            "minimum_selected_family_at_10": self.minimum_selected_family_at_10,
        }

    def micro_minimum(self, cutoff: int) -> float:
        return self.minimum_micro_at_10 if cutoff == 10 else self.minimum_micro_at_20


DEFAULT_REQUIREMENTS = CoverageRequirements()


@dataclass(frozen=True)
class JudgedCount:
    """Judged and unjudged results in one ranked prefix."""

    judged: int = 0
    unjudged: int = 0

    @property
    def total(self) -> int:
        return self.judged + self.unjudged

    @property
    def fraction(self) -> float | None:
        return self.judged / self.total if self.total else None

    def __add__(self, other: JudgedCount) -> JudgedCount:
        return JudgedCount(self.judged + other.judged, self.unjudged + other.unjudged)


def count_key(kind: str, cutoff: int) -> str:
    return f"{kind}_top{cutoff}"


@dataclass(frozen=True)
class QueryCoverage:
    """Judged counts and pooled candidate identifiers for one query result pair."""

    family_id: str
    query_id: str
    counts: Mapping[str, JudgedCount]
    pooled_paper_ids: frozenset[str]
    pooled_evidence_ids: frozenset[str]
    unjudged_paper_ids: frozenset[str]
    unjudged_evidence_ids: frozenset[str]


def query_coverage(
    dataset: CalibrationDataset,
    *,
    family_id: str,
    query_id: str,
    paper_hits: Sequence[PaperHit],
    evidence_hits: Sequence[EvidenceHit],
    regions_by_evidence_id: Mapping[str, SourceEvidenceRegion],
    alignments: SourceAlignmentDataset,
    eligible_paper_ids: Collection[str] | None = None,
) -> QueryCoverage:
    """Count judged results using the scorer's own notion of a judged result.

    A paper is judged when its family carries a paper judgment; an evidence result
    is judged when it directly supports an anchor that has an evidence judgment.
    """
    family = next((item for item in dataset.families if item.id == family_id), None)
    if family is None:
        raise CoverageError("unknown family")
    if query_id not in {query.id for query in family.queries}:
        raise CoverageError("query_id does not belong to family_id")
    eligible = _resolve_eligible_papers(family, eligible_paper_ids)
    paper_labels = _paper_labels(family, eligible)
    evidence_labels = _evidence_labels(family, eligible)

    counts: dict[str, JudgedCount] = {}
    pooled_papers: set[str] = set()
    unjudged_papers: set[str] = set()
    for cutoff in COVERAGE_CUTOFFS:
        judged = unjudged = 0
        for paper_hit in paper_hits:
            if paper_hit.rank > cutoff:
                continue
            if paper_hit.paper_id in paper_labels:
                judged += 1
            else:
                unjudged += 1
        counts[count_key("paper", cutoff)] = JudgedCount(judged, unjudged)
    for paper_hit in paper_hits:
        if paper_hit.rank <= PAPER_POOL_DEPTH:
            pooled_papers.add(paper_hit.paper_id)
            if paper_hit.paper_id not in paper_labels:
                unjudged_papers.add(paper_hit.paper_id)

    evidence_judged: list[tuple[int, bool]] = []
    pooled_evidence: set[str] = set()
    unjudged_evidence: set[str] = set()
    for evidence_hit in evidence_hits:
        if evidence_hit.rank > EVIDENCE_POOL_DEPTH:
            continue
        matches = match_evidence_hit(evidence_hit, regions_by_evidence_id, alignments)
        is_judged = any(
            match.directly_supported and match.anchor_id in evidence_labels
            for match in matches
        )
        evidence_judged.append((evidence_hit.rank, is_judged))
        pooled_evidence.add(evidence_hit.chunk_id)
        if not is_judged:
            unjudged_evidence.add(evidence_hit.chunk_id)
    for cutoff in COVERAGE_CUTOFFS:
        flags = [flag for rank, flag in evidence_judged if rank <= cutoff]
        counts[count_key("evidence", cutoff)] = JudgedCount(
            sum(flags), len(flags) - sum(flags)
        )
    return QueryCoverage(
        family_id=family_id,
        query_id=query_id,
        counts=counts,
        pooled_paper_ids=frozenset(pooled_papers),
        pooled_evidence_ids=frozenset(pooled_evidence),
        unjudged_paper_ids=frozenset(unjudged_papers),
        unjudged_evidence_ids=frozenset(unjudged_evidence),
    )


@dataclass(frozen=True)
class ProfileCoverage:
    """Micro judged counts per kind and cutoff for one profile."""

    name: str
    counts: Mapping[str, JudgedCount]
    family_counts: Mapping[str, Mapping[str, JudgedCount]]


def profile_coverage(name: str, queries: Iterable[QueryCoverage]) -> ProfileCoverage:
    totals = {
        count_key(kind, cutoff): JudgedCount()
        for kind in COVERAGE_KINDS
        for cutoff in COVERAGE_CUTOFFS
    }
    by_family: dict[str, dict[str, JudgedCount]] = {}
    for query in queries:
        family_totals = by_family.setdefault(query.family_id, {})
        for key in totals:
            value = query.counts.get(key, JudgedCount())
            totals[key] = totals[key] + value
            family_totals[key] = family_totals.get(key, JudgedCount()) + value
    return ProfileCoverage(name=name, counts=totals, family_counts=by_family)


@dataclass(frozen=True)
class CoverageReport:
    """Coverage by profile plus the selected profile's per-family fractions."""

    profiles: Mapping[str, ProfileCoverage]
    selected_profile: str
    family_order: tuple[str, ...]
    pool_paper_sizes: Mapping[str, int]
    pool_evidence_sizes: Mapping[str, int]
    unjudged_paper_ids: Mapping[str, frozenset[str]]
    unjudged_evidence_ids: Mapping[str, frozenset[str]]
    requirements: CoverageRequirements = DEFAULT_REQUIREMENTS

    def selected_family_fraction(self, family_id: str, kind: str) -> float | None:
        counts = self.profiles[self.selected_profile].family_counts.get(family_id, {})
        return counts.get(count_key(kind, 10), JudgedCount()).fraction

    def family_minimum(self, kind: str) -> float | None:
        values = [
            fraction
            for family_id in self.family_order
            if (fraction := self.selected_family_fraction(family_id, kind)) is not None
        ]
        return min(values) if values else None


def build_coverage_report(
    dataset: CalibrationDataset,
    queries_by_profile: Mapping[str, Sequence[QueryCoverage]],
    *,
    selected_profile: str,
    requirements: CoverageRequirements = DEFAULT_REQUIREMENTS,
) -> CoverageReport:
    if selected_profile not in queries_by_profile:
        raise CoverageError("selected profile has no coverage records")
    family_order = tuple(family.id for family in dataset.families)
    profiles = {
        name: profile_coverage(name, queries)
        for name, queries in queries_by_profile.items()
    }
    papers: dict[str, set[str]] = {family_id: set() for family_id in family_order}
    evidence: dict[str, set[str]] = {family_id: set() for family_id in family_order}
    unjudged_papers: dict[str, set[str]] = {
        family_id: set() for family_id in family_order
    }
    unjudged_evidence: dict[str, set[str]] = {
        family_id: set() for family_id in family_order
    }
    for queries in queries_by_profile.values():
        for query in queries:
            papers[query.family_id].update(query.pooled_paper_ids)
            evidence[query.family_id].update(query.pooled_evidence_ids)
            unjudged_papers[query.family_id].update(query.unjudged_paper_ids)
            unjudged_evidence[query.family_id].update(query.unjudged_evidence_ids)
    return CoverageReport(
        profiles=profiles,
        selected_profile=selected_profile,
        family_order=family_order,
        pool_paper_sizes={key: len(value) for key, value in papers.items()},
        pool_evidence_sizes={key: len(value) for key, value in evidence.items()},
        unjudged_paper_ids={k: frozenset(v) for k, v in unjudged_papers.items()},
        unjudged_evidence_ids={k: frozenset(v) for k, v in unjudged_evidence.items()},
        requirements=requirements,
    )


@dataclass(frozen=True)
class CoverageVerdict:
    passed: bool
    failures: tuple[str, ...]


def _check(
    profile_counts: Mapping[str, Mapping[str, JudgedCount]],
    selected_profile: str,
    selected_family_minimum: Mapping[str, float | None],
    requirements: CoverageRequirements,
) -> CoverageVerdict:
    failures: list[str] = []
    for name, counts in profile_counts.items():
        for kind in COVERAGE_KINDS:
            for cutoff in COVERAGE_CUTOFFS:
                fraction = counts.get(count_key(kind, cutoff), JudgedCount()).fraction
                minimum = requirements.micro_minimum(cutoff)
                if fraction is None:
                    failures.append(f"{name} {kind} top {cutoff}: no results")
                elif fraction < minimum:
                    failures.append(
                        f"{name} {kind} top {cutoff}: judged {fraction:.3f}"
                        f" below {minimum:.2f}"
                    )
    for kind in COVERAGE_KINDS:
        family_minimum = selected_family_minimum.get(kind)
        if (
            family_minimum is not None
            and family_minimum < requirements.minimum_selected_family_at_10
        ):
            failures.append(
                f"{selected_profile} {kind} family top 10: lowest judged"
                f" {family_minimum:.3f} below"
                f" {requirements.minimum_selected_family_at_10:.2f}"
            )
    return CoverageVerdict(passed=not failures, failures=tuple(failures))


def evaluate_coverage(report: CoverageReport) -> CoverageVerdict:
    return _check(
        {name: profile.counts for name, profile in report.profiles.items()},
        report.selected_profile,
        {kind: report.family_minimum(kind) for kind in COVERAGE_KINDS},
        report.requirements,
    )


def render_coverage_lines(report: CoverageReport) -> list[str]:
    """Render counts and fractions only, with opaque family ordinals."""
    lines = ["Judgment coverage (judged/unjudged counts only)"]
    for name, profile in report.profiles.items():
        parts = []
        for kind in COVERAGE_KINDS:
            for cutoff in COVERAGE_CUTOFFS:
                value = profile.counts[count_key(kind, cutoff)]
                fraction = value.fraction
                shown = f"{fraction:.3f}" if fraction is not None else "n/a"
                parts.append(
                    f"{kind}@{cutoff} {value.judged}/{value.unjudged} ({shown})"
                )
        lines.append(f"  {name}: " + "; ".join(parts))
    lines.append(f"Selected profile ({report.selected_profile}) per-family top-10:")
    for ordinal, family_id in enumerate(report.family_order, start=1):
        cells = []
        for kind in COVERAGE_KINDS:
            fraction = report.selected_family_fraction(family_id, kind)
            cells.append(
                f"{kind} {fraction:.3f}" if fraction is not None else f"{kind} n/a"
            )
        lines.append(f"  family {ordinal:02d}: " + "; ".join(cells))
    max_papers = max(report.pool_paper_sizes.values(), default=0)
    max_evidence = max(report.pool_evidence_sizes.values(), default=0)
    lines.append(
        f"Pooled unique candidates per family: max {max_papers} papers"
        f" (cap {PAPER_REVIEW_CAP}), max {max_evidence} evidence"
        f" (cap {EVIDENCE_REVIEW_CAP})"
    )
    verdict = evaluate_coverage(report)
    lines.append("Coverage requirements: " + ("MET" if verdict.passed else "NOT MET"))
    lines.extend(f"  - {failure}" for failure in verdict.failures)
    return lines


def coverage_table(report: CoverageReport) -> dict[str, Any]:
    """Aggregate, publication-safe table for the freeze manifest."""
    profiles: dict[str, dict[str, int]] = {}
    for name, profile in report.profiles.items():
        row: dict[str, int] = {}
        for kind in COVERAGE_KINDS:
            for cutoff in COVERAGE_CUTOFFS:
                value = profile.counts[count_key(kind, cutoff)]
                row[f"{count_key(kind, cutoff)}_judged"] = value.judged
                row[f"{count_key(kind, cutoff)}_unjudged"] = value.unjudged
        profiles[name] = row
    max_papers = max(report.pool_paper_sizes.values(), default=0)
    max_evidence = max(report.pool_evidence_sizes.values(), default=0)
    minimum = {
        kind: floor
        for kind in COVERAGE_KINDS
        if (floor := report.family_minimum(kind)) is not None
    }
    return {
        "selected_profile": report.selected_profile,
        "requirements": report.requirements.to_dict(),
        "profiles": profiles,
        "selected_family_minimum_top10": minimum,
        "pool": {
            "paper_depth": PAPER_POOL_DEPTH,
            "evidence_depth": EVIDENCE_POOL_DEPTH,
            "paper_cap": PAPER_REVIEW_CAP,
            "evidence_cap": EVIDENCE_REVIEW_CAP,
            "max_unique_papers_per_family": max_papers,
            "max_unique_evidence_per_family": max_evidence,
        },
        "passed": evaluate_coverage(report).passed,
    }


def check_recorded_coverage_table(
    table: Mapping[str, Any],
    requirements: CoverageRequirements = DEFAULT_REQUIREMENTS,
) -> CoverageVerdict:
    """Recompute the verdict from a table recorded in a freeze manifest."""
    try:
        recorded_requirements = dict(table["requirements"])
    except (KeyError, TypeError, ValueError) as error:
        raise CoverageError("recorded coverage table is malformed") from error
    if recorded_requirements != requirements.to_dict():
        raise CoverageError("recorded coverage requirements differ from ADR 0014")
    try:
        selected = str(table["selected_profile"])
        raw_profiles = table["profiles"]
        profile_counts: dict[str, dict[str, JudgedCount]] = {}
        for name, row in raw_profiles.items():
            profile_counts[name] = {
                count_key(kind, cutoff): JudgedCount(
                    int(row[f"{count_key(kind, cutoff)}_judged"]),
                    int(row[f"{count_key(kind, cutoff)}_unjudged"]),
                )
                for kind in COVERAGE_KINDS
                for cutoff in COVERAGE_CUTOFFS
            }
        minimum = {
            kind: float(value)
            for kind, value in dict(table["selected_family_minimum_top10"]).items()
        }
        recorded_pass = table["passed"]
    except (KeyError, TypeError, ValueError, AttributeError) as error:
        raise CoverageError("recorded coverage table is malformed") from error
    if selected not in profile_counts:
        raise CoverageError("recorded coverage table lacks the selected profile")
    verdict = _check(profile_counts, selected, minimum, requirements)
    if recorded_pass is not verdict.passed:
        raise CoverageError("recorded coverage verdict differs from its counts")
    return verdict
