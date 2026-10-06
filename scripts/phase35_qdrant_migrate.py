"""Copy Qdrant collections between servers through a local export (P35-03).

Qdrant only guarantees storage compatibility across one minor version, so Phase 3.5
moves local collections to a new server version by export and import instead of an
in-place upgrade. Every collection is rebuildable from PostgreSQL; this copy only saves
the embedding time.

    python scripts/phase35_qdrant_migrate.py export --url http://127.0.0.1:6333 \
        --directory local-reference/phase35/qdrant-export
    python scripts/phase35_qdrant_migrate.py import --url http://127.0.0.1:6333 \
        --directory local-reference/phase35/qdrant-export

The export directory holds one ``<collection>.jsonl.gz`` file of points (vectors and
payloads), plus ``manifest.json`` with each collection's vector configuration, payload
index schema, exact point count, content digest and probe results. Import recreates
each missing collection, upserts the points, then checks the exact count, the content
digest and the probe queries. The export contains private evidence text: keep it under
``local-reference/``.
"""

from __future__ import annotations

import argparse
import asyncio
import gzip
import hashlib
import json
from collections.abc import AsyncIterator, Mapping
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
import numpy as np

SCROLL_PAGE = 512
UPSERT_BATCH = 256
PROBE_COUNT = 3
PROBE_LIMIT = 10
VECTOR_TOLERANCE = 1e-6
PROBE_SCORE_TOLERANCE = 1e-5


def _collection_url(name: str) -> str:
    return "/collections/" + quote(name, safe="")


async def _call(
    http: httpx.AsyncClient, method: str, path: str, body: object | None = None
) -> Any:
    response = await http.request(method, path, json=body)
    if response.status_code >= 400:
        raise RuntimeError(
            f"{method} {path} -> {response.status_code}: {response.text}"
        )
    return response.json()["result"]


async def _scroll(http: httpx.AsyncClient, name: str) -> AsyncIterator[dict[str, Any]]:
    offset: object = None
    while True:
        body: dict[str, object] = {
            "limit": SCROLL_PAGE,
            "with_payload": True,
            "with_vector": True,
        }
        if offset is not None:
            body["offset"] = offset
        result = await _call(
            http, "POST", f"{_collection_url(name)}/points/scroll", body
        )
        for point in result["points"]:
            yield {
                "id": point["id"],
                "vector": point["vector"],
                "payload": point.get("payload") or {},
            }
        offset = result.get("next_page_offset")
        if offset is None:
            return


def _point_line(point: Mapping[str, Any]) -> str:
    return json.dumps(point, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _identity_line(point: Mapping[str, Any]) -> str:
    """Canonical ID and payload; vectors are compared separately with a tolerance."""
    return json.dumps(
        {"id": point["id"], "payload": point["payload"]},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _digest(lines: list[str]) -> str:
    """Order-independent digest of canonical point lines."""
    return hashlib.sha256("\n".join(sorted(lines)).encode("utf-8")).hexdigest()


def _vector_array(vector: object) -> np.ndarray:
    if not isinstance(vector, list):
        raise RuntimeError("only unnamed dense vectors are supported by this copy")
    return np.asarray(vector, dtype=np.float32)


async def _count(http: httpx.AsyncClient, name: str) -> int:
    result = await _call(
        http, "POST", f"{_collection_url(name)}/points/count", {"exact": True}
    )
    return int(result["count"])


async def _probe(
    http: httpx.AsyncClient, name: str, vectors: list[Any]
) -> list[list[list[Any]]]:
    """Exact top results as ``[id, score]`` pairs for each probe vector."""
    results = []
    for vector in vectors:
        body: dict[str, object] = {
            "limit": PROBE_LIMIT,
            "with_payload": False,
            "params": {"exact": True},
        }
        if isinstance(vector, dict):
            using, value = sorted(vector.items())[0]
            body.update({"query": value, "using": using})
        else:
            body["query"] = vector
        result = await _call(
            http, "POST", f"{_collection_url(name)}/points/query", body
        )
        results.append(
            [[str(point["id"]), float(point["score"])] for point in result["points"]]
        )
    return results


def _probes_agree(
    observed: list[list[list[Any]]], expected: list[list[list[Any]]]
) -> bool:
    """Compare scores rank by rank, and IDs only above the last returned score.

    Equal scores may be returned in any order, and ties at the cut-off may select
    different points, so tied IDs at the boundary are not compared.
    """
    if len(observed) != len(expected):
        return False
    for got, want in zip(observed, expected, strict=True):
        if len(got) != len(want):
            return False
        if any(
            abs(a[1] - b[1]) > PROBE_SCORE_TOLERANCE
            for a, b in zip(got, want, strict=True)
        ):
            return False
        if want:
            cutoff = want[-1][1] + PROBE_SCORE_TOLERANCE
            if {i for i, score in got if score > cutoff} != {
                i for i, score in want if score > cutoff
            }:
                return False
    return True


async def export(url: str, directory: Path, names: list[str] | None) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, object] = {}
    async with httpx.AsyncClient(base_url=url, timeout=120) as http:
        server = (await http.get("/")).json()["version"]
        listed = await _call(http, "GET", "/collections")
        selected = names or sorted(c["name"] for c in listed["collections"])
        for name in selected:
            info = await _call(http, "GET", _collection_url(name))
            lines: list[str] = []
            identities: list[str] = []
            path = directory / f"{name}.jsonl.gz"
            with gzip.open(path, "wt", encoding="utf-8") as handle:
                async for point in _scroll(http, name):
                    line = _point_line(point)
                    lines.append(line)
                    identities.append(_identity_line(point))
                    handle.write(line + "\n")
            count = await _count(http, name)
            if count != len(lines):
                raise RuntimeError(f"{name}: exported {len(lines)} of {count} points")
            ordered = sorted(lines)
            step = max(1, len(ordered) // PROBE_COUNT)
            probe_vectors = [
                json.loads(line)["vector"] for line in ordered[::step][:PROBE_COUNT]
            ]
            manifest[name] = {
                "params": info["config"]["params"],
                "payload_schema": {
                    field: schema.get("data_type")
                    for field, schema in info.get("payload_schema", {}).items()
                },
                "count": count,
                "digest": _digest(identities),
                "probe_vectors": probe_vectors,
                "probe_results": await _probe(http, name, probe_vectors),
            }
            print(f"exported {name}: {count} points")
    (directory / "manifest.json").write_text(
        json.dumps({"server": server, "collections": manifest}, indent=1),
        encoding="utf-8",
    )


async def import_(url: str, directory: Path, names: list[str] | None) -> None:
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    collections: dict[str, Any] = manifest["collections"]
    failures = []
    async with httpx.AsyncClient(base_url=url, timeout=120) as http:
        for name in names or sorted(collections):
            entry = collections[name]
            exists = (await http.get(_collection_url(name))).status_code == 200
            if exists:
                raise RuntimeError(f"{name} already exists on the target; refusing")
            params = entry["params"]
            create: dict[str, object] = {"vectors": params["vectors"]}
            for key in ("sparse_vectors", "on_disk_payload", "shard_number"):
                if key in params:
                    create[key] = params[key]
            await _call(http, "PUT", _collection_url(name), create)
            for field, schema in sorted(entry["payload_schema"].items()):
                await _call(
                    http,
                    "PUT",
                    f"{_collection_url(name)}/index?wait=true",
                    {"field_name": field, "field_schema": schema},
                )
            batch: list[dict[str, Any]] = []
            with gzip.open(
                directory / f"{name}.jsonl.gz", "rt", encoding="utf-8"
            ) as fh:
                for line in fh:
                    batch.append(json.loads(line))
                    if len(batch) == UPSERT_BATCH:
                        await _call(
                            http,
                            "PUT",
                            f"{_collection_url(name)}/points?wait=true",
                            {"points": batch},
                        )
                        batch = []
            if batch:
                await _call(
                    http,
                    "PUT",
                    f"{_collection_url(name)}/points?wait=true",
                    {"points": batch},
                )
            source_vectors: dict[str, np.ndarray] = {}
            with gzip.open(
                directory / f"{name}.jsonl.gz", "rt", encoding="utf-8"
            ) as fh:
                for line in fh:
                    point = json.loads(line)
                    source_vectors[str(point["id"])] = _vector_array(point["vector"])
            identities: list[str] = []
            max_vector_diff = 0.0
            async for point in _scroll(http, name):
                identities.append(_identity_line(point))
                source = source_vectors.pop(str(point["id"]), None)
                target = _vector_array(point["vector"])
                if source is None or source.shape != target.shape:
                    max_vector_diff = float("inf")
                    continue
                max_vector_diff = max(
                    max_vector_diff, float(np.max(np.abs(source - target)))
                )
            count = await _count(http, name)
            probes = await _probe(http, name, entry["probe_vectors"])
            checks = {
                "count": count == entry["count"],
                "digest": _digest(identities) == entry["digest"],
                "vectors": not source_vectors and max_vector_diff <= VECTOR_TOLERANCE,
                "probes": _probes_agree(probes, entry["probe_results"]),
            }
            print(f"imported {name}: {count} points; checks {checks}")
            if not all(checks.values()):
                failures.append(name)
    if failures:
        raise SystemExit(f"verification failed for: {', '.join(failures)}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("export", "import"))
    parser.add_argument("--url", required=True)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--collection", action="append", dest="collections")
    args = parser.parse_args()
    if args.command == "export":
        asyncio.run(export(args.url, args.directory, args.collections))
    else:
        asyncio.run(import_(args.url, args.directory, args.collections))


if __name__ == "__main__":
    main()
