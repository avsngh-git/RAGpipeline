"""Lexical parity between BM25S profile v10 and Qdrant profile v10-qdrant (P35-15).

ADR-0022 item 7: ``v10-qdrant`` inherits the Phase 2 acceptance only if

1. lexical top-50 IDs and scores match BM25S, and ``eligible_count`` and
   ``available_count`` are equal, for the evidence and paper roles, on every
   development query (with its filters) and 200 sampled queries; and
2. end-to-end v10 rankings are identical in all four modes for the development queries.

The 2026-10-05 amendment to item 7 makes the lexical check tie-aware: results may be
ordered differently only where their scores agree within ``TIE_REL_TOLERANCE`` at every
position. Strict mismatch counts are still reported. ``--summarize-only`` recomputes
the summary from the saved private records.

Prints aggregate counts only. Per-query records go to
``local-reference/phase35/lexical-parity/`` because query text and evidence IDs are
private evaluation data.

    RESEARCH_PLATFORM_DATABASE_URL=... RESEARCH_PLATFORM_QDRANT_URL=... \\
    RESEARCH_PLATFORM_LEXICAL_INDEX_ROOT=... (model cache variables as for serving) \\
        python scripts/phase35_lexical_parity.py
"""

from __future__ import annotations

import asyncio
import json
import math
import random
import subprocess
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import asyncpg  # type: ignore[import-untyped]
import httpx
import tomllib

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "local-reference/phase35/lexical-parity"
MANIFESTS = ROOT / "benchmarks/phase2"
V10 = MANIFESTS / "frozen-profile-v10.toml"
V10_QDRANT = MANIFESTS / "frozen-profile-v10-qdrant.toml"
DENSE_GENERATION = ROOT / "configs/phase35-generation-index.example.json"
LEXICAL_GENERATION = ROOT / "configs/phase35-generation-index-lexical.example.json"
CALIBRATION = MANIFESTS / "calibration-v1.toml"
DEVELOPMENT_QUESTIONS = MANIFESTS / "benchmark-development-questions-v1.toml"
DEVELOPMENT_ALLOWLIST = MANIFESTS / "phase2-dev-input-allowlist-v1.json"
V13_DEVELOPMENT = (
    ROOT
    / "local-reference/phase2-runs/benchmark-v13-backup-20260929"
    / "calibration-v13-development.toml"
)
LEXICAL_LIMIT = 50
RESULT_LIMITS = (10, 50)
LEXICAL_REL_TOLERANCE = 1e-4
SCORE_TOLERANCE = 1e-6
# ADR-0022 item 7 as amended on 2026-10-05: results may be ordered differently only
# where their scores agree within this relative tolerance at every position.
TIE_REL_TOLERANCE = 1e-6
SAMPLE_COUNT = 200
SAMPLE_SEED = 35
SAMPLE_TOKENS = 12


@dataclass(frozen=True)
class RankComparison:
    """Whether two ranked lists agree and, if not, the kind of difference."""

    kind: str

    @property
    def equal(self) -> bool:
        return self.kind == "equal"


def compare_rank_lists(
    expected: Sequence[tuple[str, float]],
    actual: Sequence[tuple[str, float]],
    *,
    rel_tol: float,
    abs_tol: float = 0.0,
) -> RankComparison:
    """Compare ``(id, score)`` lists: IDs in order, scores within tolerance.

    Differences are classified as ``length``, ``score`` (same IDs, a score outside
    the tolerance), ``tie_order`` (same IDs and the same score at every position, so
    only equal-score items swapped), ``boundary_tie`` (the same score at every
    position but different IDs: equal-score items crossed the cut) or ``order``.
    """

    def close(a: float, b: float) -> bool:
        return math.isclose(a, b, rel_tol=rel_tol, abs_tol=abs_tol)

    expected_ids = [item for item, _ in expected]
    actual_ids = [item for item, _ in actual]
    if len(expected) != len(actual):
        return RankComparison("length")
    same_scores = all(
        close(a, b) for (_, a), (_, b) in zip(expected, actual, strict=True)
    )
    if expected_ids == actual_ids:
        return RankComparison("equal" if same_scores else "score")
    if not same_scores:
        return RankComparison("order")
    if sorted(expected_ids) == sorted(actual_ids):
        return RankComparison("tie_order")
    return RankComparison("boundary_tie")


def tie_aware_match(
    expected: Sequence[tuple[str, float]],
    actual: Sequence[tuple[str, float]],
    *,
    counts_equal: bool,
) -> bool:
    """Parity under ADR-0022 item 7: equal counts, and any reordering is a tie."""
    kind = compare_rank_lists(expected, actual, rel_tol=TIE_REL_TOLERANCE).kind
    return counts_equal and kind in {"equal", "tie_order", "boundary_tie"}


def sampled_queries(
    chunks: Sequence[tuple[str, str]],
    *,
    count: int = SAMPLE_COUNT,
    seed: int = SAMPLE_SEED,
    tokens: int = SAMPLE_TOKENS,
) -> list[tuple[str, str]]:
    """``(chunk_id, query)`` from the first words of chunks chosen by a fixed seed.

    Chunks are ordered by ID first, so the sample depends only on the chunk set.
    """
    ordered = sorted(chunks)
    chosen = random.Random(seed).sample(ordered, min(count, len(ordered)))
    return [(chunk_id, " ".join(text.split()[:tokens])) for chunk_id, text in chosen]


def _development_queries() -> list[tuple[str, str, Any]]:
    from research_platform.evaluation.calibration import load_calibration
    from research_platform.search.contracts import SearchFilters

    cases: list[tuple[str, str, Any]] = []
    for path in (CALIBRATION, V13_DEVELOPMENT):
        for family in load_calibration(path).families:
            for query in family.queries:
                cases.append((query.id, query.text, family.filters))
    allowlist = json.loads(DEVELOPMENT_ALLOWLIST.read_text(encoding="utf-8"))
    allowed = set(allowlist["reviewed_development"]["allowed_family_ids"])
    questions = tomllib.loads(DEVELOPMENT_QUESTIONS.read_text(encoding="utf-8"))
    for family in questions["families"]:
        if family["id"] not in allowed:
            continue
        filters = SearchFilters(**family.get("filters", {}))
        for query in family["queries"]:
            cases.append((query["id"], query["text"], filters))
    return cases


def _lexical_pairs(result: Any) -> list[tuple[str, float]]:
    return [(hit.stable_id, hit.score) for hit in result.hits]


def _component(component: Any) -> list[object] | None:
    return None if component is None else [component.rank, component.score]


def _scores(scores: Any) -> dict[str, list[object] | None]:
    return {
        name: _component(getattr(scores, name))
        for name in ("lexical", "dense", "fusion", "reranker")
    }


def _hit_record(hit: Any) -> dict[str, object]:
    record: dict[str, object] = {
        "id": getattr(hit, "chunk_id", None) or hit.paper_id,
        "rank": hit.rank,
        "scores": _scores(hit.component_scores),
    }
    supporting = getattr(hit, "supporting_evidence", None)
    if supporting is not None:
        record["supporting"] = [item.chunk_id for item in supporting]
    return record


def _response_record(response: Any) -> dict[str, object]:
    return {
        "effective_mode": response.effective_mode.value,
        "eligible_count": response.eligible_count,
        "result_status": response.result_status.value,
        "truncated": response.truncated,
        "omitted_count": response.omitted_count,
        "warnings": list(response.warnings),
        "hits": [_hit_record(hit) for hit in response.hits],
    }


def compare_responses(
    expected: Mapping[str, Any], actual: Mapping[str, Any]
) -> list[str]:
    """Kinds of difference between two end-to-end response records."""
    differences = [
        name
        for name in (
            "effective_mode",
            "eligible_count",
            "result_status",
            "truncated",
            "omitted_count",
            "warnings",
        )
        if expected[name] != actual[name]
    ]
    left, right = expected["hits"], actual["hits"]
    if [(h["id"], h["rank"]) for h in left] != [(h["id"], h["rank"]) for h in right]:
        return [*differences, "hit_order"]
    for want, got in zip(left, right, strict=True):
        if want.get("supporting") != got.get("supporting"):
            differences.append("supporting_evidence")
        for name, tolerance in (
            ("lexical", LEXICAL_REL_TOLERANCE),
            ("dense", SCORE_TOLERANCE),
            ("fusion", SCORE_TOLERANCE),
            ("reranker", 0.0),
        ):
            a, b = want["scores"][name], got["scores"][name]
            if a is None or b is None:
                if a != b:
                    differences.append(f"{name}_presence")
                continue
            if a[0] != b[0]:
                differences.append(f"{name}_rank")
            elif not math.isclose(
                float(a[1]),
                float(b[1]),
                rel_tol=tolerance,
                abs_tol=tolerance if name != "lexical" else 0.0,
            ):
                differences.append(f"{name}_score")
    return sorted(set(differences))


async def _lexical_parity(settings: Any) -> dict[str, Any]:
    from research_platform.ingestion.generation_index import (
        GenerationIndexConfiguration,
        GenerationQdrantCollection,
    )
    from research_platform.ingestion.generation_registry import GenerationRegistry
    from research_platform.search.application import (
        SnapshotEligibilityReader,
        _build_lexical_retrievers,
        _load_lexical_artifact,
        _resolve_serving_profiles,
    )
    from research_platform.search.contracts import SearchFilters
    from research_platform.search.lexical_branches import QdrantLexicalBranches
    from research_platform.search.sparse_lexical import VocabularyRepository

    v10 = _resolve_serving_profiles(V10)
    qdrant = _resolve_serving_profiles(V10_QDRANT)
    evidence, papers = _build_lexical_retrievers(
        v10,
        lambda profile, role: _load_lexical_artifact(
            settings.lexical_index_root, profile, role, mmap=True
        ),
    )
    configuration = GenerationIndexConfiguration.from_dict(
        json.loads(LEXICAL_GENERATION.read_text(encoding="utf-8"))
    )
    assert configuration.lexical is not None
    snapshot_id = v10.frozen.snapshot.snapshot_id
    pool = await asyncpg.create_pool(settings.database_url, min_size=1, max_size=4)
    records: list[dict[str, Any]] = []
    try:
        async with httpx.AsyncClient(
            base_url=settings.qdrant_url.rstrip("/"), timeout=120
        ) as http:
            record = await GenerationRegistry(pool).by_snapshot(
                configuration.configuration_id, snapshot_id
            )
            if record is None or record.state != "published":
                raise SystemExit("the lexical generation is not published")

            async def generation_for(_snapshot_id: object) -> int:
                return record.generation

            branches = QdrantLexicalBranches(
                passages=GenerationQdrantCollection(configuration, "passages", http),
                papers=GenerationQdrantCollection(configuration, "papers", http),
                vocabulary=VocabularyRepository(pool),
                settings=configuration.lexical,
                generation_for=generation_for,
            )
            pairs = (
                ("hybrid", v10.hybrid, qdrant.hybrid),
                ("bm25", v10.bm25, qdrant.bm25),
            )
            async with pool.acquire() as connection:
                rows = await connection.fetch(
                    "SELECT chunk.id, chunk.text FROM snapshot_item_chunks AS selected "
                    "JOIN chunks AS chunk ON chunk.id = selected.chunk_id "
                    "WHERE selected.snapshot_id = $1",
                    snapshot_id,
                )
            cases = [
                ("development", query_id, text, filters)
                for query_id, text, filters in _development_queries()
            ] + [
                ("sampled", chunk_id, text, SearchFilters())
                for chunk_id, text in sampled_queries(
                    [(str(row["id"]), str(row["text"])) for row in rows]
                )
            ]
            eligibility = SnapshotEligibilityReader(pool)
            for source, case_id, text, filters in cases:
                eligible = set(
                    (
                        await eligibility.read(snapshot_id, filters=filters)
                    ).paper_metadata
                )
                for artifact, old_profile, new_profile in pairs:
                    old_evidence = evidence[old_profile.profile_id]
                    new_evidence = await branches.evidence(new_profile)
                    old_paper = papers[old_profile.profile_id]
                    new_paper = await branches.paper(new_profile)
                    for role, want, got in (
                        (
                            "evidence",
                            old_evidence.search_with_stats(
                                text, limit=LEXICAL_LIMIT, filters=filters
                            ),
                            await new_evidence.search_with_stats(
                                text, limit=LEXICAL_LIMIT, filters=filters
                            ),
                        ),
                        (
                            "paper",
                            old_paper.search_with_stats(
                                text, eligible_ids=eligible, limit=LEXICAL_LIMIT
                            ),
                            await new_paper.search_with_stats(
                                text, eligible_ids=eligible, limit=LEXICAL_LIMIT
                            ),
                        ),
                    ):
                        comparison = compare_rank_lists(
                            _lexical_pairs(want),
                            _lexical_pairs(got),
                            rel_tol=LEXICAL_REL_TOLERANCE,
                        )
                        counts_equal = (
                            want.eligible_count,
                            want.available_count,
                            want.truncated,
                        ) == (got.eligible_count, got.available_count, got.truncated)
                        scores = [
                            abs(a - b) / max(abs(a), 1e-30)
                            for (_, a), (_, b) in zip(
                                _lexical_pairs(want), _lexical_pairs(got), strict=False
                            )
                        ]
                        records.append(
                            {
                                "source": source,
                                "case": case_id,
                                "artifact": artifact,
                                "role": role,
                                "kind": comparison.kind,
                                "counts_equal": counts_equal,
                                "returned": len(want.hits),
                                "max_relative_score_difference": max(
                                    scores, default=0.0
                                ),
                                "expected": _lexical_pairs(want),
                                "actual": _lexical_pairs(got),
                                "expected_counts": [
                                    want.eligible_count,
                                    want.available_count,
                                ],
                                "actual_counts": [
                                    got.eligible_count,
                                    got.available_count,
                                ],
                            }
                        )
    finally:
        await pool.close()
    sampled = [
        (case_id, text) for source, case_id, text, _ in cases if source == "sampled"
    ]
    return {"generation": record.generation, "records": records, "sampled": sampled}


# name, manifest, lexical engine, generation configuration. Both parity runs read the
# same dense collection, so the comparison isolates the lexical engine.
RUNS = (
    ("v10-serving", V10, "bm25s", DENSE_GENERATION),
    ("v10", V10, "bm25s", LEXICAL_GENERATION),
    ("v10-qdrant", V10_QDRANT, "qdrant", LEXICAL_GENERATION),
)
PARITY = ("v10", "v10-qdrant")
COLLECTION_EFFECT = ("v10-serving", "v10")
DIAGNOSTIC_MODES = ("hybrid", "reranked")
DIAGNOSTIC_LIMIT = 10


async def _end_to_end(
    settings: Any, sampled: Sequence[tuple[str, str]]
) -> dict[str, Any]:
    from research_platform.search.application import (
        _resolve_serving_profiles,
        create_phase2_runtime,
    )
    from research_platform.search.contracts import (
        RetrievalMode,
        SearchFilters,
        SearchOperation,
        SearchRequest,
    )

    development = _development_queries()
    diagnostic = [
        (chunk_id, text, SearchFilters()) for chunk_id, text in sampled if text.strip()
    ]
    results: dict[str, dict[str, Any]] = {}
    for name, manifest, engine, generation in RUNS:
        serving = _resolve_serving_profiles(manifest)
        runtime = await create_phase2_runtime(
            replace(
                settings,
                lexical_engine=engine,
                content_source="qdrant",
                generation_configuration=generation,
            ),
            frozen_profile_path=manifest,
        )
        responses: dict[str, Any] = {}

        async def run(
            source: str, profile: Any, mode: Any, operation: Any, limit: int, case: Any
        ) -> None:
            case_id, text, filters = case
            response = await runtime.api_services.search.execute(
                SearchRequest(
                    query=text,
                    snapshot_id=profile.snapshot.snapshot_id,
                    retrieval_profile_id=profile.profile_id,
                    mode=mode,
                    operation=operation,
                    filters=filters,
                    limit=limit,
                ),
                request_id=f"p35-15-{name}",
            )
            key = f"{source}|{mode.value}|{operation.value}|{limit}|{case_id}"
            responses[key] = _response_record(response)

        try:
            modes = (
                (serving.bm25, RetrievalMode.LEXICAL),
                (serving.dense, RetrievalMode.DENSE),
                (serving.hybrid, RetrievalMode.HYBRID),
                (serving.frozen, RetrievalMode.RERANKED),
            )
            operations = (SearchOperation.EVIDENCE_SEARCH, SearchOperation.PAPER_SEARCH)
            for profile, mode in modes:
                for operation in operations:
                    for limit in RESULT_LIMITS:
                        for case in development:
                            await run(
                                "development", profile, mode, operation, limit, case
                            )
                    if name in PARITY and mode.value in DIAGNOSTIC_MODES:
                        for case in diagnostic:
                            await run(
                                "sampled",
                                profile,
                                mode,
                                operation,
                                DIAGNOSTIC_LIMIT,
                                case,
                            )
        finally:
            await runtime.close()
        results[name] = responses

    def compare(pair: tuple[str, str]) -> list[dict[str, Any]]:
        left, right = results[pair[0]], results[pair[1]]
        rows = []
        for key, expected in left.items():
            if key not in right:
                continue
            source, mode, operation, limit, case_id = key.split("|")
            rows.append(
                {
                    "source": source,
                    "mode": mode,
                    "operation": operation,
                    "limit": int(limit),
                    "case": case_id,
                    "differences": compare_responses(expected, right[key]),
                }
            )
        return rows

    return {
        "responses": results,
        "parity": compare(PARITY),
        "collection_effect": compare(COLLECTION_EFFECT),
    }


def _summary(lexical: Mapping[str, Any], end_to_end: Mapping[str, Any]) -> dict:
    lexical_rows: dict[str, dict[str, Any]] = {}
    for record in lexical["records"]:
        key = f"{record['source']}|{record['artifact']}|{record['role']}"
        row = lexical_rows.setdefault(
            key,
            {
                "comparisons": 0,
                "mismatches": 0,
                "count_mismatches": 0,
                "kinds": Counter(),
                "max_relative_score_difference": 0.0,
                "returned_hits": 0,
                "tie_aware_mismatches": 0,
            },
        )
        row["tie_aware_mismatches"] += int(
            not tie_aware_match(
                record["expected"],
                record["actual"],
                counts_equal=record["counts_equal"],
            )
        )
        row["comparisons"] += 1
        row["mismatches"] += int(
            record["kind"] != "equal" or not record["counts_equal"]
        )
        row["count_mismatches"] += int(not record["counts_equal"])
        row["kinds"][record["kind"]] += 1
        row["returned_hits"] += record["returned"]
        row["max_relative_score_difference"] = max(
            row["max_relative_score_difference"],
            record["max_relative_score_difference"],
        )

    def table(rows: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
        grouped: dict[str, dict[str, Any]] = {}
        for comparison in rows:
            key = (
                f"{comparison['source']}|{comparison['mode']}|{comparison['operation']}"
            )
            row = grouped.setdefault(
                key, {"comparisons": 0, "mismatches": 0, "kinds": Counter()}
            )
            row["comparisons"] += 1
            row["mismatches"] += int(bool(comparison["differences"]))
            for kind in comparison["differences"]:
                row["kinds"][kind] += 1
        return {
            key: {**row, "kinds": dict(row["kinds"])}
            for key, row in sorted(grouped.items())
        }

    parity_rows = [r for r in end_to_end["parity"] if r["source"] == "development"]
    lexical_mismatches = sum(row["mismatches"] for row in lexical_rows.values())
    tie_aware = sum(row["tie_aware_mismatches"] for row in lexical_rows.values())
    e2e_mismatches = sum(bool(row["differences"]) for row in parity_rows)
    return {
        "generation": lexical["generation"],
        "development_queries": len(_development_queries()),
        "sampled_queries": SAMPLE_COUNT,
        "lexical": {
            key: {**row, "kinds": dict(row["kinds"])}
            for key, row in sorted(lexical_rows.items())
        },
        "end_to_end": table(parity_rows),
        "sampled_end_to_end_diagnostic": table(
            [r for r in end_to_end["parity"] if r["source"] == "sampled"]
        ),
        "dense_collection_effect": table(end_to_end["collection_effect"]),
        "tie_rel_tolerance": TIE_REL_TOLERANCE,
        "strict_lexical_mismatches": lexical_mismatches,
        "tie_aware_lexical_mismatches": tie_aware,
        "end_to_end_mismatches": e2e_mismatches,
        "parity_strict": (
            "pass" if lexical_mismatches == 0 and e2e_mismatches == 0 else "fail"
        ),
        "parity": "pass" if tie_aware == 0 and e2e_mismatches == 0 else "fail",
    }


def _private_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=1, default=str), encoding="utf-8")
    path.chmod(0o600)


async def main(summarize_only: bool) -> None:
    from research_platform.config import Settings

    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()
    if summarize_only:
        lexical = json.loads((OUTPUT / "lexical-records.json").read_text("utf-8"))
        end_to_end = json.loads((OUTPUT / "end-to-end.json").read_text("utf-8"))
        run_revision = json.loads((OUTPUT / "run.json").read_text("utf-8"))[
            "code_revision"
        ]
    else:
        settings = Settings()
        OUTPUT.mkdir(parents=True, exist_ok=True)
        lexical = await _lexical_parity(settings)
        _private_json(OUTPUT / "lexical-records.json", lexical)
        end_to_end = await _end_to_end(settings, lexical["sampled"])
        _private_json(OUTPUT / "end-to-end.json", end_to_end)
        run_revision = revision
        _private_json(OUTPUT / "run.json", {"code_revision": revision})
    summary = _summary(lexical, end_to_end)
    summary["run_code_revision"] = run_revision
    summary["summary_code_revision"] = revision
    _private_json(OUTPUT / "summary.json", summary)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--summarize-only",
        action="store_true",
        help="recompute the summary from the saved private records",
    )
    asyncio.run(main(parser.parse_args().summarize_only))
