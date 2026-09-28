"""Run the single frozen Phase 2 R8 held-out assessment.

Raw records are written only to a caller-supplied private directory. Console output
contains aggregate metrics and hashes, never query text, judgments, or item ranks.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import platform
import random
import statistics
import subprocess
import sys
import tempfile
import time
from collections.abc import Mapping, Sequence
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import tomllib

os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["TOKENIZERS_PARALLELISM"] = "false"

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
PRIVATE_ROOT = Path("/home/avsngh/Projects/RAGpipeline/local-reference/phase2-runs")
DEFAULT_DATASET = PRIVATE_ROOT / "r8-assessment-20260928/heldout-v12.toml"
DEFAULT_ALIGNMENT = PRIVATE_ROOT / "r8-assessment-20260928/source-alignment-v12.toml"
DEFAULT_OUTPUT = PRIVATE_ROOT / "r8-assessment-20260928/assessment-run-v1"
FREEZE_PATH = REPOSITORY_ROOT / "benchmarks/phase2/r8-freeze-v1.toml"


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _git(*arguments: str) -> str:
    return subprocess.check_output(
        ["git", *arguments], cwd=REPOSITORY_ROOT, text=True
    ).strip()


def _atomic_private_json(path: Path, value: object) -> str:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    payload = (
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode("utf-8")
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, path)
        os.unlink(temporary)
        path.chmod(0o600)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise
    return _sha256_file(path)


def _nearest_rank(values: Sequence[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(quantile * len(ordered)) - 1)]


def _mean(values: Sequence[float | None]) -> float | None:
    present = [value for value in values if value is not None]
    return statistics.mean(present) if present else None


def _metric(metric: Any) -> dict[str, float | None]:
    return {
        "value": metric.value,
        "numerator": metric.numerator,
        "denominator": metric.denominator,
    }


def _rank_metrics(metrics: Any) -> dict[str, object]:
    return {
        "ndcg_at_10": _metric(metrics.ndcg_at_10),
        "direct_mrr_at_10": _metric(metrics.direct_mrr_at_10),
        "judged_recall_at_20": _metric(metrics.judged_recall_at_20),
        "judged_recall_at_50": _metric(metrics.judged_recall_at_50),
        "judgment_coverage": _metric(metrics.judgment_coverage),
    }


def _load_freeze(
    dataset_path: Path, alignment_path: Path, variant_dir: Path, *, validate_only: bool
) -> tuple[dict[str, Any], Any, Any, dict[str, Any]]:
    from research_platform.evaluation.calibration import load_heldout_dataset
    from research_platform.evaluation.source_alignment import load_source_alignment

    raw_freeze = tomllib.loads(FREEZE_PATH.read_text(encoding="utf-8"))
    if (
        raw_freeze.get("schema_version") != 1
        or raw_freeze.get("freeze_id") != "phase2-r8-v1"
    ):
        raise ValueError("R8 freeze manifest is unsupported")
    expected_files = raw_freeze.get("sha256")
    if not isinstance(expected_files, dict):
        raise ValueError("R8 freeze manifest has no file digest map")
    paths = {
        "heldout_dataset": dataset_path,
        "source_alignment": alignment_path,
        "acceptance": REPOSITORY_ROOT / "benchmarks/phase2/acceptance-v10.toml",
        "selected_profile": REPOSITORY_ROOT
        / "benchmarks/phase2/frozen-profile-v9.toml",
        "active_profile": REPOSITORY_ROOT / "benchmarks/phase2/active-profile.toml",
        "bm25_profile": REPOSITORY_ROOT / "benchmarks/phase2/bm25-profile-v1.toml",
        "hybrid_profile": REPOSITORY_ROOT
        / "benchmarks/phase2/hybrid-e5-profile-v1.toml",
        "dense_index_configuration": REPOSITORY_ROOT
        / "benchmarks/phase2/e5-small-v2-filtered-index-v1.json",
        "fixed_profile": variant_dir / "dense-profile.json",
        "fixed_index_configuration": variant_dir / "index-configuration.json",
        "fixed_variant": variant_dir / "variant.json",
    }
    code_files = raw_freeze.get("code_sha256")
    if not isinstance(code_files, dict):
        raise ValueError("R8 freeze manifest has no code digest map")
    for name, value in {
        **paths,
        **{key: REPOSITORY_ROOT / key for key in code_files},
    }.items():
        expected = expected_files.get(name) if name in paths else code_files.get(name)
        if not isinstance(expected, str) or _sha256_file(value) != expected:
            raise ValueError(f"R8 frozen digest mismatch: {name}")

    if _git("status", "--porcelain", "--untracked-files=no"):
        raise ValueError("R8 assessment requires a clean tracked worktree")
    dataset = load_heldout_dataset(dataset_path)
    alignment = load_source_alignment(alignment_path, dataset)
    acceptance = tomllib.loads(paths["acceptance"].read_text(encoding="utf-8"))
    frozen_manifest = tomllib.loads(
        paths["selected_profile"].read_text(encoding="utf-8")
    )
    if raw_freeze.get("comparison_profiles") != frozen_manifest.get(
        "comparison_profiles"
    ):
        raise ValueError("comparison profile identities differ from the frozen profile")
    if dataset.dataset_kind != "held_out" or dataset.dataset_id != acceptance.get(
        "benchmark_split"
    ):
        raise ValueError("held-out dataset does not match the frozen acceptance split")
    expected = raw_freeze.get("dataset")
    if not isinstance(expected, dict):
        raise ValueError("R8 freeze dataset facts are missing")
    family_count = len(dataset.families)
    positive_families = sum(not family.unsupported for family in dataset.families)
    unsupported_families = sum(family.unsupported for family in dataset.families)
    positive_anchors = {
        judgment.source_anchor_id
        for family in dataset.families
        for judgment in family.evidence_judgments
        if judgment.label == 2
    }
    category_counts = {
        category: sum(category in family.categories for family in dataset.families)
        for category in sorted(
            {category for family in dataset.families for category in family.categories}
        )
    }
    if (
        family_count != expected.get("family_count")
        or positive_families != expected.get("positive_family_count")
        or unsupported_families != expected.get("unsupported_family_count")
        or len(positive_anchors) != expected.get("positive_anchor_count")
        or len(alignment.table_alignments) != expected.get("table_anchor_count")
        or len(alignment.text_alignments) != expected.get("text_anchor_count")
        or category_counts != expected.get("categories")
    ):
        raise ValueError("held-out dataset no longer matches its frozen sample facts")
    if validate_only:
        return raw_freeze, dataset, alignment, acceptance
    return raw_freeze, dataset, alignment, acceptance


@dataclass(frozen=True)
class _ProfileSpec:
    name: str
    profile: Any
    mode: Any
    executor: Any
    variant: str


class _DraftDenseSearch:
    """Expose the explicit evaluation-only path for the private draft variant."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    async def search_query(
        self, profile: Any, query: str, *, limit: int, filters: Any
    ) -> Any:
        return await self._inner.evaluate_query(
            profile, query, limit=limit, filters=filters
        )


class _EvaluationProxy:
    def __init__(
        self,
        spec: _ProfileSpec,
        *,
        deadline_seconds: float,
        regions: dict[str, Any],
        responses_by_query: dict[str, dict[str, Any]],
        query_id_by_hash: Mapping[str, str],
    ) -> None:
        self.spec = spec
        self.deadline_seconds = deadline_seconds
        self.regions = regions
        self.responses_by_query = responses_by_query
        self.query_id_by_hash = query_id_by_hash

    async def search(self, request: Any) -> Any:
        from research_platform.evaluation.matching import regions_from_search_hits
        from research_platform.evaluation.runner import SearchServiceFailure
        from research_platform.search.contracts import SearchOperation

        query_id = self.query_id_by_hash.get(
            _sha256_bytes(request.query.encode("utf-8"))
        )
        if query_id is None:
            raise SearchServiceFailure("validation")
        request_id = str(uuid4())
        try:
            response = await asyncio.wait_for(
                self.spec.executor.execute(request, request_id=request_id),
                timeout=self.deadline_seconds,
            )
        except TimeoutError:
            raise SearchServiceFailure("timeout") from None
        except (PermissionError, MemoryError):
            raise SearchServiceFailure("resource") from None
        except ValueError:
            raise SearchServiceFailure("validation") from None
        except OSError:
            raise SearchServiceFailure("transport") from None
        except Exception:
            raise SearchServiceFailure("backend") from None

        operation_key = request.operation.value
        self.responses_by_query.setdefault(query_id, {})[operation_key] = response
        if request.operation is SearchOperation.EVIDENCE_SEARCH:
            self.regions.update(regions_from_search_hits(response.hits))
        return response


def _prepare_profiles(
    runtime: Any,
    frozen_path: Path,
    manifest_dir: Path,
    variant_dir: Path,
) -> tuple[list[_ProfileSpec], Any]:
    from research_platform.ingestion.evidence_repository import EvidenceRepository
    from research_platform.ingestion.indexing import (
        IndexConfiguration,
        IndexRepository,
        QdrantIndex,
    )
    from research_platform.search.application import (
        Phase2SearchExecutor,
        SnapshotEligibilityReader,
    )
    from research_platform.search.contracts import RetrievalMode
    from research_platform.search.dense_search import SnapshotDenseSearch
    from research_platform.search.profile_manifest import (
        load_frozen_profile,
        load_retrieval_profile_manifest,
    )
    from research_platform.search.profiles import RetrievalProfile

    frozen = load_frozen_profile(frozen_path)
    hybrid = load_retrieval_profile_manifest(manifest_dir / "hybrid-e5-profile-v1.toml")
    bm25 = load_retrieval_profile_manifest(manifest_dir / "bm25-profile-v1.toml")
    dense = replace(
        hybrid,
        lexical_index=None,
        fusion=None,
        candidate_limits=replace(
            hybrid.candidate_limits,
            lexical_top_k=None,
            dense_top_k=50,
            fused_top_k=None,
            rerank_top_k=None,
        ),
    )
    profiles = {
        "bm25_lexical": (bm25, RetrievalMode.LEXICAL),
        "dense_e5": (dense, RetrievalMode.DENSE),
        "hybrid_e5": (hybrid, RetrievalMode.HYBRID),
        "reranked_minilm_hybrid": (frozen, RetrievalMode.RERANKED),
    }
    expected = tomllib.loads(frozen_path.read_text(encoding="utf-8"))[
        "comparison_profiles"
    ]
    for name, (profile, _mode) in profiles.items():
        if profile.profile_id != expected.get(name):
            raise ValueError("a frozen comparison profile identity changed")

    executor = runtime.api_services.search
    registered_modes = executor._modes
    specs: list[_ProfileSpec] = []
    for name, (profile, mode) in profiles.items():
        if (
            profile.profile_id not in registered_modes
            or registered_modes[profile.profile_id] is not mode
        ):
            raise ValueError("runtime profile registration differs from the freeze")
        specs.append(_ProfileSpec(name, profile, mode, executor, "accepted"))

    fixed_profile = RetrievalProfile.from_dict(
        json.loads((variant_dir / "dense-profile.json").read_text(encoding="utf-8"))
    )
    fixed_config = IndexConfiguration.from_dict(
        json.loads(
            (variant_dir / "index-configuration.json").read_text(encoding="utf-8")
        )
    )
    if (
        fixed_profile.profile_id != expected.get("fixed_window_dense_e5")
        or fixed_profile.dense_index is None
        or fixed_profile.dense_index.index_configuration_id
        != fixed_config.configuration_id
    ):
        raise ValueError("fixed-window profile or index differs from its freeze")
    repository = IndexRepository(runtime.pool)
    fixed_dense = SnapshotDenseSearch(
        repository,
        QdrantIndex(fixed_config, runtime.http),
        query_embedder=executor._dense._query_embedder,
        evidence_hydrator=repository,
    )
    fixed_executor = Phase2SearchExecutor(
        pool=runtime.pool,
        index_configuration=fixed_config,
        repository=repository,
        eligibility_reader=SnapshotEligibilityReader(runtime.pool),
        profiles_by_id={fixed_profile.profile_id: fixed_profile},
        modes_by_profile_id={fixed_profile.profile_id: RetrievalMode.DENSE},
        lexical_evidence={},
        lexical_papers={},
        hybrid_profile=hybrid,
        hybrid_search=executor._hybrid,
        dense_search=_DraftDenseSearch(fixed_dense),
        reranker=runtime.reranker,
        evidence_repository=EvidenceRepository(runtime.pool),
    )
    specs.append(
        _ProfileSpec(
            "fixed_window_dense_e5",
            fixed_profile,
            RetrievalMode.DENSE,
            fixed_executor,
            "fixed-window",
        )
    )
    return specs, fixed_profile


def _family_aggregates(
    dataset: Any,
    records: Sequence[Any],
    responses_by_profile_query: Mapping[str, Mapping[str, Mapping[str, Any]]],
    regions_by_profile: Mapping[str, Mapping[str, Any]],
    alignments_by_profile: Mapping[str, Any],
    eligible_by_profile_query: Mapping[str, Mapping[str, set[str]]],
) -> dict[str, dict[str, dict[str, Any]]]:
    from research_platform.evaluation.matching import match_evidence_hits
    from research_platform.search.contracts import SearchOperation

    records_by_profile: dict[str, dict[str, list[Any]]] = {}
    # The run records carry a profile comparison ID, while scores carry the query/family.
    for record in records:
        profile_name = record.comparison_id
        if profile_name is None:
            raise ValueError("query run record has no comparison identity")
        records_by_profile.setdefault(profile_name, {}).setdefault(
            record.family_id, []
        ).append(record)

    output: dict[str, dict[str, dict[str, Any]]] = {}
    for profile_name, family_records in records_by_profile.items():
        profile_rows: dict[str, dict[str, Any]] = {}
        responses = responses_by_profile_query[profile_name]
        regions = regions_by_profile[profile_name]
        alignments = alignments_by_profile[profile_name]
        eligible = eligible_by_profile_query[profile_name]
        for family in dataset.families:
            query_records = family_records.get(family.id, [])
            if not query_records:
                continue
            row: dict[str, Any] = {}
            for group in ("paper", "evidence"):
                metric_names = (
                    "ndcg_at_10",
                    "direct_mrr_at_10",
                    "judged_recall_at_20",
                    "judged_recall_at_50",
                    "judgment_coverage",
                )
                for metric_name in metric_names:
                    values: list[float | None] = []
                    for query_record in query_records:
                        score = query_record.score
                        if score is not None:
                            values.append(
                                getattr(getattr(score, group), metric_name).value
                            )
                    row[f"{group}_{metric_name}"] = _mean(values)

            positive_anchors_by_query: dict[str, set[str]] = {}
            retrieved_at_10: set[str] = set()
            retrieved_at_50: set[str] = set()
            any_hit_at_10 = False
            for query_record in query_records:
                positive = {
                    judgment.source_anchor_id
                    for judgment in family.evidence_judgments
                    if judgment.label == 2
                    and judgment.source_anchor_id
                    and (
                        query_record.query_id not in eligible
                        or judgment.paper_id in eligible[query_record.query_id]
                    )
                }
                positive_anchors_by_query[query_record.query_id] = positive
                evidence_response = responses.get(query_record.query_id, {}).get(
                    SearchOperation.EVIDENCE_SEARCH.value
                )
                if evidence_response is None:
                    continue
                hits = evidence_response.hits
                matches10 = match_evidence_hits(
                    tuple(hit for hit in hits if hit.rank <= 10), regions, alignments
                )
                matches50 = match_evidence_hits(
                    tuple(hit for hit in hits if hit.rank <= 50), regions, alignments
                )
                anchors10 = {
                    match.anchor_id for match in matches10 if match.directly_supported
                }
                anchors50 = {
                    match.anchor_id for match in matches50 if match.directly_supported
                }
                retrieved_at_10.update(anchors10.intersection(positive))
                retrieved_at_50.update(anchors50.intersection(positive))
                any_hit_at_10 = any_hit_at_10 or bool(anchors10.intersection(positive))
            family_positive_anchors = (
                set().union(*positive_anchors_by_query.values())
                if positive_anchors_by_query
                else set()
            )
            row["source_anchor_recall_at_10"] = (
                len(retrieved_at_10) / len(family_positive_anchors)
                if family_positive_anchors
                else None
            )
            row["source_anchor_recall_at_50"] = (
                len(retrieved_at_50) / len(family_positive_anchors)
                if family_positive_anchors
                else None
            )
            row["source_anchor_recall_at_10_numerator"] = len(retrieved_at_10)
            row["source_anchor_recall_at_10_denominator"] = len(family_positive_anchors)
            row["source_anchor_recall_at_50_numerator"] = len(retrieved_at_50)
            row["source_anchor_recall_at_50_denominator"] = len(family_positive_anchors)
            row["positive_source_anchor_count"] = len(family_positive_anchors)
            row["positive_source_family_hit_at_10"] = any_hit_at_10

            group_values: dict[int, dict[str, list[float | None]]] = {
                cutoff: {"pieces": [], "complete": []} for cutoff in (10, 20, 50)
            }
            for query_record in query_records:
                if query_record.score is None:
                    continue
                for value in query_record.score.evidence_group_coverage:
                    group_values[value.cutoff]["pieces"].append(
                        value.required_pieces.value
                    )
                    group_values[value.cutoff]["complete"].append(
                        value.complete_groups.value
                    )
            row["evidence_group_coverage"] = {
                str(cutoff): {
                    "required_pieces_macro": _mean(values["pieces"]),
                    "complete_groups_macro": _mean(values["complete"]),
                }
                for cutoff, values in group_values.items()
            }
            row["unsupported"] = family.unsupported
            profile_rows[family.id] = row
        output[profile_name] = profile_rows
    return output


def _profile_summary(rows: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    metric_names = (
        "paper_ndcg_at_10",
        "paper_direct_mrr_at_10",
        "paper_judged_recall_at_20",
        "paper_judged_recall_at_50",
        "paper_judgment_coverage",
        "evidence_ndcg_at_10",
        "evidence_direct_mrr_at_10",
        "evidence_judged_recall_at_20",
        "evidence_judged_recall_at_50",
        "evidence_judgment_coverage",
    )
    for name in metric_names:
        values = [row.get(name) for row in rows.values()]
        result[f"{name}_macro"] = _mean(values)
        result[f"{name}_scored_families"] = sum(value is not None for value in values)
    for cutoff in (10, 50):
        numerator = sum(
            int(row[f"source_anchor_recall_at_{cutoff}_numerator"])
            for row in rows.values()
        )
        denominator = sum(
            int(row[f"source_anchor_recall_at_{cutoff}_denominator"])
            for row in rows.values()
        )
        result[f"source_anchor_recall_at_{cutoff}_micro"] = (
            numerator / denominator if denominator else None
        )
        result[f"source_anchor_recall_at_{cutoff}_numerator"] = numerator
        result[f"source_anchor_recall_at_{cutoff}_denominator"] = denominator
    positive = [row for row in rows.values() if row["positive_source_anchor_count"] > 0]
    hit = sum(bool(row["positive_source_family_hit_at_10"]) for row in positive)
    result["positive_source_family_count"] = len(positive)
    result["positive_source_families_with_hit_at_10"] = hit
    result["positive_families_with_source_hit_at_10_fraction"] = (
        hit / len(positive) if positive else None
    )
    for cutoff in (10, 20, 50):
        pieces = [
            row["evidence_group_coverage"][str(cutoff)]["required_pieces_macro"]
            for row in rows.values()
        ]
        complete = [
            row["evidence_group_coverage"][str(cutoff)]["complete_groups_macro"]
            for row in rows.values()
        ]
        result[f"evidence_group_piece_coverage_at_{cutoff}_macro"] = _mean(pieces)
        result[f"evidence_group_complete_fraction_at_{cutoff}_macro"] = _mean(complete)
    return result


def _paired_bootstrap(
    family_rows: Mapping[str, Mapping[str, Mapping[str, Any]]],
    selected: str,
    baseline: str,
    metric_names: Sequence[str],
    *,
    seed: int,
    repetitions: int,
) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for metric_index, metric_name in enumerate(metric_names):
        pairs = [
            (
                family_rows[selected][family_id].get(metric_name),
                family_rows[baseline][family_id].get(metric_name),
            )
            for family_id in sorted(
                family_rows[selected].keys() & family_rows[baseline].keys()
            )
        ]
        pairs = [
            (float(left), float(right))
            for left, right in pairs
            if left is not None and right is not None
        ]
        if not pairs:
            output[metric_name] = {
                "n_families": 0,
                "mean_delta": None,
                "ci95_low": None,
                "ci95_high": None,
            }
            continue
        deltas = [left - right for left, right in pairs]
        rng = random.Random(seed + metric_index)
        draws = [
            statistics.mean(deltas[rng.randrange(len(deltas))] for _ in deltas)
            for _ in range(repetitions)
        ]
        output[metric_name] = {
            "n_families": len(pairs),
            "mean_delta": statistics.mean(deltas),
            "ci95_low": _nearest_rank(draws, 0.025),
            "ci95_high": _nearest_rank(draws, 0.975),
        }
    return output


@contextmanager
def _measure_model_loads(torch: Any) -> Any:
    from research_platform.ingestion.embeddings import _SentenceTransformerEmbedder
    from research_platform.search.reranker_models import (
        PinnedSentenceTransformersReranker,
    )

    measurements: dict[str, Any] = {}
    original_embedder = _SentenceTransformerEmbedder._ensure_model
    original_reranker = PinnedSentenceTransformersReranker._ensure_loaded
    device = "cuda:0"

    def timed_embedder(instance: Any) -> Any:
        was_loaded = getattr(instance, "_model", None) is not None
        started = time.perf_counter()
        before = torch.cuda.memory_allocated(device) if torch.cuda.is_available() else 0
        result = original_embedder(instance)
        if (
            not was_loaded
            and instance._profile.model == "intfloat/e5-small-v2"
            and "e5_model_load_ms" not in measurements
        ):
            if torch.cuda.is_available():
                torch.cuda.synchronize(device)
            measurements["e5_model_load_ms"] = (time.perf_counter() - started) * 1000
            after = (
                torch.cuda.memory_allocated(device) if torch.cuda.is_available() else 0
            )
            measurements["e5_allocated_delta_bytes"] = max(0, after - before)
        return result

    def timed_reranker(instance: Any) -> None:
        was_loaded = (
            getattr(instance, "_model", None) is not None
            and getattr(instance, "_tokenizer", None) is not None
        )
        started = time.perf_counter()
        before = torch.cuda.memory_allocated(device) if torch.cuda.is_available() else 0
        original_reranker(instance)
        if (
            not was_loaded
            and instance.identity.model == "cross-encoder/ms-marco-MiniLM-L6-v2"
            and "reranker_model_load_ms" not in measurements
        ):
            if torch.cuda.is_available():
                torch.cuda.synchronize(device)
            measurements["reranker_model_load_ms"] = (
                time.perf_counter() - started
            ) * 1000
            after = (
                torch.cuda.memory_allocated(device) if torch.cuda.is_available() else 0
            )
            measurements["reranker_allocated_delta_bytes"] = max(0, after - before)

    _SentenceTransformerEmbedder._ensure_model = timed_embedder
    PinnedSentenceTransformersReranker._ensure_loaded = timed_reranker
    try:
        yield measurements
    finally:
        _SentenceTransformerEmbedder._ensure_model = original_embedder
        PinnedSentenceTransformersReranker._ensure_loaded = original_reranker


def _hardware(torch: Any) -> dict[str, Any]:
    cuda_available = bool(torch.cuda.is_available())
    if cuda_available:
        device_name = torch.cuda.get_device_name(0)
        memory_bytes = int(torch.cuda.get_device_properties(0).total_memory)
    else:
        device_name = None
        memory_bytes = None
    ram_bytes = None
    if hasattr(os, "sysconf"):
        try:
            ram_bytes = int(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES"))
        except (OSError, ValueError):
            pass
    return {
        "platform_system": platform.system(),
        "platform_release": platform.release(),
        "machine_architecture": platform.machine(),
        "python_version": platform.python_version(),
        "logical_cpu_count": os.cpu_count() or 1,
        "ram_bytes": ram_bytes,
        "accelerator_name": device_name,
        "accelerator_memory_bytes": memory_bytes,
        "cuda_available": cuda_available,
    }


class _Ready:
    async def check(self) -> Any:
        from research_platform.services.readiness import ReadinessReport

        return ReadinessReport(dependencies={})


def _timing_cases(dataset: Any) -> list[dict[str, Any]]:
    from research_platform.search.contracts import SearchFilters, SearchOperation

    cases: list[dict[str, Any]] = []
    for family in dataset.families:
        for query in family.queries:
            for operation in (
                SearchOperation.PAPER_SEARCH,
                SearchOperation.EVIDENCE_SEARCH,
            ):
                cases.append(
                    {
                        "query": query.text,
                        "filters": family.filters,
                        "operation": operation.value,
                        "category": family.categories[0]
                        if family.categories
                        else "uncategorized",
                        "kind": "heldout_query",
                    }
                )
    seed_query = cases[0]["query"]
    for operation in (SearchOperation.PAPER_SEARCH, SearchOperation.EVIDENCE_SEARCH):
        cases.append(
            {
                "query": seed_query,
                "filters": SearchFilters(paper_ids=("W999999999999999999999999999",)),
                "operation": operation.value,
                "category": "empty-filter",
                "kind": "no_match_filter",
            }
        )
    return cases


async def _warm_timing(
    specs: Sequence[_ProfileSpec],
    dataset: Any,
    settings: Any,
    *,
    seed: int,
    sessions: int,
    requests_per_session: int,
    warmups_per_session: int,
    selected_profile: str,
    deadline_seconds: float,
) -> dict[str, Any]:
    import httpx

    from research_platform.api.app import create_app
    from research_platform.api.routes import Phase2APIServices

    results: dict[str, Any] = {}
    cases = _timing_cases(dataset)
    for profile_index, spec in enumerate(specs):
        profile_samples: list[dict[str, Any]] = []
        profile_sessions = sessions if spec.name == selected_profile else 1
        for session_index in range(profile_sessions):
            case_order = [
                cases[index % len(cases)]
                for index in range(warmups_per_session + requests_per_session)
            ]
            random.Random(seed + profile_index * 1009 + session_index).shuffle(
                case_order
            )
            app = create_app(
                settings,
                dependency_checker=_Ready(),
                api_services=Phase2APIServices(search=spec.executor),
            )
            transport = httpx.ASGITransport(app=app)
            async with app.router.lifespan_context(app):
                async with httpx.AsyncClient(
                    transport=transport,
                    base_url="http://phase2-r8.local",
                    timeout=deadline_seconds,
                ) as client:
                    for request_index, case in enumerate(case_order):
                        body = {
                            "query": case["query"],
                            "snapshot_id": str(spec.profile.snapshot.snapshot_id),
                            "retrieval_profile_id": spec.profile.profile_id,
                            "mode": spec.mode.value,
                            "filters": case["filters"].to_dict(),
                            "limit": 10,
                        }
                        endpoint = (
                            "/v1/search"
                            if case["operation"] == "paper_search"
                            else "/v1/evidence/search"
                        )
                        started = time.perf_counter()
                        status_code = 0
                        response_body: dict[str, Any] = {}
                        try:
                            response = await client.post(endpoint, json=body)
                            status_code = response.status_code
                            parsed = response.json()
                            if isinstance(parsed, dict):
                                response_body = parsed
                        except Exception:
                            response_body = {"request_error": True}
                        elapsed_ms = (time.perf_counter() - started) * 1000
                        if (
                            case["kind"] == "no_match_filter"
                            and response_body.get("eligible_count") != 0
                        ):
                            raise RuntimeError(
                                "frozen no-match timing case did not resolve to zero eligible records"
                            )
                        if request_index < warmups_per_session:
                            continue
                        effective_mode = response_body.get("effective_mode")
                        profile_samples.append(
                            {
                                "session": session_index,
                                "measured_index": request_index - warmups_per_session,
                                "operation": case["operation"],
                                "category": case["category"],
                                "case_kind": case["kind"],
                                "http_status": status_code,
                                "latency_ms": round(elapsed_ms, 3),
                                "effective_mode": effective_mode,
                                "fallback": isinstance(effective_mode, str)
                                and effective_mode != spec.mode.value,
                                "response_sha256": _sha256_bytes(response.content)
                                if status_code
                                else None,
                                "eligible_count": response_body.get("eligible_count"),
                                "result_status": response_body.get("result_status"),
                            }
                        )
        all_ms = [sample["latency_ms"] for sample in profile_samples]
        by_operation: dict[str, Any] = {}
        for operation in ("paper_search", "evidence_search"):
            values = [
                sample["latency_ms"]
                for sample in profile_samples
                if sample["operation"] == operation
            ]
            by_operation[operation] = {
                "samples": len(values),
                "median_ms": statistics.median(values) if values else None,
                "p95_nearest_rank_ms": _nearest_rank(values, 0.95),
            }
        results[spec.name] = {
            "samples": len(profile_samples),
            "sessions": profile_sessions,
            "warmups_per_session": warmups_per_session,
            "median_ms": statistics.median(all_ms) if all_ms else None,
            "p95_nearest_rank_ms": _nearest_rank(all_ms, 0.95),
            "by_operation": by_operation,
            "hard_failures": sum(
                sample["http_status"] != 200 for sample in profile_samples
            ),
            "fallbacks": sum(bool(sample["fallback"]) for sample in profile_samples),
            "samples_private": profile_samples,
        }
    return results


async def _run_assessment(
    dataset_path: Path,
    alignment_path: Path,
    output_dir: Path,
    variant_dir: Path,
    *,
    validate_only: bool,
) -> dict[str, Any]:
    sys.path.insert(0, str(REPOSITORY_ROOT / "src"))
    from research_platform.config import Settings
    from research_platform.evaluation.acceptance_report import (
        build_acceptance_gate_report,
        load_acceptance_config,
    )
    from research_platform.evaluation.runner import EvaluationOptions, evaluate_heldout
    from research_platform.search.application import create_phase2_runtime

    freeze, dataset, alignment, acceptance_raw = _load_freeze(
        dataset_path, alignment_path, variant_dir, validate_only=validate_only
    )
    if validate_only:
        return {
            "validation": "passed",
            "dataset_sha256": _sha256_file(dataset_path),
            "alignment_sha256": _sha256_file(alignment_path),
            "family_count": len(dataset.families),
            "aligned_table_anchor_count": len(alignment.table_alignments),
            "aligned_text_anchor_count": len(alignment.text_alignments),
        }

    for name in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
        os.environ[name] = "4"
    os.environ["HF_HOME"] = "/tmp/phase1-embedding-hf-cache"
    os.environ["HF_HUB_CACHE"] = "/tmp/phase1-embedding-hf-cache/hub"
    import torch

    torch.set_num_threads(4)
    password = os.environ.get("P2_EVAL_POSTGRES_PASSWORD")
    if not password:
        password = subprocess.check_output(
            [
                "docker",
                "exec",
                "p2_eval_20260927-postgres-1",
                "sh",
                "-c",
                'printf "%s" "$POSTGRES_PASSWORD"',
            ],
            text=True,
        ).strip()
    from urllib.parse import quote

    settings = Settings(
        environment="test",
        log_level="WARNING",
        database_url=(
            "postgresql://research_test:"
            + quote(password, safe="")
            + "@127.0.0.1:25432/research_test"
        ),
        qdrant_url="http://127.0.0.1:26333",
        evidence_access_profile="trusted_private_local",
        lexical_index_root=Path(
            "/home/avsngh/Projects/RAGpipeline/local-reference/phase2-indexes"
        ),
        model_device="auto",
        reranker_cache_dir=Path("/tmp/phase2-reranker-hf-cache"),
    )
    if torch.cuda.is_available():
        torch.cuda.reset_peak_memory_stats(0)

    manifest_dir = REPOSITORY_ROOT / "benchmarks/phase2"
    frozen_path = manifest_dir / "frozen-profile-v9.toml"
    code_revision = _git("rev-parse", "HEAD")
    hardware = _hardware(torch)
    if not output_dir.is_dir():
        raise ValueError("private output directory was not created exclusively")
    output_dir.chmod(0o700)
    assessment_started_at = (
        datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    )
    with _measure_model_loads(torch) as model_loads:
        runtime_started = time.perf_counter()
        runtime = await create_phase2_runtime(settings, frozen_profile_path=frozen_path)
        runtime_startup_ms = (time.perf_counter() - runtime_started) * 1000
        try:
            specs, fixed_profile = _prepare_profiles(
                runtime,
                frozen_path,
                manifest_dir,
                variant_dir,
            )
            names = [spec.name for spec in specs]
            expected_names = [
                "bm25_lexical",
                "dense_e5",
                "hybrid_e5",
                "reranked_minilm_hybrid",
                "fixed_window_dense_e5",
            ]
            if names != expected_names:
                raise ValueError(
                    "comparison profile set or order differs from the freeze"
                )
            query_hash_to_id: dict[str, str] = {}
            for family in dataset.families:
                for query in family.queries:
                    query_hash = _sha256_bytes(query.text.encode("utf-8"))
                    if query_hash in query_hash_to_id:
                        raise ValueError("held-out query identities are not unique")
                    query_hash_to_id[query_hash] = query.id

            all_records: list[Any] = []
            family_rows_by_profile: dict[str, dict[str, dict[str, Any]]] = {}
            responses_by_profile_query: dict[str, dict[str, dict[str, Any]]] = {}
            regions_by_profile: dict[str, dict[str, Any]] = {}
            alignments_by_profile: dict[str, Any] = {}
            eligible_by_profile_query: dict[str, dict[str, set[str]]] = {}
            profile_failures: dict[str, dict[str, int]] = {}
            for spec in specs:
                if spec.variant == "fixed-window":
                    run_dataset = replace(
                        dataset, snapshot_id=fixed_profile.snapshot.snapshot_id
                    )
                    run_alignment = replace(
                        alignment, snapshot_id=fixed_profile.snapshot.snapshot_id
                    )
                else:
                    run_dataset = dataset
                    run_alignment = alignment
                eligible: dict[str, set[str]] = {}
                for family in run_dataset.families:
                    availability = await spec.executor._eligibility.read(
                        run_dataset.snapshot_id, filters=family.filters
                    )
                    for query in family.queries:
                        eligible[query.id] = set(availability.paper_metadata)
                regions: dict[str, Any] = {}
                responses: dict[str, dict[str, Any]] = {}
                proxy = _EvaluationProxy(
                    spec,
                    deadline_seconds=float(
                        acceptance_raw["operations"]["request_deadline_seconds"]
                    ),
                    regions=regions,
                    responses_by_query=responses,
                    query_id_by_hash=query_hash_to_id,
                )
                from research_platform.evaluation.run_records import HardwareDescriptor

                run_hardware = HardwareDescriptor.capture_host(
                    ram_bytes=hardware["ram_bytes"],
                    accelerator_name=hardware["accelerator_name"],
                    accelerator_memory_bytes=hardware["accelerator_memory_bytes"],
                )
                options = EvaluationOptions(
                    retrieval_profile_id=spec.profile.profile_id,
                    mode=spec.mode,
                    calibration_sha256=_sha256_file(dataset_path),
                    source_alignment_sha256=_sha256_file(alignment_path),
                    code_revision=code_revision[:40],
                    limit=int(acceptance_raw["operations"]["candidate_pool_limit"]),
                    latency_kind="warm",
                    hardware=run_hardware,
                    experiment_id="phase2-r8-heldout-v12",
                    comparison_id=spec.name,
                    random_seed=int(freeze["timing"]["seed"]),
                )
                profile_records = await evaluate_heldout(
                    proxy,
                    run_dataset,
                    run_alignment,
                    options=options,
                    regions_by_evidence_id=regions,
                    eligible_paper_ids_by_query=eligible,
                )
                all_records.extend(profile_records)
                responses_by_profile_query[spec.name] = responses
                regions_by_profile[spec.name] = regions
                alignments_by_profile[spec.name] = run_alignment
                eligible_by_profile_query[spec.name] = eligible
                profile_failures[spec.name] = {
                    "attempts": sum(len(record.attempts) for record in profile_records),
                    "hard_failures": sum(
                        attempt.status == "failed"
                        for record in profile_records
                        for attempt in record.attempts
                    ),
                    "degraded_attempts": sum(
                        attempt.status == "degraded"
                        for record in profile_records
                        for attempt in record.attempts
                    ),
                    "fallbacks": sum(
                        attempt.effective_mode is not None
                        and attempt.effective_mode is not attempt.requested_mode
                        for record in profile_records
                        for attempt in record.attempts
                    ),
                }
                family_rows_by_profile[spec.name] = {}

            family_rows_by_profile = _family_aggregates(
                dataset,
                all_records,
                responses_by_profile_query,
                regions_by_profile,
                alignments_by_profile,
                eligible_by_profile_query,
            )
            profile_summaries = {
                name: _profile_summary(rows)
                for name, rows in family_rows_by_profile.items()
            }
            seed = int(freeze["timing"]["seed"])
            paired: dict[str, Any] = {}
            paired_metrics = (
                "paper_ndcg_at_10",
                "paper_direct_mrr_at_10",
                "paper_judged_recall_at_20",
                "evidence_ndcg_at_10",
                "evidence_direct_mrr_at_10",
                "evidence_judged_recall_at_20",
                "source_anchor_recall_at_10",
                "source_anchor_recall_at_50",
            )
            selected_name = "reranked_minilm_hybrid"
            for baseline in (
                "bm25_lexical",
                "dense_e5",
                "hybrid_e5",
                "fixed_window_dense_e5",
            ):
                paired[baseline] = _paired_bootstrap(
                    family_rows_by_profile,
                    selected_name,
                    baseline,
                    paired_metrics,
                    seed=seed,
                    repetitions=int(freeze["timing"]["bootstrap_repetitions"]),
                )

            timing = await _warm_timing(
                specs,
                dataset,
                settings,
                seed=seed,
                sessions=int(freeze["timing"]["sessions"]),
                requests_per_session=int(freeze["timing"]["requests_per_session"]),
                warmups_per_session=int(freeze["timing"]["warmups_per_session"]),
                selected_profile=selected_name,
                deadline_seconds=float(
                    acceptance_raw["operations"]["request_deadline_seconds"]
                ),
            )
            selected_timing = timing[selected_name]
            selected_operations = profile_failures[selected_name]
            selected_summary = profile_summaries[selected_name]
            acceptance_config = load_acceptance_config(
                manifest_dir / "acceptance-v10.toml"
            )
            observations = {
                "paper_ndcg_at_10": selected_summary["paper_ndcg_at_10_macro"],
                "paper_direct_mrr_at_10": selected_summary[
                    "paper_direct_mrr_at_10_macro"
                ],
                "paper_judged_recall_at_20": selected_summary[
                    "paper_judged_recall_at_20_macro"
                ],
                "evidence_ndcg_at_10": selected_summary["evidence_ndcg_at_10_macro"],
                "evidence_direct_mrr_at_10": selected_summary[
                    "evidence_direct_mrr_at_10_macro"
                ],
                "evidence_judged_recall_at_20": selected_summary[
                    "evidence_judged_recall_at_20_macro"
                ],
                "source_anchor_recall_at_10": selected_summary[
                    "source_anchor_recall_at_10_micro"
                ],
                "source_anchor_recall_at_50": selected_summary[
                    "source_anchor_recall_at_50_micro"
                ],
                "positive_families_with_source_hit_at_10_fraction": selected_summary[
                    "positive_families_with_source_hit_at_10_fraction"
                ],
                "hard_failure_fraction": selected_operations["hard_failures"]
                / selected_operations["attempts"],
                "reranker_fallback_fraction": selected_operations["fallbacks"]
                / selected_operations["attempts"],
                "warm_p95_ms": selected_timing["p95_nearest_rank_ms"],
                "combined_cold_model_load_ms": model_loads.get("e5_model_load_ms", 0.0)
                + model_loads.get("reranker_model_load_ms", 0.0),
                "summed_cuda_allocated_bytes": model_loads.get(
                    "e5_allocated_delta_bytes", 0
                )
                + model_loads.get("reranker_allocated_delta_bytes", 0),
            }
            gate_report = build_acceptance_gate_report(acceptance_config, observations)

            category_summary: dict[str, Any] = {}
            for category in sorted(
                {
                    category
                    for family in dataset.families
                    for category in family.categories
                }
            ):
                category_families = [
                    family
                    for family in dataset.families
                    if category in family.categories
                ]
                rows = [
                    family_rows_by_profile[selected_name].get(family.id, {})
                    for family in category_families
                ]
                source_num = sum(
                    int(row.get("source_anchor_recall_at_10_numerator", 0))
                    for row in rows
                )
                source_den = sum(
                    int(row.get("source_anchor_recall_at_10_denominator", 0))
                    for row in rows
                )
                category_summary[category] = {
                    "families": len(category_families),
                    "paper_ndcg_at_10_macro": _mean(
                        [row.get("paper_ndcg_at_10") for row in rows]
                    ),
                    "evidence_ndcg_at_10_macro": _mean(
                        [row.get("evidence_ndcg_at_10") for row in rows]
                    ),
                    "source_anchor_recall_at_10_micro": source_num / source_den
                    if source_den
                    else None,
                }

            if torch.cuda.is_available():
                torch.cuda.synchronize(0)
                peak_cuda_allocated = int(torch.cuda.max_memory_allocated(0))
                peak_cuda_reserved = int(torch.cuda.max_memory_reserved(0))
            else:
                peak_cuda_allocated = None
                peak_cuda_reserved = None
            raw_result = {
                "schema_version": 1,
                "experiment_id": "phase2-r8-heldout-v12",
                "started_at_utc": assessment_started_at,
                "completed_at_utc": None,
                "code_revision": code_revision,
                "clean_worktree": True,
                "freeze_id": freeze["freeze_id"],
                "freeze_manifest_sha256": _sha256_file(FREEZE_PATH),
                "benchmark": {
                    "dataset_id": dataset.dataset_id,
                    "dataset_sha256": _sha256_file(dataset_path),
                    "source_alignment_sha256": _sha256_file(alignment_path),
                    "family_count": len(dataset.families),
                    "positive_family_count": sum(
                        not family.unsupported for family in dataset.families
                    ),
                    "unsupported_family_count": sum(
                        family.unsupported for family in dataset.families
                    ),
                    "positive_anchor_count": sum(
                        row["source_anchor_recall_at_10_denominator"]
                        for row in family_rows_by_profile[selected_name].values()
                    ),
                    "categories": {
                        category: sum(
                            category in family.categories for family in dataset.families
                        )
                        for category in sorted(
                            {
                                category
                                for family in dataset.families
                                for category in family.categories
                            }
                        )
                    },
                },
                "hardware": hardware,
                "model_loads": {
                    **model_loads,
                    "runtime_startup_ms": runtime_startup_ms,
                    "combined_cold_model_load_ms": observations[
                        "combined_cold_model_load_ms"
                    ],
                    "summed_cuda_allocated_bytes": observations[
                        "summed_cuda_allocated_bytes"
                    ],
                    "cuda_peak_allocated_bytes": peak_cuda_allocated,
                    "cuda_peak_reserved_bytes": peak_cuda_reserved,
                },
                "profile_results": {
                    spec.name: {
                        "profile_id": spec.profile.profile_id,
                        "mode": spec.mode.value,
                        "source_variant": spec.variant,
                        "metrics": profile_summaries[spec.name],
                        "attempts": profile_failures[spec.name],
                        "warm_latency": {
                            key: value
                            for key, value in timing[spec.name].items()
                            if key != "samples_private"
                        },
                        "per_family": family_rows_by_profile[spec.name],
                    }
                    for spec in specs
                },
                "paired_bootstrap_selected_minus_baseline": paired,
                "selected_category_summary": category_summary,
                "acceptance_observations": observations,
                "acceptance_gates": gate_report,
                "raw_query_runs": [record.to_dict() for record in all_records],
                "private_timing_samples": {
                    name: value["samples_private"] for name, value in timing.items()
                },
                "unsupported_policy": "ranking_only; cutoff disabled; no rejection accuracy computed",
                "limitations": [
                    "Ten purposively selected held-out families support directional evidence, not precise population estimates.",
                    "Reviews were assistant-reviewed without independent second annotation.",
                    "Source freshness could not be fully certified against prior private family identities.",
                ],
            }
            raw_result["completed_at_utc"] = (
                datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            )
            output_path = output_dir / "heldout-assessment-v1.json"
            output_digest = _atomic_private_json(output_path, raw_result)
            return {
                "passed": bool(gate_report["passed"]),
                "gate_report": gate_report,
                "observations": observations,
                "profile_summaries": profile_summaries,
                "timings": {
                    name: {
                        key: value
                        for key, value in timing[name].items()
                        if key != "samples_private"
                    }
                    for name in timing
                },
                "output_name": output_path.name,
                "output_sha256": output_digest,
                "freeze_manifest_sha256": _sha256_file(FREEZE_PATH),
                "runtime_startup_ms": round(runtime_startup_ms, 1),
                "hardware": hardware,
                "category_summary": category_summary,
                "paired": paired,
                "dataset_sha256": _sha256_file(dataset_path),
                "alignment_sha256": _sha256_file(alignment_path),
            }
        finally:
            await runtime.close()


def _display_number(value: object, digits: int = 4) -> str:
    return f"{value:.{digits}f}" if isinstance(value, (int, float)) else "n/a"


def _print_summary(result: Mapping[str, Any]) -> None:
    if result.get("validation") == "passed":
        print("R8 private inputs and freeze: valid")
        print(f"Held-out families: {result['family_count']}")
        print(
            f"Source alignment anchors: {result['aligned_table_anchor_count']} tables, {result['aligned_text_anchor_count']} prose"
        )
        print(f"Dataset SHA-256: {result['dataset_sha256']}")
        print(f"Alignment SHA-256: {result['alignment_sha256']}")
        return
    gate = result["gate_report"]
    print(
        f"R8 acceptance: {'PASS' if result['passed'] else 'FAIL'} ({gate['pass_count']}/{gate['gate_count']} gates)"
    )
    print(f"Private raw record: {result['output_name']} ({result['output_sha256']})")
    print(f"R8 freeze SHA-256: {result['freeze_manifest_sha256']}")
    print(
        f"Dataset SHA-256: {result['dataset_sha256']}; alignment SHA-256: {result['alignment_sha256']}"
    )
    for name, summary in result["profile_summaries"].items():
        print(
            f"{name}: paper nDCG@10={_display_number(summary['paper_ndcg_at_10_macro'])}; "
            f"evidence nDCG@10={_display_number(summary['evidence_ndcg_at_10_macro'])}; "
            f"source recall@10/@50={_display_number(summary['source_anchor_recall_at_10_micro'])}/"
            f"{_display_number(summary['source_anchor_recall_at_50_micro'])}; "
            f"warm p95={_display_number(result['timings'][name]['p95_nearest_rank_ms'], 1)} ms "
            f"({result['timings'][name]['samples']} samples)"
        )
    print("Selected profile gates:")
    for row in gate["gates"]:
        print(
            f"  {'PASS' if row['passed'] else 'FAIL'} {row['metric']}: {row['observed']:.4f} (threshold {row['threshold']:.4f})"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--heldout", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--alignment", type=Path, default=DEFAULT_ALIGNMENT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--variant-dir",
        type=Path,
        default=PRIVATE_ROOT / "fixed-window-20260927",
    )
    parser.add_argument("--validate-only", action="store_true")
    arguments = parser.parse_args()
    if not FREEZE_PATH.is_file():
        parser.error("R8 freeze manifest is missing")
    log_path: Path | None = None
    if arguments.validate_only:
        result = asyncio.run(
            _run_assessment(
                arguments.heldout,
                arguments.alignment,
                arguments.output_dir,
                arguments.variant_dir,
                validate_only=True,
            )
        )
        _print_summary(result)
        return 0
    arguments.output_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
    arguments.output_dir.chmod(0o700)
    log_path = arguments.output_dir / "runner-private.log"
    log_path.touch(mode=0o600, exist_ok=False)
    log_path.chmod(0o600)
    try:
        with log_path.open("a", encoding="utf-8") as log_file:
            with redirect_stdout(log_file), redirect_stderr(log_file):
                result = asyncio.run(
                    _run_assessment(
                        arguments.heldout,
                        arguments.alignment,
                        arguments.output_dir,
                        arguments.variant_dir,
                        validate_only=False,
                    )
                )
        _print_summary(result)
        return 0 if result["passed"] else 2
    except Exception as error:
        with log_path.open("a", encoding="utf-8") as log_file:
            log_file.write(f"\nAssessment stopped: {type(error).__name__}\n")
        print(
            f"R8 assessment stopped; private diagnostic log: {log_path.name} ({type(error).__name__})"
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
