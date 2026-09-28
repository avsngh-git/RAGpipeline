"""Repeatable, development-only HTTP retrieval timing and result fingerprinting."""

from __future__ import annotations

import argparse
import asyncio
import contextvars
import hashlib
import json
import os
import platform
import random
import statistics
import subprocess
import sys
import time
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator
from urllib.parse import urlsplit

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
ALLOWLIST_PATH = (
    REPOSITORY_ROOT / "benchmarks/phase2/phase2-dev-input-allowlist-v1.json"
)
EXCLUDED_FAMILY_IDS = frozenset({"q20", "q21"})
ALLOWED_DEVELOPMENT_FAMILIES = frozenset(f"q{number}" for number in range(11, 20))


@dataclass
class _StageFrame:
    name: str
    started: float
    child_ms: float = 0.0


class _StageCollector:
    def __init__(self) -> None:
        self._stack: contextvars.ContextVar[tuple[_StageFrame, ...]] = (
            contextvars.ContextVar("phase2_benchmark_stage_stack", default=())
        )
        self.samples: dict[str, list[dict[str, float]]] = defaultdict(list)

    def reset(self) -> None:
        self.samples.clear()

    @contextmanager
    def span(self, name: str) -> Iterator[None]:
        frame = _StageFrame(name=name, started=time.perf_counter())
        stack = self._stack.get()
        token = self._stack.set((*stack, frame))
        try:
            yield
        finally:
            elapsed_ms = (time.perf_counter() - frame.started) * 1000
            exclusive_ms = max(0.0, elapsed_ms - frame.child_ms)
            self.samples[name].append(
                {"inclusive_ms": elapsed_ms, "exclusive_ms": exclusive_ms}
            )
            self._stack.reset(token)
            if stack:
                stack[-1].child_ms += elapsed_ms


def _wrap_method(
    target: object, name: str, stage_name: str, stages: _StageCollector
) -> None:
    original = getattr(target, name)
    if asyncio.iscoroutinefunction(original):

        async def async_wrapper(*args: object, **kwargs: object) -> object:
            with stages.span(stage_name):
                return await original(*args, **kwargs)

        setattr(target, name, async_wrapper)
        return

    def sync_wrapper(*args: object, **kwargs: object) -> object:
        with stages.span(stage_name):
            return original(*args, **kwargs)

    setattr(target, name, sync_wrapper)


def _character_length_bucket(length: int) -> str:
    if length <= 512:
        return "0-512"
    if length <= 2048:
        return "513-2048"
    return "2049+"


def _fallback_input_summary(
    query: str, candidates: object, rerank_limit: object
) -> dict[str, object]:
    candidate_list = list(candidates) if isinstance(candidates, (tuple, list)) else []
    limit = (
        rerank_limit
        if isinstance(rerank_limit, int) and not isinstance(rerank_limit, bool)
        else len(candidate_list)
    )
    prefix = candidate_list[:limit]
    candidate_kinds: dict[str, dict[str, int]] = {
        "prose": {"0-512": 0, "513-2048": 0, "2049+": 0},
        "table": {"0-512": 0, "513-2048": 0, "2049+": 0},
    }
    for candidate in prefix:
        kind_value = getattr(candidate, "kind", "text")
        kind = "table" if kind_value in {"table", "table_row_group"} else "prose"
        text_value = getattr(candidate, "text", "")
        length = len(text_value) if isinstance(text_value, str) else 0
        candidate_kinds[kind][_character_length_bucket(length)] += 1
    return {
        "query_char_length_bucket": _character_length_bucket(len(query)),
        "candidate_char_length_buckets_by_kind": candidate_kinds,
        "rerank_prefix_candidate_count": len(prefix),
    }


def _fallback_diagnostic_summary(
    samples: list[dict[str, object]],
) -> dict[str, object]:
    events = [
        event
        for sample in samples
        for event in sample.get("reranker_fallback_diagnostics", [])
        if isinstance(event, dict)
    ]
    categories: defaultdict[str, int] = defaultdict(int)
    query_lengths: defaultdict[str, int] = defaultdict(int)
    candidate_kind_lengths: dict[str, defaultdict[str, int]] = {
        "prose": defaultdict(int),
        "table": defaultdict(int),
    }
    for event in events:
        category = event.get("failure_category")
        query_bucket = event.get("query_char_length_bucket")
        if isinstance(category, str):
            categories[category] += 1
        if isinstance(query_bucket, str):
            query_lengths[query_bucket] += 1
        kind_buckets = event.get("candidate_char_length_buckets_by_kind")
        if not isinstance(kind_buckets, dict):
            continue
        for kind in ("prose", "table"):
            bucket_counts = kind_buckets.get(kind)
            if not isinstance(bucket_counts, dict):
                continue
            for bucket, count in bucket_counts.items():
                if isinstance(bucket, str) and isinstance(count, int):
                    candidate_kind_lengths[kind][bucket] += count
    return {
        "fallback_count": len(events),
        "by_failure_category": dict(sorted(categories.items())),
        "by_query_char_length_bucket": dict(sorted(query_lengths.items())),
        "rerank_prefix_candidates_by_kind_and_char_length": {
            kind: dict(sorted(bucket_counts.items()))
            for kind, bucket_counts in candidate_kind_lengths.items()
        },
    }


def _install_instrumentation(
    stages: _StageCollector, fallback_events: list[dict[str, object]]
) -> None:
    from fastapi.responses import JSONResponse

    from research_platform.ingestion.embeddings import E5SmallV2Embedder
    from research_platform.ingestion.indexing import IndexRepository, QdrantIndex
    from research_platform.search import application
    from research_platform.search.application import (
        Phase2SearchExecutor,
        SnapshotEligibilityReader,
    )
    from research_platform.search.reranker import CrossEncoderReranker

    original_rerank_with_fallback = application.rerank_with_fallback

    async def observe_rerank_with_fallback(
        profile: object,
        query: object,
        candidates: object,
        reranker: object,
    ) -> object:
        outcome = await original_rerank_with_fallback(
            profile, query, candidates, reranker
        )
        failure = getattr(outcome, "failure", None)
        if failure is not None and isinstance(query, str):
            profile_limits = getattr(profile, "candidate_limits", None)
            rerank_limit = getattr(profile_limits, "rerank_top_k", None)
            input_summary = _fallback_input_summary(query, candidates, rerank_limit)
            fallback_events.append(
                {
                    "failure_category": getattr(
                        failure, "failure_category", "adapter_failure"
                    ),
                    "error_type": getattr(failure, "error_type", "unknown"),
                    **input_summary,
                }
            )
        return outcome

    application.rerank_with_fallback = observe_rerank_with_fallback
    for target, name, label in (
        (SnapshotEligibilityReader, "read", "eligibility"),
        (
            IndexRepository,
            "_snapshot_selection_on_connection",
            "exact_selection_validation",
        ),
        (E5SmallV2Embedder, "embed_query", "query_embedding"),
        (QdrantIndex, "query_snapshot", "qdrant_query"),
        (IndexRepository, "hydrate_snapshot_matches", "authoritative_hydration"),
        (CrossEncoderReranker, "rerank", "reranking"),
        (Phase2SearchExecutor, "_attach_table_context", "table_context"),
        (application, "select_evidence_results", "evidence_selection"),
        (application, "select_paper_results", "paper_selection"),
        (JSONResponse, "render", "http_json_serialization"),
    ):
        _wrap_method(target, name, label, stages)


def _sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return _sha256(encoded)


def _load_cases(
    input_path: Path, allowlist_path: Path
) -> tuple[dict[str, object], list[dict[str, object]]]:
    raw_bytes = input_path.read_bytes()
    try:
        dataset = json.loads(raw_bytes)
        allowlist = json.loads(allowlist_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        raise ValueError("development inputs or allowlist are invalid JSON") from None
    if not isinstance(dataset, dict) or dataset.get("schema_version") != 1:
        raise ValueError("development input schema is unsupported")
    if not isinstance(allowlist, dict) or allowlist.get("schema_version") != 1:
        raise ValueError("development allowlist schema is unsupported")
    kind = dataset.get("dataset_kind")
    cases = dataset.get("cases")
    if not isinstance(kind, str) or not isinstance(cases, list) or not cases:
        raise ValueError("development inputs must declare a kind and non-empty cases")

    synthetic = allowlist.get("synthetic_diagnostic")
    if not isinstance(synthetic, dict):
        raise ValueError("development allowlist has no synthetic diagnostic entry")
    if kind == "synthetic_development_diagnostic":
        if (
            dataset.get("dataset_id") != synthetic.get("dataset_id")
            or _sha256(raw_bytes) != synthetic.get("input_sha256")
            or dataset.get("split") != "development"
        ):
            raise ValueError(
                "synthetic input does not match the approved development fixture"
            )
    elif kind == "reviewed_development":
        reviewed = allowlist.get("reviewed_development")
        if not isinstance(reviewed, dict):
            raise ValueError("development allowlist has no reviewed development entry")
        if (
            dataset.get("split") != "development"
            or dataset.get("split_policy_id") != reviewed.get("split_policy_id")
            or dataset.get("question_manifest_sha256")
            != reviewed.get("question_manifest_sha256")
            or dataset.get("split_manifest_sha256")
            != reviewed.get("split_manifest_sha256")
        ):
            raise ValueError("reviewed input is outside the approved development split")
    else:
        raise ValueError("held-out, spent or unrecognized input kinds are prohibited")

    validated: list[dict[str, object]] = []
    allowed_families = set(ALLOWED_DEVELOPMENT_FAMILIES)
    for case in cases:
        if not isinstance(case, dict):
            raise ValueError("development case is malformed")
        required = {
            "query_id",
            "family_id",
            "category",
            "query",
            "operation",
            "filters",
            "limit",
        }
        if set(case) != required:
            raise ValueError("development case fields are incomplete or unknown")
        family_id = case["family_id"]
        query_id = case["query_id"]
        if not isinstance(family_id, str) or not isinstance(query_id, str):
            raise ValueError("development case identities are malformed")
        if family_id in EXCLUDED_FAMILY_IDS or query_id in EXCLUDED_FAMILY_IDS:
            raise ValueError("q20 and q21 are excluded from the development loop")
        if kind == "reviewed_development":
            reviewed_entry = allowlist["reviewed_development"]
            listed_families = reviewed_entry.get("allowed_family_ids")
            listed_exclusions = reviewed_entry.get("excluded_family_ids")
            if not isinstance(listed_families, list) or not isinstance(
                listed_exclusions, list
            ):
                raise ValueError("reviewed development allowlist is malformed")
            if family_id in listed_exclusions:
                raise ValueError("excluded development family is prohibited")
            if family_id not in allowed_families or family_id not in listed_families:
                raise ValueError("development case family is not allowlisted")
            if not query_id.startswith(family_id):
                raise ValueError("development query does not belong to its family")
        if (
            not isinstance(case["query"], str)
            or not case["query"].strip()
            or case["operation"] not in {"paper_search", "evidence_search"}
            or not isinstance(case["filters"], dict)
            or isinstance(case["limit"], bool)
            or not isinstance(case["limit"], int)
            or not 1 <= case["limit"] <= 50
        ):
            raise ValueError("development case request is invalid")
        validated.append(dict(case))
    return dataset, validated


def _git_value(*arguments: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", *arguments],
            cwd=REPOSITORY_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip()


def _git_identity() -> dict[str, object]:
    diff = subprocess.run(
        ["git", "diff", "--binary", "HEAD"],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
    )
    status = _git_value("status", "--porcelain=v1") or ""
    return {
        "revision": _git_value("rev-parse", "HEAD"),
        "tracked_worktree_dirty": bool(diff.stdout),
        "tracked_diff_sha256": _sha256(diff.stdout) if diff.stdout else None,
        "untracked_path_count": sum(
            line.startswith("??") for line in status.splitlines()
        ),
    }


def _percentile95(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, int(0.95 * len(ordered) + 0.999999999) - 1)
    return ordered[index]


def _summary(values: list[float]) -> dict[str, object]:
    if not values:
        return {"count": 0, "median_ms": None, "p95_ms": None}
    return {
        "count": len(values),
        "median_ms": statistics.median(values),
        "p95_ms": _percentile95(values),
        "min_ms": min(values),
        "max_ms": max(values),
    }


def _stage_summary(samples: list[dict[str, object]]) -> dict[str, object]:
    names = sorted(
        {name for sample in samples for name in sample.get("stage_timings", {})}
    )
    result: dict[str, object] = {}
    for name in names:
        inclusive = [
            float(sample["stage_timings"][name]["inclusive_total_ms"])
            for sample in samples
            if name in sample.get("stage_timings", {})
        ]
        exclusive = [
            float(sample["stage_timings"][name]["exclusive_total_ms"])
            for sample in samples
            if name in sample.get("stage_timings", {})
        ]
        result[name] = {
            "inclusive": _summary(inclusive),
            "exclusive": _summary(exclusive),
        }
    return result


def _response_fingerprint(response_data: object) -> str:
    if isinstance(response_data, dict):
        safe = dict(response_data)
        safe.pop("request_id", None)
        return _canonical_sha256(safe)
    return _canonical_sha256(response_data)


def _sample_stages(stages: _StageCollector) -> dict[str, dict[str, object]]:
    return {
        name: {
            "calls": len(values),
            "inclusive_total_ms": round(
                sum(value["inclusive_ms"] for value in values), 3
            ),
            "exclusive_total_ms": round(
                sum(value["exclusive_ms"] for value in values), 3
            ),
            "calls_ms": [round(value["inclusive_ms"], 3) for value in values],
        }
        for name, values in sorted(stages.samples.items())
    }


def _safe_database_target(database_url: str) -> dict[str, object]:
    parsed = urlsplit(database_url)
    return {
        "host": parsed.hostname,
        "port": parsed.port,
        "database": parsed.path.lstrip("/"),
    }


async def _run(
    args: argparse.Namespace, input_hash: str, cases: list[dict[str, object]]
) -> dict[str, object]:
    os.environ["HF_HOME"] = str(args.embedding_cache_dir.resolve())
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["TOKENIZERS_PARALLELISM"] = "false"
    for variable in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
        os.environ[variable] = str(args.cpu_threads)

    import httpx
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse

    from research_platform.api.app import create_app
    from research_platform.api.routes import Phase2APIServices
    from research_platform.config import Settings
    from research_platform.search.application import create_phase2_runtime
    from research_platform.search.profile_manifest import load_frozen_profile
    from research_platform.services.readiness import ReadinessReport

    del FastAPI, JSONResponse, Phase2APIServices
    profile = load_frozen_profile(args.profile)
    settings = Settings(
        environment="test",
        log_level="WARNING",
        database_url=os.environ[args.database_url_env],
        qdrant_url=args.qdrant_url,
        evidence_access_profile="trusted_private_local",
        lexical_index_root=args.lexical_index_root,
        model_device=args.device,
        reranker_cache_dir=args.reranker_cache_dir,
    )

    class _Ready:
        async def check(self) -> ReadinessReport:
            return ReadinessReport(dependencies={})

    stages = _StageCollector()
    fallback_events: list[dict[str, object]] = []
    _install_instrumentation(stages, fallback_events)
    session_rows: list[dict[str, object]] = []
    args._runtime_start_ms = []
    mode_counts: defaultdict[str, int] = defaultdict(int)
    failure_count = 0
    fallback_count = 0
    warmup_count = args.warmups

    for session_index in range(args.sessions):
        runtime_started = time.perf_counter()
        runtime = await create_phase2_runtime(
            settings, frozen_profile_path=args.profile
        )
        runtime_start_ms = (time.perf_counter() - runtime_started) * 1000
        args._runtime_start_ms.append(runtime_start_ms)
        app = create_app(
            settings, dependency_checker=_Ready(), api_services=runtime.api_services
        )
        order = [
            cases[index % len(cases)]
            for index in range(warmup_count + args.requests_per_session)
        ]
        random.Random(args.seed + session_index).shuffle(order)
        transport = httpx.ASGITransport(app=app)
        try:
            async with app.router.lifespan_context(app):
                async with httpx.AsyncClient(
                    transport=transport,
                    base_url="http://phase2-development.local",
                    timeout=40.0,
                ) as client:
                    for request_index, case in enumerate(order):
                        stages.reset()
                        started = time.perf_counter()
                        operation = str(case["operation"])
                        endpoint = (
                            "/v1/search"
                            if operation == "paper_search"
                            else "/v1/evidence/search"
                        )
                        body = {
                            "query": case["query"],
                            "snapshot_id": str(profile.snapshot.snapshot_id),
                            "retrieval_profile_id": profile.profile_id,
                            "mode": "reranked",
                            "filters": case["filters"],
                            "limit": case["limit"],
                        }
                        http_status = 0
                        fallback_event_start = len(fallback_events)
                        response_data: object = None
                        try:
                            response = await client.post(endpoint, json=body)
                            http_status = response.status_code
                            response_data = response.json()
                        except Exception as error:
                            response_data = {"error_type": type(error).__name__}
                        elapsed_ms = (time.perf_counter() - started) * 1000
                        if request_index < warmup_count:
                            continue
                        if not isinstance(response_data, dict):
                            response_data = {"malformed_response": True}
                        effective_mode = response_data.get("effective_mode")
                        effective_name = (
                            effective_mode
                            if isinstance(effective_mode, str)
                            else "error"
                        )
                        mode_counts[effective_name] += 1
                        is_fallback = (
                            http_status == 200 and effective_name != "reranked"
                        )
                        fallback_count += int(is_fallback)
                        failure_count += int(http_status != 200)
                        warnings = response_data.get("warnings", [])
                        if not isinstance(warnings, list):
                            warnings = []
                        truncated = response_data.get("truncated") is True
                        omitted_count = response_data.get("omitted_count")
                        sample = {
                            "session_index": session_index,
                            "request_index": request_index - warmup_count,
                            "category": case["category"],
                            "operation": operation,
                            "result_limit": case["limit"],
                            "http_status": http_status,
                            "latency_ms": round(elapsed_ms, 3),
                            "requested_mode": "reranked",
                            "effective_mode": effective_name,
                            "fallback": is_fallback,
                            "warning_count": len(warnings),
                            "truncated": truncated,
                            "omitted_count": omitted_count
                            if isinstance(omitted_count, int)
                            and not isinstance(omitted_count, bool)
                            else None,
                            "response_fingerprint_sha256": _response_fingerprint(
                                response_data
                            ),
                            "reranker_fallback_diagnostics": list(
                                fallback_events[fallback_event_start:]
                            ),
                            "stage_timings": _sample_stages(stages),
                        }
                        session_rows.append(sample)
        finally:
            await runtime.close()

    by_session: list[list[dict[str, object]]] = [
        [row for row in session_rows if row["session_index"] == session_index]
        for session_index in range(args.sessions)
    ]
    session_summaries: list[dict[str, object]] = []
    for session_index, rows in enumerate(by_session):
        session_summaries.append(
            {
                "session": session_index + 1,
                "warmup_requests": warmup_count,
                "measured_requests": len(rows),
                "http_latency": _summary([float(row["latency_ms"]) for row in rows]),
                "failure_count": sum(row["http_status"] != 200 for row in rows),
                "fallback_count": sum(row["fallback"] is True for row in rows),
                "selection_reconstruction_calls": sum(
                    int(
                        row["stage_timings"]
                        .get("exact_selection_validation", {})
                        .get("calls", 0)
                    )
                    for row in rows
                ),
                "stages": _stage_summary(rows),
                "reranker_fallback_diagnostics": _fallback_diagnostic_summary(rows),
            }
        )

    return {
        "schema_version": 1,
        "benchmark_id": "phase2-development-retrieval-diagnostic-v1",
        "input_sha256": input_hash,
        "input_kind": "development_only",
        "profile_manifest": args.profile.name,
        "profile_sha256": _sha256(args.profile.read_bytes()),
        "profile_id": profile.profile_id,
        "snapshot_id": str(profile.snapshot.snapshot_id),
        "code": _git_identity(),
        "environment": {
            "database_target": _safe_database_target(settings.database_url),
            "qdrant_host": urlsplit(args.qdrant_url).hostname,
            "embedding_cache_configured": True,
            "reranker_cache_configured": True,
            "device": args.device,
            "cpu_threads": args.cpu_threads,
            "concurrency": args.concurrency,
            "background_load": args.background_load,
            "platform": platform.platform(),
            "python": sys.version.split()[0],
        },
        "procedure": {
            "sessions": args.sessions,
            "warmup_requests_per_session": warmup_count,
            "measured_requests_per_session": args.requests_per_session,
            "order_seed": args.seed,
            "result_limits": sorted({int(case["limit"]) for case in cases}),
            "case_count": len(cases),
        },
        "runtime_start_ms_by_session": [
            round(value, 3) for value in args._runtime_start_ms
        ],
        "request_counts": {
            "measured": len(session_rows),
            "failures": failure_count,
            "fallbacks": fallback_count,
            "effective_modes": dict(sorted(mode_counts.items())),
        },
        "reranker_fallback_diagnostics": _fallback_diagnostic_summary(session_rows),
        "sessions": session_summaries,
        "samples": session_rows,
    }


def _compare(current: dict[str, object], baseline_path: Path) -> dict[str, object]:
    try:
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise ValueError("comparison baseline is invalid JSON") from None
    if not isinstance(baseline, dict):
        raise ValueError("comparison baseline is malformed")
    for key in ("input_sha256", "profile_id", "procedure", "environment"):
        if baseline.get(key) != current.get(key):
            raise ValueError(f"comparison baseline differs in {key}")
    old_samples = baseline.get("samples")
    new_samples = current.get("samples")
    if not isinstance(old_samples, list) or not isinstance(new_samples, list):
        raise ValueError("comparison baseline has no request samples")
    if len(old_samples) != len(new_samples):
        raise ValueError("comparison baseline request count differs")
    changed_fingerprints = sum(
        old.get("response_fingerprint_sha256") != new.get("response_fingerprint_sha256")
        for old, new in zip(old_samples, new_samples, strict=True)
    )
    changed_modes = sum(
        old.get("effective_mode") != new.get("effective_mode")
        for old, new in zip(old_samples, new_samples, strict=True)
    )
    old_p95 = _percentile95([float(row["latency_ms"]) for row in old_samples])
    new_p95 = _percentile95([float(row["latency_ms"]) for row in new_samples])
    return {
        "baseline_code": baseline.get("code"),
        "current_code": current.get("code"),
        "aligned_requests": len(new_samples),
        "ordered_result_fingerprint_changes": changed_fingerprints,
        "effective_mode_changes": changed_modes,
        "baseline_warm_p95_ms": old_p95,
        "current_warm_p95_ms": new_p95,
        "warm_p95_delta_ms": (
            round(new_p95 - old_p95, 3)
            if old_p95 is not None and new_p95 is not None
            else None
        ),
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url-env", required=True)
    parser.add_argument("--qdrant-url", required=True)
    parser.add_argument("--embedding-cache-dir", type=Path, required=True)
    parser.add_argument("--reranker-cache-dir", type=Path, required=True)
    parser.add_argument("--lexical-index-root", type=Path, required=True)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--allowlist", type=Path, default=ALLOWLIST_PATH)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), required=True)
    parser.add_argument("--cpu-threads", type=int, default=4)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--background-load", default="no intentional background load")
    parser.add_argument("--sessions", type=int, default=3)
    parser.add_argument("--warmups", type=int, default=6)
    parser.add_argument("--requests-per-session", type=int, default=100)
    parser.add_argument("--seed", type=int, default=20260928)
    parser.add_argument("--compare-to", type=Path)
    parser.add_argument(
        "--smoke", action="store_true", help="allow a short one-session harness check"
    )
    args = parser.parse_args()
    if args.cpu_threads < 1 or args.concurrency != 1:
        parser.error(
            "cpu threads must be positive and diagnostic concurrency must remain 1"
        )
    if args.smoke:
        if args.sessions != 1 or args.requests_per_session > 10:
            parser.error("--smoke requires one session with at most ten requests")
    elif args.sessions < 3 or args.requests_per_session < 100:
        parser.error(
            "acceptance-quality diagnostics require three sessions of 100 warm requests"
        )
    if not args.database_url_env or args.database_url_env not in os.environ:
        parser.error("the selected database URL environment variable is unavailable")
    for path in (
        args.embedding_cache_dir,
        args.reranker_cache_dir,
        args.lexical_index_root,
        args.profile,
        args.inputs,
        args.allowlist,
    ):
        if not path.exists():
            parser.error(f"required diagnostic path does not exist: {path.name}")
    output = args.output.resolve()
    private_root = (REPOSITORY_ROOT / "local-reference").resolve()
    if output.is_relative_to(REPOSITORY_ROOT.resolve()) and not output.is_relative_to(
        private_root
    ):
        parser.error(
            "private benchmark output must be outside Git or under local-reference"
        )
    if args.output.exists():
        parser.error("refusing to overwrite an existing development run")
    args.profile = args.profile.resolve()
    args.embedding_cache_dir = args.embedding_cache_dir.resolve()
    args.reranker_cache_dir = args.reranker_cache_dir.resolve()
    args.lexical_index_root = args.lexical_index_root.resolve()
    args.inputs = args.inputs.resolve()
    args.allowlist = args.allowlist.resolve()
    args._runtime_start_ms = []
    return args


def main() -> int:
    args = _parse_args()
    try:
        _dataset, cases = _load_cases(args.inputs, args.allowlist)
        input_hash = _sha256(args.inputs.read_bytes())
        report = asyncio.run(_run(args, input_hash, cases))
        if args.compare_to is not None:
            report["comparison"] = _compare(report, args.compare_to)
        report["run_sha256"] = _canonical_sha256(report)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(
            report, indent=2, ensure_ascii=False, allow_nan=False
        ).encode()
        descriptor = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as output:
            output.write(encoded)
            output.write(b"\n")
        print(
            json.dumps(
                {
                    "output": args.output.name,
                    "run_sha256": report["run_sha256"],
                    "requests": report["request_counts"],
                },
                sort_keys=True,
            )
        )
    except (OSError, RuntimeError, TypeError, ValueError) as error:
        print(f"phase2 development benchmark failed: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
