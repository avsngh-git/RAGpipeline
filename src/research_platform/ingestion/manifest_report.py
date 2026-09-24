"""Explainable, bounded diagnostics for human-reviewed discovery shortlists."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence

from research_platform.ingestion.discovery_repository import (
    DiscoveryRunSummary,
    ManifestCoverageReview,
    ManifestHeader,
    ManifestItem,
)

_SIGNAL_NAMES = (
    "older_paper_exception",
    "publication_year_in_range",
    "language_matches",
    "has_abstract",
)
_DECISIONS = ("include", "exclude", "undecided")


def build_manifest_review_report(
    header: ManifestHeader,
    run: DiscoveryRunSummary,
    items: Sequence[ManifestItem],
    coverage: Sequence[ManifestCoverageReview],
) -> dict[str, object]:
    """Summarize reviewer yield and selection signals without estimating recall."""
    decision_counts: Counter[str] = Counter(item.decision for item in items)
    reviewed_count = decision_counts["include"] + decision_counts["exclude"]
    inclusion_share = (
        decision_counts["include"] / reviewed_count if reviewed_count else None
    )

    query_counts: dict[int, Counter[str]] = defaultdict(Counter)
    signal_counts: dict[str, dict[str, Counter[str]]] = {
        signal: {"true": Counter(), "false": Counter(), "unknown": Counter()}
        for signal in _SIGNAL_NAMES
    }
    year_counts: Counter[str] = Counter()
    type_counts: Counter[str] = Counter()
    question_counts: dict[str, Counter[str]] = defaultdict(Counter)
    missing_metadata: Counter[str] = Counter()

    for item in items:
        for origin in item.origins:
            query_index = origin.get("query_index")
            if isinstance(query_index, int) and not isinstance(query_index, bool):
                query_counts[query_index][item.decision] += 1
        for signal in _SIGNAL_NAMES:
            value = item.selection_signals.get(signal)
            group = str(value).lower() if isinstance(value, bool) else "unknown"
            signal_counts[signal][group][item.decision] += 1
        year_counts[
            str(
                item.publication_year
                if item.publication_year is not None
                else "unknown"
            )
        ] += 1
        type_counts[item.work_type or "unknown"] += 1
        if item.title is None:
            missing_metadata["title"] += 1
        if item.publication_year is None:
            missing_metadata["publication_year"] += 1
        if item.language is None:
            missing_metadata["language"] += 1
        for question in item.coverage_questions:
            question_counts[question][item.decision] += 1

    configured_limits = run.configuration.get("limits")
    max_pages = (
        configured_limits.get("max_pages_per_query")
        if isinstance(configured_limits, Mapping)
        else None
    )
    query_reports: list[dict[str, object]] = []
    truncated_queries: list[str] = []
    for query in run.queries:
        counts = query_counts[query.query_index]
        if query.truncated:
            truncated_queries.append(query.query_text)
        origin_reviewed = counts["include"] + counts["exclude"]
        query_reports.append(
            {
                "query_index": query.query_index,
                "query": query.query_text,
                "source_kind": query.source_kind,
                "pages_fetched": query.page_count,
                "provider_result_count": query.result_count,
                "truncated_at_page_limit": query.truncated,
                "shortlist_candidate_origins": sum(counts.values()),
                "reviewed_candidate_origins": origin_reviewed,
                "included_candidate_origins": counts["include"],
                "excluded_candidate_origins": counts["exclude"],
                "undecided_candidate_origins": counts["undecided"],
                "reviewer_inclusion_share": (
                    counts["include"] / origin_reviewed if origin_reviewed else None
                ),
            }
        )

    return {
        "schema_version": 1,
        "manifest": {
            "id": str(header.id),
            "run_id": str(header.run_id),
            "version": header.version,
            "status": header.status,
            "discovery_configuration_id": header.configuration_id,
            "code_revision": header.code_revision,
        },
        "discovery": {
            "status": run.status,
            "request_attempts": run.request_count,
            "request_limit": _configured_limit(run.configuration, "max_total_requests"),
            "unique_discovered_candidates": run.result_count,
            "api_cost_usd": run.api_cost_usd,
            "maximum_pages_per_query": max_pages,
            "queries": query_reports,
            "truncated_queries": truncated_queries,
        },
        "review_yield": {
            "candidate_count": len(items),
            "included": decision_counts["include"],
            "excluded": decision_counts["exclude"],
            "undecided": decision_counts["undecided"],
            "reviewed": reviewed_count,
            "reviewer_inclusion_share": inclusion_share,
            "interpretation": (
                "Share of reviewed shortlist candidates retained by the reviewer; "
                "this is not corpus recall."
            ),
        },
        "coverage_review": [
            {
                "question": item.question,
                "status": item.status,
                "reviewer_note": item.reviewer_note,
                "included_candidates_tagged": question_counts[item.question]["include"],
                "excluded_candidates_tagged": question_counts[item.question]["exclude"],
                "undecided_candidates_tagged": question_counts[item.question][
                    "undecided"
                ],
            }
            for item in coverage
        ],
        "review_decisions_by_selection_signal": {
            signal: {
                value: {
                    decision: signal_counts[signal][value][decision]
                    for decision in _DECISIONS
                }
                for value in ("true", "false", "unknown")
            }
            for signal in _SIGNAL_NAMES
        },
        "candidate_metadata_distribution": {
            "publication_year": dict(sorted(year_counts.items())),
            "work_type": dict(sorted(type_counts.items())),
            "missing_fields": dict(sorted(missing_metadata.items())),
        },
        "limitations": [
            "The reviewer inclusion share describes only this reviewed shortlist; it does not estimate recall over all OpenAlex works.",
            "Per-query origin counts can count one paper more than once when it matched multiple queries.",
            "The shortlist is bounded by configured page and request limits; truncated queries are listed above.",
            "Coverage statuses and inclusion/exclusion decisions are human judgments, not independent labels.",
        ],
    }


def _configured_limit(configuration: Mapping[str, object], name: str) -> int | None:
    limits = configuration.get("limits")
    if not isinstance(limits, Mapping):
        return None
    value = limits.get(name)
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return None
