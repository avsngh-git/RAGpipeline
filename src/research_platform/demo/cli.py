"""Create, load and prepare public demo bundles."""

from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import sys
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Final
from urllib.parse import quote
from uuid import UUID

import asyncpg  # type: ignore[import-untyped]
import httpx
import tomllib

from research_platform.config import Settings
from research_platform.demo.bundle import (
    BUNDLE_FORMAT,
    attribution_rows,
    file_sha256,
    read_manifest,
    render_attribution,
    write_manifest,
)
from research_platform.demo.database import (
    DemoExportRefused,
    DemoLoadRefused,
    ExportedTable,
    export_tables,
    load_tables,
)
from research_platform.demo.qdrant import export_collection, restore_collection
from research_platform.ingestion.generation_index import GenerationIndexConfiguration
from research_platform.ingestion.provenance import code_revision
from research_platform.search.active_profile import resolve_frozen_profile_path

MODEL_ALLOW_PATTERNS: Final = (
    "*.json",
    "*.safetensors",
    "*.txt",
    "*.model",
    "tokenizer*",
    "1_Pooling/*",
)
MODEL_IGNORE_PATTERNS: Final = (
    "onnx/*",
    "openvino/*",
    "*.onnx",
    "*.bin",
    "*.ot",
    "*.msgpack",
    "*.h5",
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="research-demo")
    commands = parser.add_subparsers(dest="command", required=True)
    export = commands.add_parser("export", help="export a public demo bundle")
    export.add_argument("--snapshot-id", required=True, type=UUID)
    export.add_argument("--run-principal", required=True)
    export.add_argument("--output", required=True, type=Path)
    export.add_argument("--bundle-version", default="v2")
    load = commands.add_parser("load", help="load a demo bundle")
    load.add_argument("--bundle", required=True, type=Path)
    commands.add_parser("fetch-models", help="download the pinned local models")
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    """Run a demo bundle command."""
    args = _parser().parse_args(argv)
    try:
        asyncio.run(_execute(args, Settings()))
    except SystemExit:
        raise
    except (
        DemoExportRefused,
        DemoLoadRefused,
        asyncpg.PostgresError,
        httpx.HTTPError,
        OSError,
        ValueError,
        KeyError,
        TypeError,
    ) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1) from None


async def _execute(args: argparse.Namespace, settings: Settings) -> None:
    if args.command == "fetch-models":
        _fetch_models(settings)
    elif args.command == "export":
        await _export(args, settings)
    else:
        await _load(args, settings)


async def _export(args: argparse.Namespace, settings: Settings) -> None:
    if args.output.exists():
        raise DemoExportRefused("output directory already exists")
    if args.bundle_version != "v2":
        raise DemoExportRefused("unsupported bundle version")

    args.output.mkdir(parents=True)
    async with _connect(settings.database_url) as connection:
        tables = await export_tables(
            connection,
            snapshot_id=args.snapshot_id,
            run_principal=args.run_principal,
            bundle_dir=args.output,
        )
        config = _generation_configuration(settings.generation_configuration)
        qdrant_entries: list[dict[str, object]] = []
        async with httpx.AsyncClient(
            base_url=settings.qdrant_url.rstrip("/"), timeout=httpx.Timeout(600.0)
        ) as http:
            for collection in (
                config.passages_collection,
                config.papers_collection,
            ):
                path = args.output / "qdrant" / f"{collection}.snapshot"
                digest = await export_collection(http, collection, path)
                qdrant_entries.append(
                    {
                        "collection": collection,
                        "path": path.relative_to(args.output).as_posix(),
                        "sha256": digest,
                    }
                )

        attributions = await attribution_rows(connection, args.snapshot_id)
        attribution_path = args.output / "ATTRIBUTION.md"
        attribution_path.write_text(render_attribution(attributions), encoding="utf-8")
        profile = _active_profile()
        schema_version = await connection.fetchval(
            "SELECT max(version) FROM schema_migrations"
        )
        if schema_version is None:
            raise DemoExportRefused("database has no recorded schema version")
        generation = await connection.fetchval(
            """
            SELECT max(ig.generation)
            FROM index_generations AS ig
            JOIN collections AS collection ON collection.id = ig.collection_id
            WHERE collection.name = $1 AND ig.snapshot_id = $2
              AND ig.state = 'published'
            """,
            settings.generation_collection,
            args.snapshot_id,
        )
        if generation is None:
            raise DemoExportRefused("snapshot has no published index generation")
        runs = await connection.fetch(
            """
            SELECT id, mode, question, answer_outcome
            FROM research_runs
            WHERE snapshot_id = $1 AND principal = $2
              AND status IN ('completed', 'failed')
            ORDER BY created_at
            """,
            args.snapshot_id,
            args.run_principal,
        )

    manifest: dict[str, object] = {
        "format": BUNDLE_FORMAT,
        "bundle_version": args.bundle_version,
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "code_revision": code_revision(),
        "schema_version": schema_version,
        "snapshot_id": str(args.snapshot_id),
        "collection_name": settings.generation_collection,
        "generation": generation,
        "retrieval_profile_id": profile["profile_id"],
        "run_principal": args.run_principal,
        "models": [
            {
                "role": "embedding",
                "model": profile["embedding"]["model"],
                "revision": profile["embedding"]["revision"],
            },
            {
                "role": "reranker",
                "model": profile["reranker"]["model"],
                "revision": profile["reranker"]["revision"],
            },
        ],
        "runs": [
            {
                "run_id": str(run["id"]),
                "mode": run["mode"],
                "question": run["question"],
                "answer_outcome": run["answer_outcome"],
            }
            for run in runs
        ],
        "postgres": [
            {
                "name": table.name,
                "path": table.path,
                "rows": table.rows,
                "sha256": table.sha256,
            }
            for table in tables
        ],
        "qdrant": qdrant_entries,
        "attribution": {
            "path": "ATTRIBUTION.md",
            "sha256": file_sha256(attribution_path),
        },
    }
    write_manifest(args.output / "manifest.json", manifest)
    row_counts = {table.name: table.rows for table in tables}
    print(
        json.dumps(
            {
                "postgres_tables": len(tables),
                "postgres_rows": sum(row_counts.values()),
                "qdrant_collections": len(qdrant_entries),
                "runs": len(runs),
                "papers": len(attributions),
            }
        )
    )


async def _load(args: argparse.Namespace, settings: Settings) -> None:
    manifest = read_manifest(args.bundle / "manifest.json")
    attribution = _mapping(manifest.get("attribution"), "attribution")
    attribution_path = _bundle_file(args.bundle, attribution.get("path"))
    _verify_file(attribution_path, attribution.get("sha256"), "attribution")
    postgres = _manifest_tables(args.bundle, manifest.get("postgres"))
    qdrant = _manifest_qdrant(args.bundle, manifest.get("qdrant"))
    runs = manifest.get("runs")
    if not isinstance(runs, list):
        raise DemoLoadRefused("manifest runs are invalid")

    async with _connect(settings.database_url) as connection:
        schema_version = await _schema_version(connection)
        if schema_version != manifest.get("schema_version"):
            raise DemoLoadRefused("schema version differs; run research-migrate first")
        async with httpx.AsyncClient(
            base_url=settings.qdrant_url.rstrip("/"), timeout=httpx.Timeout(600.0)
        ) as http:
            for entry, _path in qdrant:
                collection = str(entry["collection"])
                response = await http.get(f"/collections/{quote(collection, safe='')}")
                if response.status_code == 200:
                    raise DemoLoadRefused(
                        f"Qdrant collection already exists: {collection}"
                    )
                if response.status_code != 404:
                    raise DemoLoadRefused("could not inspect target Qdrant collection")
            await load_tables(connection, bundle_dir=args.bundle, tables=postgres)
            for entry, path in qdrant:
                await restore_collection(
                    http,
                    str(entry["collection"]),
                    path,
                    sha256=str(entry["sha256"]),
                )
        snapshot_id = UUID(str(manifest.get("snapshot_id")))
        paper_count = await connection.fetchval(
            """
            SELECT count(DISTINCT document.paper_id)
            FROM snapshot_items AS item
            JOIN documents AS document ON document.id = item.document_id
            WHERE item.snapshot_id = $1
            """,
            snapshot_id,
        )
    print(
        json.dumps(
            {
                "postgres_tables": len(postgres),
                "postgres_rows": sum(table.rows for table in postgres),
                "qdrant_collections": len(qdrant),
                "runs": len(runs),
                "papers": paper_count,
            }
        )
    )


@asynccontextmanager
async def _connect(database_url: str) -> AsyncIterator[asyncpg.Connection]:
    connection = await asyncpg.connect(database_url)
    try:
        yield connection
    finally:
        await connection.close()


def _fetch_models(settings: Settings) -> None:
    profile = _active_profile()
    try:
        hub = importlib.import_module("huggingface_hub")
    except ModuleNotFoundError:
        print(
            "huggingface_hub is not installed; use the serving image", file=sys.stderr
        )
        raise SystemExit(2) from None

    downloaded: list[dict[str, str]] = []
    for role in ("embedding", "reranker"):
        model = profile[role]["model"]
        revision = profile[role]["revision"]
        options: dict[str, object] = {
            "repo_id": model,
            "revision": revision,
            "allow_patterns": list(MODEL_ALLOW_PATTERNS),
            "ignore_patterns": list(MODEL_IGNORE_PATTERNS),
        }
        if role == "reranker" and settings.reranker_cache_dir is not None:
            options["cache_dir"] = str(settings.reranker_cache_dir)
        snapshot_download = getattr(hub, "snapshot_download")
        snapshot_download(**options)
        downloaded.append({"role": role, "model": model, "revision": revision})
    print(json.dumps({"models": downloaded}))


async def _schema_version(connection: asyncpg.Connection) -> object:
    try:
        version = await connection.fetchval(
            "SELECT max(version) FROM schema_migrations"
        )
    except asyncpg.UndefinedTableError:
        raise DemoLoadRefused("run research-migrate first") from None
    if version is None:
        raise DemoLoadRefused("run research-migrate first")
    return version


def _generation_configuration(path: Path) -> GenerationIndexConfiguration:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, Mapping):
        raise ValueError("generation configuration must be a JSON object")
    return GenerationIndexConfiguration.from_dict(raw)


def _active_profile() -> dict[str, Any]:
    path = resolve_frozen_profile_path()
    profile = tomllib.loads(path.read_text(encoding="utf-8"))
    if not isinstance(profile.get("profile_id"), str):
        raise ValueError("active profile identity is missing")
    for role in ("embedding", "reranker"):
        model_config = profile.get(role)
        if not isinstance(model_config, dict) or not all(
            isinstance(model_config.get(field), str) for field in ("model", "revision")
        ):
            raise ValueError("active profile model identity is incomplete")
    return profile


def _manifest_tables(bundle: Path, value: object) -> tuple[ExportedTable, ...]:
    if not isinstance(value, list):
        raise DemoLoadRefused("manifest PostgreSQL entries are invalid")
    tables: list[ExportedTable] = []
    for item in value:
        entry = _mapping(item, "PostgreSQL entry")
        path = _bundle_file(bundle, entry.get("path"))
        name, rows, digest = entry.get("name"), entry.get("rows"), entry.get("sha256")
        if (
            not isinstance(name, str)
            or not isinstance(rows, int)
            or not isinstance(digest, str)
        ):
            raise DemoLoadRefused("manifest PostgreSQL entry is invalid")
        tables.append(
            ExportedTable(
                name=name,
                path=path.relative_to(bundle).as_posix(),
                rows=rows,
                sha256=digest,
            )
        )
    return tuple(tables)


def _manifest_qdrant(
    bundle: Path, value: object
) -> tuple[tuple[Mapping[str, object], Path], ...]:
    if not isinstance(value, list):
        raise DemoLoadRefused("manifest Qdrant entries are invalid")
    entries: list[tuple[Mapping[str, object], Path]] = []
    for item in value:
        entry = _mapping(item, "Qdrant entry")
        collection, digest = entry.get("collection"), entry.get("sha256")
        path = _bundle_file(bundle, entry.get("path"))
        if not isinstance(collection, str) or not isinstance(digest, str):
            raise DemoLoadRefused("manifest Qdrant entry is invalid")
        _verify_file(path, digest, "Qdrant snapshot")
        entries.append((entry, path))
    return tuple(entries)


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise DemoLoadRefused(f"manifest {name} is invalid")
    return value


def _bundle_file(bundle: Path, value: object) -> Path:
    if not isinstance(value, str):
        raise DemoLoadRefused("manifest file path is invalid")
    relative = PurePosixPath(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise DemoLoadRefused("manifest file path is invalid")
    root = bundle.resolve()
    path = root.joinpath(*relative.parts).resolve()
    if not path.is_relative_to(root):
        raise DemoLoadRefused("manifest file path is invalid")
    if not path.is_file():
        raise DemoLoadRefused("bundle file is missing")
    return path


def _verify_file(path: Path, expected: object, label: str) -> None:
    if not isinstance(expected, str) or file_sha256(path) != expected:
        raise DemoLoadRefused(f"{label} checksum mismatch")


if __name__ == "__main__":
    main()
