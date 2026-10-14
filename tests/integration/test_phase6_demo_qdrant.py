"""Qdrant snapshot integration tests for public demo bundles."""

from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from research_platform.demo.database import DemoLoadRefused
from research_platform.demo.qdrant import export_collection, restore_collection

QDRANT_URL = os.environ.get("RESEARCH_PLATFORM_TEST_QDRANT_URL")
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not QDRANT_URL,
        reason="requires the dedicated disposable Qdrant service",
    ),
]


def test_snapshot_round_trip(tmp_path: Path) -> None:
    async def exercise() -> None:
        assert QDRANT_URL is not None
        collection = f"phase6-demo-{uuid4().hex}"
        async with httpx.AsyncClient(base_url=QDRANT_URL, timeout=600.0) as http:
            try:
                await _create_collection(http, collection)
                await _insert_points(http, collection)
                snapshot = tmp_path / f"{collection}.snapshot"
                checksum = await export_collection(http, collection, snapshot)
                await _delete_collection(http, collection)
                await restore_collection(http, collection, snapshot, sha256=checksum)
                assert await _point_count(http, collection) == 3
            finally:
                await _delete_collection(http, collection)

    import asyncio

    asyncio.run(exercise())


def test_restore_refuses_an_existing_collection(tmp_path: Path) -> None:
    async def exercise() -> None:
        assert QDRANT_URL is not None
        collection = f"phase6-demo-{uuid4().hex}"
        async with httpx.AsyncClient(base_url=QDRANT_URL, timeout=600.0) as http:
            try:
                await _create_collection(http, collection)
                snapshot = tmp_path / f"{collection}.snapshot"
                await _insert_points(http, collection)
                checksum = await export_collection(http, collection, snapshot)
                with pytest.raises(DemoLoadRefused):
                    await restore_collection(
                        http, collection, snapshot, sha256=checksum
                    )
            finally:
                await _delete_collection(http, collection)

    import asyncio

    asyncio.run(exercise())


def test_restore_refuses_a_wrong_checksum(tmp_path: Path) -> None:
    async def exercise() -> None:
        assert QDRANT_URL is not None
        collection = f"phase6-demo-{uuid4().hex}"
        snapshot = tmp_path / "snapshot.bin"
        snapshot.write_bytes(b"synthetic qdrant snapshot")
        async with httpx.AsyncClient(base_url=QDRANT_URL, timeout=600.0) as http:
            with pytest.raises(DemoLoadRefused):
                await restore_collection(
                    http, collection, snapshot, sha256="sha256:" + "0" * 64
                )
            response = await http.get(f"/collections/{collection}")
            assert response.status_code == 404

    import asyncio

    asyncio.run(exercise())


async def _create_collection(http: httpx.AsyncClient, collection: str) -> None:
    response = await http.put(
        f"/collections/{collection}",
        json={"vectors": {"dense": {"size": 4, "distance": "Cosine"}}},
    )
    response.raise_for_status()


async def _insert_points(http: httpx.AsyncClient, collection: str) -> None:
    response = await http.put(
        f"/collections/{collection}/points?wait=true",
        json={
            "points": [
                {"id": index, "vector": {"dense": [1.0, 0.0, 0.0, 0.0]}}
                for index in range(3)
            ]
        },
    )
    response.raise_for_status()


async def _point_count(http: httpx.AsyncClient, collection: str) -> int:
    response = await http.post(
        f"/collections/{collection}/points/count", json={"exact": True}
    )
    response.raise_for_status()
    return int(response.json()["result"]["count"])


async def _delete_collection(http: httpx.AsyncClient, collection: str) -> None:
    response = await http.delete(f"/collections/{collection}")
    if response.status_code != 404:
        response.raise_for_status()
