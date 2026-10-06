"""Gate A content and dense-ranking parity for Qdrant-served search (P35-10).

Compares, for the published generation of ``research-corpus``:

1. every evidence unit's search hit built from PostgreSQL hydration with the hit built
   from the Qdrant payload (floats compared with a 1e-12 relative tolerance);
2. exact dense search over the Phase 2 per-snapshot collection with exact dense search
   over the generation collection, for every development query and its filters; and
3. how far the Phase 2 approximate (HNSW) dense results were from exact search.

Prints aggregate counts only. Per-query results go to
``local-reference/phase35/content-parity/`` because query text and evidence IDs are
private evaluation data.

    RESEARCH_PLATFORM_DATABASE_URL=... RESEARCH_PLATFORM_QDRANT_URL=... \\
        python scripts/phase35_content_parity.py
"""

from __future__ import annotations

import asyncio
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any

import asyncpg  # type: ignore[import-untyped]
import httpx
import tomllib

from research_platform.config import Settings
from research_platform.ingestion.embeddings import create_embedder_for_configuration
from research_platform.ingestion.generation_index import (
    GenerationIndexConfiguration,
    GenerationQdrantCollection,
    generation_filter,
    with_conditions,
)
from research_platform.ingestion.generation_registry import GenerationRegistry
from research_platform.ingestion.indexing import (
    DENSE_FILTER_PAYLOAD_REVISION,
    IndexConfiguration,
    IndexMatch,
    IndexRepository,
)
from research_platform.search.application import _hit_and_source_unit
from research_platform.search.contracts import (
    ComponentScores,
    RankedComponent,
    SearchFilters,
)
from research_platform.search.dense_search import _qdrant_payload_conditions
from research_platform.search.generation_search import (
    PassageAuthorizer,
    QdrantContentReader,
)
from research_platform.search.profile_manifest import load_frozen_profile

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "local-reference/phase35/content-parity"
OLD_CONFIGURATION = ROOT / "configs/phase2-gte-modernbert-base-index.example.json"
QUESTION_FILES = (
    ROOT / "benchmarks/phase2/calibration-v1.toml",
    ROOT / "benchmarks/phase2/benchmark-development-questions-v1.toml",
)
BATCH = 200
DENSE_LIMIT = 50
FLOAT_TOLERANCE = 1e-12
SCORE_TOLERANCE = 1e-6


def _close(a: object, b: object) -> bool:
    if isinstance(a, float) and isinstance(b, float):
        return math.isclose(a, b, rel_tol=FLOAT_TOLERANCE, abs_tol=FLOAT_TOLERANCE)
    if isinstance(a, Mapping) and isinstance(b, Mapping):
        return a.keys() == b.keys() and all(_close(a[k], b[k]) for k in a)
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(_close(x, y) for x, y in zip(a, b, strict=True))
    return a == b


def _queries() -> list[tuple[str, str, SearchFilters]]:
    cases = []
    for path in QUESTION_FILES:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        for family in data["families"]:
            filters = SearchFilters(**family.get("filters", {}))
            for query in family["queries"]:
                cases.append((query["id"], query["text"], filters))
    return cases


async def _old_dense(
    http: httpx.AsyncClient,
    collection: str,
    snapshot_id: str,
    vector: Sequence[float],
    filters: SearchFilters,
    *,
    exact: bool,
) -> list[tuple[str, float]]:
    conditions = list(_qdrant_payload_conditions(filters))
    body: dict[str, Any] = {
        "query": list(vector),
        "filter": {
            "must": [
                {"key": "snapshot_id", "match": {"value": snapshot_id}},
                *conditions,
            ]
        },
        "limit": DENSE_LIMIT,
        "with_payload": ["evidence_id"],
    }
    if exact:
        body["params"] = {"exact": True}
    response = await http.post(f"/collections/{collection}/points/query", json=body)
    response.raise_for_status()
    return [
        (str(p["payload"]["evidence_id"]), float(p["score"]))
        for p in response.json()["result"]["points"]
    ]


def _same_ranking(a: list[tuple[str, float]], b: list[tuple[str, float]]) -> bool:
    """Equal IDs in order, allowing equal-score neighbours to swap."""
    if len(a) != len(b):
        return False
    if any(abs(x[1] - y[1]) > SCORE_TOLERANCE for x, y in zip(a, b, strict=True)):
        return False

    def key(item: tuple[str, float]) -> tuple[float, str]:
        return (-round(item[1], 6), item[0])

    return sorted(a, key=key) == sorted(b, key=key)


async def main() -> None:
    settings = Settings()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    frozen = load_frozen_profile(ROOT / "benchmarks/phase2/frozen-profile-v10.toml")
    configuration = GenerationIndexConfiguration.from_dict(
        json.loads(settings.generation_configuration.read_text(encoding="utf-8"))
    )
    old = IndexConfiguration.from_dict(json.loads(OLD_CONFIGURATION.read_text("utf-8")))
    pool = await asyncpg.create_pool(settings.database_url, min_size=1, max_size=4)
    async with httpx.AsyncClient(
        base_url=settings.qdrant_url.rstrip("/"), timeout=120
    ) as http:
        registry = GenerationRegistry(pool)
        collection_id = await registry.ensure_collection(settings.generation_collection)
        published = await registry.published(
            collection_id, configuration.configuration_id
        )
        if published is None or published.snapshot_id != frozen.snapshot.snapshot_id:
            raise SystemExit("generation 1 of the accepted snapshot is not published")
        passages = GenerationQdrantCollection(configuration, "passages", http)
        reader = QdrantContentReader(passages, PassageAuthorizer(pool), configuration)
        repository = IndexRepository(pool)
        selection = await repository.snapshot_selection_for(published.snapshot_id)
        async with pool.acquire() as connection:
            rows = await connection.fetch(
                "SELECT chunk_id FROM snapshot_item_chunks WHERE snapshot_id = $1 "
                "ORDER BY chunk_id",
                published.snapshot_id,
            )
        evidence_ids = [str(row["chunk_id"]) for row in rows]

        content_mismatches: list[str] = []
        scores = ComponentScores(dense=RankedComponent(rank=1, score=1.0))
        for start in range(0, len(evidence_ids), BATCH):
            batch = evidence_ids[start : start + BATCH]
            hydrated = await repository.hydrate_snapshot_matches(
                selection,
                old,
                [IndexMatch(evidence_id=e, score=0.0, payload={}) for e in batch],
            )
            served = await reader.read(
                published.snapshot_id, published.generation, batch
            )
            for pg, qd in zip(hydrated, served, strict=True):
                left = asdict(_hit_and_source_unit(pg, rank=1, scores=scores)[0])
                right = asdict(_hit_and_source_unit(qd, rank=1, scores=scores)[0])
                if pg.text != qd.text or not _close(left, right):
                    content_mismatches.append(pg.evidence_id)

        embedder = create_embedder_for_configuration(
            configuration.dense_configuration(), device=settings.model_device
        )
        dense_cases = []
        try:
            for query_id, text, filters in _queries():
                vector = await embedder.embed_query(
                    text, configuration=configuration.dense_configuration()
                )
                old_exact = await _old_dense(
                    http,
                    old.collection_name,
                    str(published.snapshot_id),
                    vector,
                    filters,
                    exact=True,
                )
                old_ann = await _old_dense(
                    http,
                    old.collection_name,
                    str(published.snapshot_id),
                    vector,
                    filters,
                    exact=False,
                )
                new_filter = with_conditions(
                    generation_filter(published.generation),
                    [
                        c
                        for c in _qdrant_payload_conditions(filters)
                        if c.get("key") != "filter_payload_revision"
                    ],
                )
                new_exact = [
                    (str(m.payload["evidence_id"]), m.score)
                    for m in await passages.query_dense(
                        vector, filter_=new_filter, limit=DENSE_LIMIT, exact=True
                    )
                ]
                dense_cases.append(
                    {
                        "query_id": query_id,
                        "exact_parity": _same_ranking(old_exact, new_exact),
                        "ann_top10_equal_exact": [i for i, _ in old_ann[:10]]
                        == [i for i, _ in old_exact[:10]],
                        "ann_overlap_at_50": len(
                            {i for i, _ in old_ann} & {i for i, _ in old_exact}
                        ),
                        "old_exact": old_exact,
                        "new_exact": new_exact,
                        "old_ann": old_ann,
                    }
                )
        finally:
            embedder.close()
    await pool.close()

    (OUTPUT / "dense-cases.json").write_text(json.dumps(dense_cases, indent=1))
    (OUTPUT / "content-mismatches.json").write_text(json.dumps(content_mismatches))
    summary = {
        "filter_payload_revision": DENSE_FILTER_PAYLOAD_REVISION,
        "evidence_units_compared": len(evidence_ids),
        "content_mismatches": len(content_mismatches),
        "dense_queries": len(dense_cases),
        "dense_exact_parity": sum(1 for c in dense_cases if c["exact_parity"]),
        "phase2_ann_top10_equal_to_exact": sum(
            1 for c in dense_cases if c["ann_top10_equal_exact"]
        ),
        "phase2_ann_mean_overlap_at_50": (
            sum(int(c["ann_overlap_at_50"]) for c in dense_cases) / len(dense_cases)
            if dense_cases
            else None
        ),
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
