"""Development retrieval evaluation suite."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from research_platform.evaluation.calibration import (
    load_calibration,
)
from research_platform.evaluation.experiments import (
    DatasetIdentity,
    ExperimentOutcome,
    file_sha256,
)
from research_platform.evaluation.matching import SourceEvidenceRegion
from research_platform.evaluation.runner import EvaluationOptions, evaluate_calibration
from research_platform.evaluation.source_alignment import load_source_alignment
from research_platform.evaluation.suites.base import SuiteContext
from research_platform.ingestion.provenance import code_revision
from research_platform.search.application import create_phase2_runtime
from research_platform.search.contracts import RetrievalMode

_PROFILE_ID = re.compile(r"^sha256:[0-9a-f]{64}$")
_METRICS = (
    "ndcg_at_10",
    "direct_mrr_at_10",
    "judged_recall_at_20",
    "judged_recall_at_50",
    "judgment_coverage",
)


def _parse_datasets(value: str) -> tuple[tuple[Path, Path], ...]:
    """Parse comma-separated calibration/alignment path pairs."""
    if not value.strip():
        raise ValueError("datasets must contain at least one path pair")
    pairs: list[tuple[Path, Path]] = []
    for entry in value.split(","):
        parts = entry.strip().split(":")
        if len(parts) != 2 or any(not part.strip() for part in parts):
            raise ValueError("each dataset must be CALIBRATION_PATH:ALIGNMENT_PATH")
        pairs.append((Path(parts[0].strip()), Path(parts[1].strip())))
    return tuple(pairs)


def _profile_id(options: Mapping[str, str]) -> str:
    value = options.get("profile_id", "")
    if not _PROFILE_ID.fullmatch(value):
        raise ValueError(
            "profile_id must be sha256 followed by 64 lowercase hex digits"
        )
    return value


def _mode(options: Mapping[str, str]) -> RetrievalMode:
    value = options.get("mode", RetrievalMode.RERANKED.value)
    try:
        return RetrievalMode(value)
    except ValueError as exc:
        raise ValueError("mode must be lexical, dense, hybrid, or reranked") from exc


def _limit(options: Mapping[str, str]) -> int:
    try:
        limit = int(options.get("limit", "10"))
    except ValueError as exc:
        raise ValueError("limit must be an integer") from exc
    if limit < 1:
        raise ValueError("limit must be positive")
    return limit


class _Proxy:
    """Collect evidence regions while adapting the search executor."""

    def __init__(self, executor: Any, regions: dict[str, SourceEvidenceRegion]) -> None:
        self.executor = executor
        self.regions = regions

    async def search(self, request: Any) -> Any:
        from research_platform.evaluation.matching import regions_from_search_hits
        from research_platform.search.contracts import SearchOperation

        response = await self.executor.execute(request, request_id=str(uuid4()))
        if request.operation is SearchOperation.EVIDENCE_SEARCH:
            self.regions.update(regions_from_search_hits(response.hits))
        return response


def summarize(records: Sequence[Mapping[str, Any]]) -> dict[str, object]:
    """Compute the reference script's query macro means and metric counts."""
    summary: dict[str, object] = {"queries": len(records)}
    for group in ("paper", "evidence"):
        for metric in _METRICS:
            values = [
                record[group][metric]
                for record in records
                if record.get(group) is not None and record[group][metric] is not None
            ]
            summary[f"{group}_{metric}"] = sum(values) / len(values) if values else None
            summary[f"{group}_{metric}_queries"] = len(values)
    summary["failed_attempts"] = sum(record["failed_attempts"] for record in records)
    return summary


def _item_from_record(record: Any) -> dict[str, object]:
    score = record.score
    return {
        "item_id": f"{record.family_id}:{record.query_id}",
        "family_id": record.family_id,
        "query_id": record.query_id,
        "failed_attempts": sum(
            attempt.status == "failed" for attempt in record.attempts
        ),
        **{
            group: None
            if score is None
            else {
                metric: getattr(getattr(score, group), metric).value
                for metric in _METRICS
            }
            for group in ("paper", "evidence")
        },
    }


class RetrievalDevSuite:
    name = "retrieval-dev"

    def dataset(self, options: Mapping[str, str]) -> DatasetIdentity:
        pairs = _parse_datasets(options.get("datasets", ""))
        version = "+".join(calibration.stem for calibration, _ in pairs)
        digest = hashlib.sha256(
            "".join(file_sha256(path) for pair in pairs for path in pair).encode(
                "ascii"
            )
        ).hexdigest()
        return DatasetIdentity("retrieval-development", version, digest)

    async def run(self, context: SuiteContext) -> ExperimentOutcome:
        pairs = _parse_datasets(context.options.get("datasets", ""))
        profile_id = _profile_id(context.options)
        mode = _mode(context.options)
        limit = _limit(context.options)
        runtime = await create_phase2_runtime(context.settings)
        records: list[dict[str, Any]] = []
        try:
            search = runtime.api_services.search
            for calibration_path, alignment_path in pairs:
                dataset = load_calibration(calibration_path)
                alignment = load_source_alignment(alignment_path, dataset)
                eligible: dict[str, set[str]] = {}
                for family in dataset.families:
                    availability = await search._eligibility.read(
                        dataset.snapshot_id, filters=family.filters
                    )
                    for query in family.queries:
                        eligible[query.id] = set(availability.paper_metadata)
                regions: dict[str, SourceEvidenceRegion] = {}
                results = await evaluate_calibration(
                    _Proxy(search, regions),
                    dataset,
                    alignment,
                    options=EvaluationOptions(
                        retrieval_profile_id=profile_id,
                        mode=mode,
                        calibration_sha256=file_sha256(calibration_path),
                        source_alignment_sha256=file_sha256(alignment_path),
                        code_revision=code_revision(),
                        limit=limit,
                        experiment_id=str(context.experiment_id),
                    ),
                    regions_by_evidence_id=regions,
                    eligible_paper_ids_by_query=eligible,
                )
                for record in results:
                    item = _item_from_record(record)
                    context.writer.append(item)
                    item["family"] = item.pop("family_id")
                    item["query"] = item.pop("query_id")
                    records.append(item)
        finally:
            await runtime.close()

        metrics = cast(dict[str, float | int | None], summarize(records))
        failed_attempts = cast(int, metrics["failed_attempts"])
        return ExperimentOutcome(
            configuration_id=profile_id,
            configuration={
                "retrieval_profile_id": profile_id,
                "mode": mode.value,
                "limit": limit,
            },
            versions={"retrieval_profile": profile_id},
            random_seed=None,
            metrics=metrics,
            failures={"failed_attempts": failed_attempts} if failed_attempts else {},
            item_count=context.writer.count,
        )
