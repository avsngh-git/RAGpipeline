"""Qdrant snapshot export and restore for public demo bundles."""

from __future__ import annotations

import hashlib
from pathlib import Path
from urllib.parse import quote

import httpx

from research_platform.demo.database import DemoLoadRefused


async def export_collection(
    http: httpx.AsyncClient, collection: str, destination: Path
) -> str:
    """Snapshot a collection into destination and return its sha256."""
    name = quote(collection, safe="")
    response = await http.post(
        f"/collections/{name}/snapshots", params={"wait": "true"}
    )
    response.raise_for_status()
    snapshot = response.json()["result"]["name"]
    snapshot_path = f"/collections/{name}/snapshots/{quote(snapshot, safe='')}"
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        async with http.stream("GET", snapshot_path) as download:
            download.raise_for_status()
            with destination.open("wb") as output:
                async for chunk in download.aiter_bytes():
                    output.write(chunk)
    finally:
        deleted = await http.delete(snapshot_path, params={"wait": "true"})
        deleted.raise_for_status()

    digest = hashlib.sha256()
    with destination.open("rb") as snapshot_file:
        for block in iter(lambda: snapshot_file.read(1024 * 1024), b""):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


async def restore_collection(
    http: httpx.AsyncClient, collection: str, source: Path, *, sha256: str
) -> None:
    """Restore a collection from a snapshot file; refuse if it exists or differs."""
    digest = hashlib.sha256()
    with source.open("rb") as snapshot_file:
        for block in iter(lambda: snapshot_file.read(1024 * 1024), b""):
            digest.update(block)
    if sha256 != "sha256:" + digest.hexdigest():
        raise DemoLoadRefused("Qdrant snapshot checksum mismatch")

    name = quote(collection, safe="")
    existing = await http.get(f"/collections/{name}")
    if existing.status_code == 200:
        raise DemoLoadRefused(f"Qdrant collection already exists: {collection}")
    if existing.status_code != 404:
        raise DemoLoadRefused("could not inspect target Qdrant collection")

    with source.open("rb") as snapshot:
        response = await http.post(
            f"/collections/{name}/snapshots/upload",
            params={"priority": "snapshot", "wait": "true"},
            files={"snapshot": (source.name, snapshot, "application/octet-stream")},
        )
    if not response.is_success:
        raise DemoLoadRefused("Qdrant snapshot restore failed")
