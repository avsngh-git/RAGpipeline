"""Copy a ready Qdrant dense index and its registration between local stacks."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import cast
from urllib.parse import quote
from uuid import UUID

import asyncpg  # type: ignore[import-untyped]
import httpx

from research_platform.ingestion.indexing import (
    IndexConfiguration,
    IndexRepository,
)
from research_platform.ingestion.snapshot_selection import SnapshotSelection

logger = logging.getLogger("research_platform.phase2_copy_dense_index")
DEFAULT_COLLECTION = "phase2-dev-gte-modernbert-base-v1"
DEFAULT_SNAPSHOT_ID = UUID("4b11fab3-d4a5-4e7a-a58e-8654accf2c6c")
EXPECTED_POINT_COUNT = 44_277
PRIVATE_COPY_ROOT = (
    Path(__file__).resolve().parents[1] / "local-reference" / "phase2-index-copy"
)


class CopyRefused(RuntimeError):
    """The source and target do not satisfy the safe-copy preconditions."""


@dataclass(frozen=True)
class CopyPlan:
    """Validated, read-only details needed to copy one index."""

    snapshot_id: UUID
    collection_name: str
    configuration_id: str
    point_count: int
    state: Mapping[str, object]
    configuration: Mapping[str, object]


def build_copy_plan(
    *,
    snapshot_id: UUID,
    collection_name: str,
    source_selection: SnapshotSelection,
    target_selection: SnapshotSelection,
    source_configuration_id: str,
    source_configuration: Mapping[str, object],
    source_state: Mapping[str, object],
    target_configuration: Mapping[str, object] | None,
    target_state: Mapping[str, object] | None,
    target_collection_exists: bool,
) -> CopyPlan:
    """Validate copy invariants without touching either database or Qdrant."""
    if (
        source_selection != target_selection
        or source_selection.snapshot_id != snapshot_id
    ):
        raise CopyRefused("target snapshot selection differs from source")
    try:
        configuration = IndexConfiguration.from_dict(source_configuration)
    except (KeyError, TypeError, ValueError) as error:
        raise CopyRefused("source index configuration is invalid") from error
    if configuration.collection_name != collection_name:
        raise CopyRefused("source configuration belongs to a different collection")
    if configuration.configuration_id != source_configuration_id:
        raise CopyRefused("source configuration ID does not match its content")
    if source_state.get("status") != "ready":
        raise CopyRefused("source snapshot index is not ready")
    expected_count = source_state.get("expected_count")
    indexed_count = source_state.get("indexed_count")
    if (
        isinstance(expected_count, bool)
        or not isinstance(expected_count, int)
        or expected_count <= 0
        or isinstance(indexed_count, bool)
        or not isinstance(indexed_count, int)
        or indexed_count != expected_count
    ):
        raise CopyRefused("source index counts are incomplete or inconsistent")
    if collection_name == DEFAULT_COLLECTION and expected_count != EXPECTED_POINT_COUNT:
        raise CopyRefused("gte source index does not have the accepted point count")
    details = _as_json_object(source_state.get("details"), "source index details")
    ids_fingerprint = details.get("evidence_ids_sha256")
    if (
        not isinstance(ids_fingerprint, str)
        or details.get("qdrant_evidence_ids_sha256") != ids_fingerprint
    ):
        raise CopyRefused("source index evidence fingerprints do not agree")
    if target_configuration is not None and dict(target_configuration) != dict(
        source_configuration
    ):
        raise CopyRefused("target configuration ID already has different content")
    if target_state is not None:
        if not _states_match(target_state, source_state):
            raise CopyRefused(
                "target snapshot index state already has different content"
            )
        raise CopyRefused(
            "target snapshot index state already exists without its collection"
        )
    if target_collection_exists:
        raise CopyRefused("target Qdrant collection already exists")
    return CopyPlan(
        snapshot_id=snapshot_id,
        collection_name=collection_name,
        configuration_id=source_configuration_id,
        point_count=expected_count,
        state=dict(source_state),
        configuration=dict(source_configuration),
    )


def _as_json_object(value: object, name: str) -> dict[str, object]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as error:
            raise CopyRefused(f"{name} is not valid JSON") from error
    if not isinstance(value, dict):
        raise CopyRefused(f"{name} must be an object")
    return cast(dict[str, object], value)


def _states_match(left: Mapping[str, object], right: Mapping[str, object]) -> bool:
    fields = (
        "collection_name",
        "status",
        "expected_count",
        "indexed_count",
        "details",
    )
    return all(
        _normalized(left.get(field)) == _normalized(right.get(field))
        for field in fields
    )


def _normalized(value: object) -> object:
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return value
        if isinstance(parsed, dict):
            return parsed
    return value


async def _read_source(
    pool: asyncpg.Pool, snapshot_id: UUID, collection_name: str
) -> tuple[str, dict[str, object], dict[str, object], SnapshotSelection]:
    async with pool.acquire() as connection:
        rows = await connection.fetch(
            """
            SELECT configuration_id, configuration
            FROM index_configurations
            WHERE configuration ->> 'collection_name' = $1
            """,
            collection_name,
        )
        if len(rows) != 1:
            raise CopyRefused("source collection must have exactly one configuration")
        configuration_id = rows[0]["configuration_id"]
        configuration = _as_json_object(rows[0]["configuration"], "configuration")
        state_row = await connection.fetchrow(
            """
            SELECT collection_name, status, expected_count, indexed_count,
                   reconciled_at, details
            FROM snapshot_index_states
            WHERE snapshot_id = $1 AND configuration_id = $2
            """,
            snapshot_id,
            configuration_id,
        )
        if state_row is None:
            raise CopyRefused("source snapshot index state does not exist")
        state = dict(state_row)
        state["details"] = _as_json_object(state["details"], "source index details")
    selection = await IndexRepository(pool).snapshot_selection_for(snapshot_id)
    return configuration_id, configuration, state, selection


async def _read_target(
    pool: asyncpg.Pool, snapshot_id: UUID, configuration_id: str, collection_name: str
) -> tuple[dict[str, object] | None, dict[str, object] | None, SnapshotSelection]:
    async with pool.acquire() as connection:
        configuration_row = await connection.fetchrow(
            "SELECT configuration FROM index_configurations WHERE configuration_id = $1",
            configuration_id,
        )
        state_row = await connection.fetchrow(
            """
            SELECT collection_name, status, expected_count, indexed_count,
                   reconciled_at, details
            FROM snapshot_index_states
            WHERE snapshot_id = $1 AND configuration_id = $2
            """,
            snapshot_id,
            configuration_id,
        )
        owner = await connection.fetchval(
            """
            SELECT configuration_id FROM index_configurations
            WHERE configuration ->> 'collection_name' = $1
            """,
            collection_name,
        )
        if owner is not None and owner != configuration_id:
            raise CopyRefused("target collection name belongs to another configuration")
    target_configuration = (
        None
        if configuration_row is None
        else _as_json_object(configuration_row["configuration"], "target configuration")
    )
    target_state = None if state_row is None else dict(state_row)
    if target_state is not None:
        target_state["details"] = _as_json_object(
            target_state["details"], "target index details"
        )
    selection = await IndexRepository(pool).snapshot_selection_for(snapshot_id)
    return target_configuration, target_state, selection


async def _collection_exists(client: httpx.AsyncClient, collection: str) -> bool:
    response = await client.get(f"/collections/{quote(collection, safe='')}")
    if response.status_code == httpx.codes.NOT_FOUND:
        return False
    response.raise_for_status()
    return True


async def _point_count(client: httpx.AsyncClient, collection: str) -> int:
    response = await client.post(
        f"/collections/{quote(collection, safe='')}/points/count",
        json={"exact": True},
    )
    response.raise_for_status()
    body = response.json()
    result = body.get("result") if isinstance(body, dict) else None
    count = result.get("count") if isinstance(result, dict) else None
    if isinstance(count, bool) or not isinstance(count, int):
        raise CopyRefused("Qdrant returned an invalid point count")
    return count


async def _copy_snapshot(
    source: httpx.AsyncClient,
    target: httpx.AsyncClient,
    collection: str,
    destination: Path,
) -> str:
    collection_path = f"/collections/{quote(collection, safe='')}"
    create_response = await source.post(
        f"{collection_path}/snapshots", params={"wait": "true"}
    )
    create_response.raise_for_status()
    result = create_response.json().get("result", {})
    snapshot_name = result.get("name") if isinstance(result, dict) else None
    if not isinstance(snapshot_name, str) or not snapshot_name:
        raise CopyRefused("Qdrant did not return a snapshot name")
    snapshot_path = f"{collection_path}/snapshots/{quote(snapshot_name, safe='')}"
    target_recovered = False
    try:
        async with source.stream("GET", snapshot_path) as response:
            response.raise_for_status()
            with destination.open("wb") as snapshot_file:
                async for chunk in response.aiter_bytes():
                    snapshot_file.write(chunk)
        if not await _collection_exists(target, collection):
            with destination.open("rb") as snapshot_file:
                upload_response = await target.post(
                    f"{collection_path}/snapshots/upload",
                    params={"wait": "true"},
                    files={
                        "snapshot": (
                            snapshot_name,
                            snapshot_file,
                            "application/octet-stream",
                        )
                    },
                )
                upload_response.raise_for_status()
                target_recovered = True
        else:
            raise CopyRefused("target Qdrant collection appeared during copy")
    finally:
        try:
            delete_response = await source.delete(snapshot_path)
            delete_response.raise_for_status()
        except Exception:
            if target_recovered:
                await _delete_collection(target, collection)
            raise
    return snapshot_name


async def _register_target(
    pool: asyncpg.Pool, plan: CopyPlan, source_state: Mapping[str, object]
) -> None:
    async with pool.acquire() as connection:
        async with connection.transaction():
            owner = await connection.fetchval(
                """
                SELECT configuration_id FROM index_configurations
                WHERE configuration ->> 'collection_name' = $1
                FOR SHARE
                """,
                plan.collection_name,
            )
            if owner is not None and owner != plan.configuration_id:
                raise CopyRefused(
                    "target collection name belongs to another configuration"
                )
            await connection.execute(
                """
                INSERT INTO index_configurations (configuration_id, configuration)
                VALUES ($1, $2::jsonb)
                ON CONFLICT (configuration_id) DO NOTHING
                """,
                plan.configuration_id,
                json.dumps(plan.configuration, sort_keys=True),
            )
            stored_configuration = await connection.fetchval(
                "SELECT configuration::text FROM index_configurations WHERE configuration_id = $1",
                plan.configuration_id,
            )
            if _as_json_object(stored_configuration, "stored configuration") != dict(
                plan.configuration
            ):
                raise CopyRefused("target configuration ID conflicts with stored data")
            existing_state = await connection.fetchrow(
                """
                SELECT collection_name, status, expected_count, indexed_count, details
                FROM snapshot_index_states
                WHERE snapshot_id = $1 AND configuration_id = $2
                FOR UPDATE
                """,
                plan.snapshot_id,
                plan.configuration_id,
            )
            if existing_state is not None:
                existing = dict(existing_state)
                existing["details"] = _as_json_object(
                    existing["details"], "target details"
                )
                if not _states_match(existing, source_state):
                    raise CopyRefused(
                        "target snapshot index state conflicts with source"
                    )
                return
            await connection.execute(
                """
                INSERT INTO snapshot_index_states
                    (snapshot_id, configuration_id, collection_name, status,
                     expected_count, indexed_count, reconciled_at, details)
                VALUES ($1, $2, $3, 'ready', $4, $4, now(), $5::jsonb)
                """,
                plan.snapshot_id,
                plan.configuration_id,
                plan.collection_name,
                plan.point_count,
                json.dumps(source_state["details"], sort_keys=True),
            )


async def copy_dense_index(
    *,
    source_database_url: str,
    source_qdrant_url: str,
    target_database_url: str,
    target_qdrant_url: str,
    collection: str,
    snapshot_id: UUID,
    dry_run: bool,
) -> CopyPlan:
    """Validate, preview or copy one collection and register it in PostgreSQL."""
    source_pool = await asyncpg.create_pool(source_database_url, min_size=1, max_size=3)
    target_pool = await asyncpg.create_pool(target_database_url, min_size=1, max_size=3)
    timeout = httpx.Timeout(120.0, connect=10.0)
    async with (
        httpx.AsyncClient(
            base_url=source_qdrant_url.rstrip("/"), timeout=timeout
        ) as source,
        httpx.AsyncClient(
            base_url=target_qdrant_url.rstrip("/"), timeout=timeout
        ) as target,
    ):
        try:
            (
                configuration_id,
                configuration_data,
                state,
                source_selection,
            ) = await _read_source(source_pool, snapshot_id, collection)
            source_configuration = IndexConfiguration.from_dict(configuration_data)
            async with IndexRepository(source_pool).serving_index(
                source_selection, source_configuration
            ):
                (
                    target_configuration,
                    target_state,
                    target_selection,
                ) = await _read_target(
                    target_pool, snapshot_id, configuration_id, collection
                )
                source_exists = await _collection_exists(source, collection)
                if not source_exists:
                    raise CopyRefused("source Qdrant collection does not exist")
                target_exists = await _collection_exists(target, collection)
                source_count = await _point_count(source, collection)
                plan = build_copy_plan(
                    snapshot_id=snapshot_id,
                    collection_name=collection,
                    source_selection=source_selection,
                    target_selection=target_selection,
                    source_configuration_id=configuration_id,
                    source_configuration=configuration_data,
                    source_state=state,
                    target_configuration=target_configuration,
                    target_state=target_state,
                    target_collection_exists=target_exists,
                )
                if source_count != plan.point_count:
                    raise CopyRefused(
                        "source Qdrant point count differs from its ready database state"
                    )
                if dry_run:
                    return plan

                PRIVATE_COPY_ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
                with tempfile.TemporaryDirectory(
                    prefix="dense-index-", dir=PRIVATE_COPY_ROOT
                ) as temporary_directory:
                    snapshot_file = Path(temporary_directory) / "collection.snapshot"
                    await _copy_snapshot(source, target, collection, snapshot_file)
                target_count = await _point_count(target, collection)
                if target_count != plan.point_count:
                    await _delete_collection(target, collection)
                    raise CopyRefused("target Qdrant point count differs from source")
                await _register_target(target_pool, plan, state)
                async with IndexRepository(target_pool).serving_index(
                    target_selection, source_configuration
                ):
                    pass
                verified_count = await _point_count(target, collection)
                if verified_count != plan.point_count:
                    raise CopyRefused(
                        "target Qdrant point count changed during verification"
                    )
                return plan
        finally:
            await source_pool.close()
            await target_pool.close()


async def _delete_collection(client: httpx.AsyncClient, collection: str) -> None:
    response = await client.delete(f"/collections/{quote(collection, safe='')}")
    response.raise_for_status()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-database-url", required=True)
    parser.add_argument("--source-qdrant-url", required=True)
    parser.add_argument("--target-database-url", required=True)
    parser.add_argument("--target-qdrant-url", required=True)
    parser.add_argument("--collection", default=DEFAULT_COLLECTION)
    parser.add_argument("--snapshot-id", type=UUID, default=DEFAULT_SNAPSHOT_ID)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = _parse_args()
    try:
        plan = asyncio.run(
            copy_dense_index(
                source_database_url=args.source_database_url,
                source_qdrant_url=args.source_qdrant_url,
                target_database_url=args.target_database_url,
                target_qdrant_url=args.target_qdrant_url,
                collection=args.collection,
                snapshot_id=args.snapshot_id,
                dry_run=args.dry_run,
            )
        )
    except Exception as error:
        logger.error("Dense index copy refused or failed: %s", error)
        raise SystemExit(1) from None
    action = (
        "Would transfer and register" if args.dry_run else "Transferred and registered"
    )
    print(
        f"{action} {plan.collection_name}: {plan.point_count:,} points for snapshot "
        f"{plan.snapshot_id}; configuration {plan.configuration_id}."
    )


if __name__ == "__main__":
    main()
