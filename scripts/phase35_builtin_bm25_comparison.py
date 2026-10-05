"""Development comparison arm: Qdrant's built-in ``Qdrant/bm25`` (P35-15 part 2).

ADR-0022 item 3 keeps the built-in encoder as a development comparison only; this
script changes no decision.

``build`` copies generation 1 of the lexical generation collection into
``research-passages-qdrant-bm25-v1`` with the same dense vectors and payloads and a
server-side ``bm25`` sparse vector (model ``qdrant/bm25``, defaults ``k=1.2`` and
``b=0.75``, IDF modifier). Each point's token count is solved from its smallest
stored weight, and points are re-encoded until ``avg_len`` equals the mean inferred
count (a fixed point). Encoding starts from ``avg_len`` 30, near the corpus mean,
because float32 weights give more precise counts when the average is small.

``evaluate`` scores the judged development families with the Phase 2 metrics. Each
arm changes only the passage lexical scorer: dense search, fusion code, reranking,
selection and paper-title lexical search are shared.

Prints aggregates only; per-query records go to
``local-reference/phase35/builtin-bm25/``.

    RESEARCH_PLATFORM_DATABASE_URL=... RESEARCH_PLATFORM_QDRANT_URL=... \\
    RESEARCH_PLATFORM_LEXICAL_INDEX_ROOT=... (model cache variables as for serving) \\
        python scripts/phase35_builtin_bm25_comparison.py {build,evaluate}
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import subprocess
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "local-reference/phase35/builtin-bm25"
MANIFESTS = ROOT / "benchmarks/phase2"
V10 = MANIFESTS / "frozen-profile-v10.toml"
LEXICAL_GENERATION = ROOT / "configs/phase35-generation-index-lexical.example.json"
TARGET = "research-passages-qdrant-bm25-v1"
VECTOR = "bm25"
MODEL = "qdrant/bm25"
K = 1.2
B = 0.75
FIRST_PASS_AVERAGE = 30.0
MAXIMUM_PASSES = 6
GENERATION = 1
PAGE = 256
TIE_MARGIN = 50
RESULT_LIMIT = 50
DATASETS = (
    (MANIFESTS / "calibration-v1.toml", MANIFESTS / "source-alignment-v1.toml"),
    (
        ROOT
        / "local-reference/phase2-runs/benchmark-v13-backup-20260929"
        / "calibration-v13-development.toml",
        ROOT
        / "local-reference/phase2-runs/benchmark-v13-backup-20260929"
        / "source-alignment-v13-development.toml",
    ),
)
METRICS = (
    "ndcg_at_10",
    "direct_mrr_at_10",
    "judged_recall_at_20",
    "judged_recall_at_50",
    "judgment_coverage",
)


def document_length(values: Sequence[float], average: float) -> float:
    """Token count implied by a document's smallest weight.

    The smallest weight belongs to the least frequent term; its count ``tf`` is the
    smallest one that gives a whole token count (usually 1).
    """
    if not values:
        return 0.0
    smallest = min(values)
    candidates = []
    for tf in range(1, 51):
        norm = tf * ((K + 1) / smallest - 1) / K
        length = (norm - (1 - B)) / B * average
        if length >= len(values) - 1e-6 and abs(length - round(length)) < 1e-4:
            return length
        candidates.append(length)
    return candidates[0]


def _document(text: str, average: float) -> dict[str, object]:
    return {"text": text, "model": MODEL, "options": {"avg_len": average}}


async def _pages(
    http: httpx.AsyncClient, collection: str, body: dict
) -> AsyncIterator[list[dict]]:
    offset: object = None
    while True:
        request = {**body, "limit": PAGE}
        if offset is not None:
            request["offset"] = offset
        response = await http.post(
            f"/collections/{collection}/points/scroll", json=request
        )
        response.raise_for_status()
        result = response.json()["result"]
        yield result["points"]
        offset = result.get("next_page_offset")
        if offset is None:
            return


async def _lengths(http: httpx.AsyncClient, average: float) -> dict[str, float]:
    lengths: dict[str, float] = {}
    body = {"with_payload": ["evidence_id"], "with_vector": [VECTOR]}
    async for page in _pages(http, TARGET, body):
        for point in page:
            values = point["vector"].get(VECTOR, {}).get("values", [])
            lengths[str(point["payload"]["evidence_id"])] = document_length(
                values, average
            )
    return lengths


async def build(settings: Any) -> dict[str, object]:
    from research_platform.ingestion.generation_index import (
        _PAYLOAD_INDEXES,
        GenerationIndexConfiguration,
        generation_filter,
    )

    configuration = GenerationIndexConfiguration.from_dict(
        json.loads(LEXICAL_GENERATION.read_text(encoding="utf-8"))
    )
    async with httpx.AsyncClient(
        base_url=settings.qdrant_url.rstrip("/"), timeout=300
    ) as http:
        await http.delete(f"/collections/{TARGET}")
        created = await http.put(
            f"/collections/{TARGET}",
            json={
                "vectors": {
                    "dense": {
                        "size": configuration.vector_size,
                        "distance": configuration.distance,
                    }
                },
                "sparse_vectors": {VECTOR: {"modifier": "idf"}},
            },
        )
        created.raise_for_status()
        for field_name, field_schema in _PAYLOAD_INDEXES["passages"]:
            indexed = await http.put(
                f"/collections/{TARGET}/index",
                params={"wait": "true"},
                json={"field_name": field_name, "field_schema": field_schema},
            )
            indexed.raise_for_status()
        source_points = 0
        source = {
            "filter": generation_filter(GENERATION),
            "with_payload": True,
            "with_vector": ["dense"],
        }
        async for page in _pages(http, configuration.passages_collection, source):
            source_points += len(page)
            response = await http.put(
                f"/collections/{TARGET}/points",
                params={"wait": "true"},
                json={
                    "points": [
                        {
                            "id": point["id"],
                            "vector": {
                                "dense": point["vector"]["dense"],
                                VECTOR: _document(
                                    str(point["payload"]["text"]), FIRST_PASS_AVERAGE
                                ),
                            },
                            "payload": point["payload"],
                        }
                        for point in page
                    ]
                },
            )
            response.raise_for_status()
        average = FIRST_PASS_AVERAGE
        passes: list[dict[str, float]] = []
        for _ in range(MAXIMUM_PASSES):
            lengths = await _lengths(http, average)
            inferred = sum(round(n) for n in lengths.values()) / len(lengths)
            passes.append(
                {
                    "encoded_average": average,
                    "inferred_average": inferred,
                    "non_integer_lengths": sum(
                        abs(n - round(n)) > 1e-4 for n in lengths.values()
                    ),
                }
            )
            if abs(inferred - average) < 1e-6:
                break
            average = inferred
            async for page in _pages(http, TARGET, {"with_payload": ["text"]}):
                response = await http.put(
                    f"/collections/{TARGET}/points/vectors",
                    params={"wait": "true"},
                    json={
                        "points": [
                            {
                                "id": point["id"],
                                "vector": {
                                    VECTOR: _document(
                                        str(point["payload"]["text"]), average
                                    )
                                },
                            }
                            for point in page
                        ]
                    },
                )
                response.raise_for_status()
        else:
            raise SystemExit("the average length did not converge")
        count = await http.post(
            f"/collections/{TARGET}/points/count", json={"exact": True}
        )
        count.raise_for_status()
    summary = {
        "collection": TARGET,
        "points": count.json()["result"]["count"],
        "source_points": source_points,
        "average_length": average,
        "passes": passes,
        "empty_documents": sum(n == 0 for n in lengths.values()),
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "build.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    return summary


class BuiltinEvidenceBranch:
    """Passage lexical search scored by the server-side ``Qdrant/bm25`` encoder."""

    def __init__(
        self,
        *,
        profile: Any,
        http: httpx.AsyncClient,
        average: float,
        candidate_limit: int,
    ) -> None:
        from research_platform.search.lexical_branches import LexicalBranchIdentity

        self._profile = profile
        self._http = http
        self._average = average
        self._identity = LexicalBranchIdentity(
            role="evidence",
            profile_id=profile.profile_id,
            snapshot=profile.snapshot,
            snapshot_status="finalized",
            candidate_limit=candidate_limit,
        )

    @property
    def profile(self) -> Any:
        return self._profile

    @property
    def identity(self) -> Any:
        return self._identity

    async def _query(self, query: str, filter_: dict, limit: int) -> list[tuple]:
        from research_platform.ingestion.generation_index import generation_filter

        response = await self._http.post(
            f"/collections/{TARGET}/points/query",
            json={
                "query": _document(query, self._average),
                "using": VECTOR,
                "filter": filter_,
                "params": {"idf": {"corpus": generation_filter(GENERATION)}},
                "limit": limit,
                "with_payload": ["evidence_id", "paper_id"],
            },
        )
        response.raise_for_status()
        return [
            (
                str(point["payload"]["evidence_id"]),
                str(point["payload"]["paper_id"]),
                float(point["score"]),
            )
            for point in response.json()["result"]["points"]
            if float(point["score"]) > 0
        ]

    async def search_with_stats(self, query: str, *, limit: int, filters: Any) -> Any:
        from research_platform.ingestion.generation_index import (
            generation_filter,
            with_conditions,
        )
        from research_platform.search.lexical import LexicalHit, LexicalSearchResult
        from research_platform.search.lexical_branches import generation_conditions

        base = with_conditions(
            generation_filter(GENERATION), generation_conditions(filters)
        )
        counted = await self._http.post(
            f"/collections/{TARGET}/points/count", json={"exact": True, "filter": base}
        )
        counted.raise_for_status()
        eligible = int(counted.json()["result"]["count"])
        available = len(await self._query(query, base, eligible)) if eligible else 0
        ranked: list[tuple] = []
        fetch = min(available, limit + TIE_MARGIN)
        while fetch:
            ranked = sorted(
                await self._query(query, base, fetch), key=lambda h: (-h[2], h[0])
            )
            if not (fetch < available and ranked[limit - 1][2] == ranked[-1][2]):
                break
            fetch = min(available, fetch * 2)
        return LexicalSearchResult(
            hits=tuple(
                LexicalHit(stable_id=e, paper_id=p, row=row, score=s)
                for row, (e, p, s) in enumerate(ranked[:limit])
            ),
            available_count=available,
            eligible_count=eligible,
            limit=limit,
            truncated=available > limit,
            applied_filters=filters,
        )


class _Proxy:
    def __init__(self, executor: Any, regions: dict[str, Any]) -> None:
        self.executor = executor
        self.regions = regions

    async def search(self, request: Any) -> Any:
        from research_platform.evaluation.matching import regions_from_search_hits
        from research_platform.search.contracts import SearchOperation

        response = await self.executor.execute(request, request_id=str(uuid4()))
        if request.operation is SearchOperation.EVIDENCE_SEARCH:
            self.regions.update(regions_from_search_hits(response.hits))
        return response


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def summarize(records: Sequence[Mapping[str, Any]]) -> dict[str, object]:
    """Macro means over queries that define each metric, with the query counts."""
    summary: dict[str, object] = {"queries": len(records)}
    for group in ("paper", "evidence"):
        for metric in METRICS:
            values = [
                r[group][metric]
                for r in records
                if r.get(group) is not None and r[group][metric] is not None
            ]
            summary[f"{group}_{metric}"] = sum(values) / len(values) if values else None
            summary[f"{group}_{metric}_queries"] = len(values)
    summary["failed_attempts"] = sum(r["failed_attempts"] for r in records)
    return summary


async def evaluate(settings: Any) -> dict[str, object]:
    from research_platform.evaluation.calibration import load_calibration
    from research_platform.evaluation.runner import (
        EvaluationOptions,
        evaluate_calibration,
    )
    from research_platform.evaluation.source_alignment import load_source_alignment
    from research_platform.search.application import (
        Phase2SearchExecutor,
        _bind_lexical_to_profile,
        _load_lexical_artifact,
        _resolve_serving_profiles,
        create_phase2_runtime,
    )
    from research_platform.search.contracts import RetrievalMode
    from research_platform.search.hybrid_search import HybridEvidenceSearch
    from research_platform.search.lexical import LexicalRetriever
    from research_platform.search.lexical_branches import (
        BM25SEvidenceBranch,
        BM25SPaperBranch,
    )
    from research_platform.search.profiles import LexicalIndexIdentity

    build_record = json.loads((OUTPUT / "build.json").read_text(encoding="utf-8"))
    average = float(build_record["average_length"])
    builtin_identity = LexicalIndexIdentity(
        implementation="qdrant-builtin-bm25",
        implementation_revision=f"qdrant-v1.19.1-k{K}-b{B}-avg{average:.6f}",
        analyzer=MODEL,
        analyzer_revision="qdrant-v1.19.1-default",
        normalization_revision="qdrant-bm25-default",
        index_format_revision="qdrant-server-side-bm25-v1",
    )
    serving = _resolve_serving_profiles(V10)
    hybrid_k60 = replace(
        serving.hybrid, fusion=replace(serving.hybrid.fusion, rank_constant=60)
    )
    arms = []
    for engine in ("scientific", "builtin"):
        for name, profile, mode in (
            ("lexical", serving.bm25, RetrievalMode.LEXICAL),
            ("hybrid_k10", serving.hybrid, RetrievalMode.HYBRID),
            ("hybrid_k60", hybrid_k60, RetrievalMode.HYBRID),
        ):
            if engine == "builtin":
                profile = replace(profile, lexical_index=builtin_identity)
            arms.append((f"{engine}_{name}", engine, profile, mode))

    runtime = await create_phase2_runtime(
        replace(
            settings,
            lexical_engine="bm25s",
            content_source="qdrant",
            generation_configuration=LEXICAL_GENERATION,
        ),
        frozen_profile_path=V10,
    )
    base = runtime.api_services.search
    root = settings.lexical_index_root
    results: dict[str, Any] = {}
    try:
        async with httpx.AsyncClient(
            base_url=settings.qdrant_url.rstrip("/"), timeout=120
        ) as http:
            for arm, engine, profile, mode in arms:
                source = (
                    serving.bm25 if mode is RetrievalMode.LEXICAL else serving.hybrid
                )
                artifact_profile = (
                    serving.bm25
                    if mode is RetrievalMode.LEXICAL
                    else serving.lexical_source
                )

                def retriever(role: str, bound: Any = profile) -> LexicalRetriever:
                    index = _load_lexical_artifact(
                        root, artifact_profile, role, mmap=True
                    )
                    return LexicalRetriever(_bind_lexical_to_profile(index, bound))

                limit = profile.candidate_limits.lexical_top_k
                evidence = (
                    BM25SEvidenceBranch(retriever("evidence"))
                    if engine == "scientific"
                    else BuiltinEvidenceBranch(
                        profile=profile,
                        http=http,
                        average=average,
                        candidate_limit=limit,
                    )
                )
                assert source.snapshot == profile.snapshot
                executor = Phase2SearchExecutor(
                    pool=base._pool,
                    index_configuration=base._configuration,
                    repository=base._repository,
                    eligibility_reader=base._eligibility,
                    profiles_by_id={profile.profile_id: profile},
                    modes_by_profile_id={profile.profile_id: mode},
                    lexical_evidence={profile.profile_id: evidence},
                    lexical_papers={
                        profile.profile_id: BM25SPaperBranch(retriever("paper"))
                    },
                    hybrid_profile=profile,
                    hybrid_search=HybridEvidenceSearch(evidence, base._dense),
                    dense_search=base._dense,
                    reranker=base._reranker,
                    evidence_repository=base._evidence_repository,
                )
                records: list[dict[str, Any]] = []
                for dataset_path, alignment_path in DATASETS:
                    dataset = load_calibration(dataset_path)
                    alignment = load_source_alignment(alignment_path, dataset)
                    eligible: dict[str, set[str]] = {}
                    for family in dataset.families:
                        availability = await base._eligibility.read(
                            dataset.snapshot_id, filters=family.filters
                        )
                        for query in family.queries:
                            eligible[query.id] = set(availability.paper_metadata)
                    regions: dict[str, Any] = {}
                    run = await evaluate_calibration(
                        _Proxy(executor, regions),
                        dataset,
                        alignment,
                        options=EvaluationOptions(
                            retrieval_profile_id=profile.profile_id,
                            mode=mode,
                            calibration_sha256=_sha256(dataset_path),
                            source_alignment_sha256=_sha256(alignment_path),
                            code_revision=_revision(),
                            limit=RESULT_LIMIT,
                            comparison_id=arm,
                        ),
                        regions_by_evidence_id=regions,
                        eligible_paper_ids_by_query=eligible,
                    )
                    for record in run:
                        score = record.score
                        records.append(
                            {
                                "family": record.family_id,
                                "query": record.query_id,
                                "failed_attempts": sum(
                                    a.status == "failed" for a in record.attempts
                                ),
                                **{
                                    group: None
                                    if score is None
                                    else {
                                        metric: getattr(
                                            getattr(score, group), metric
                                        ).value
                                        for metric in METRICS
                                    }
                                    for group in ("paper", "evidence")
                                },
                            }
                        )
                results[arm] = {
                    "profile_id": profile.profile_id,
                    "records": records,
                    "summary": summarize(records),
                }
    finally:
        await runtime.close()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    path = OUTPUT / "evaluation.json"
    path.write_text(json.dumps(results, indent=1), encoding="utf-8")
    path.chmod(0o600)
    return {arm: value["summary"] for arm, value in results.items()}


def _revision() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()


def main() -> None:
    from research_platform.config import Settings

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=("build", "evaluate"))
    arguments = parser.parse_args()
    settings = Settings()
    if arguments.command == "build":
        result = asyncio.run(build(settings))
    else:
        result = asyncio.run(evaluate(settings))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
