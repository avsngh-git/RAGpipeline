"""Terminal commands for index generations (``research-ingest generations ...``)."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any
from uuid import UUID

import asyncpg  # type: ignore[import-untyped]
import httpx

from research_platform.config import Settings
from research_platform.ingestion.embeddings import create_embedder_for_configuration
from research_platform.ingestion.generation_build import (
    GenerationInputRepository,
    QdrantDenseVectorSource,
    build_generation_passages,
)
from research_platform.ingestion.generation_index import (
    GenerationIndexConfiguration,
    GenerationQdrantCollection,
)
from research_platform.ingestion.generation_publication import (
    publish_generation,
    purge_retired,
    verify_generation,
)
from research_platform.ingestion.generation_registry import GenerationRegistry
from research_platform.ingestion.indexing import IndexConfiguration
from research_platform.ingestion.paper_index import PaperIndexRepository, sync_papers


def add_generation_commands(commands: Any) -> None:
    """Register the ``generations`` command group on the ingestion parser."""
    generations = commands.add_parser(
        "generations", help="build, verify and publish index generations"
    )
    subcommands = generations.add_subparsers(dest="generation_command", required=True)
    build = subcommands.add_parser(
        "build", help="build the next generation's passages from a finalized snapshot"
    )
    build.add_argument("--collection-name", required=True)
    build.add_argument("--snapshot-id", type=UUID, required=True)
    build.add_argument("--configuration", type=Path, required=True)
    build.add_argument(
        "--reuse-dense-configuration",
        type=Path,
        help="per-snapshot index configuration whose stored vectors are reused",
    )
    build.add_argument(
        "--reuse-dense-snapshot-id",
        type=UUID,
        help="snapshot whose per-snapshot points hold the vectors (default: --snapshot-id)",
    )
    sync = subcommands.add_parser(
        "sync-papers",
        help="upsert known papers and mark a generation's members as indexed",
    )
    sync.add_argument("--collection-name", required=True)
    sync.add_argument("--configuration", type=Path, required=True)
    sync.add_argument("--generation", type=int, required=True)
    for name, help_text in (
        ("verify", "check a built generation against its snapshot"),
        ("publish", "move the published pointer to a verified generation"),
    ):
        command = subcommands.add_parser(name, help=help_text)
        command.add_argument("--collection-name", required=True)
        command.add_argument("--configuration", type=Path, required=True)
        command.add_argument("--generation", type=int, required=True)
    purge = subcommands.add_parser(
        "purge", help="delete retired passages no readable generation can see"
    )
    purge.add_argument("--collection-name", required=True)
    purge.add_argument("--configuration", type=Path, required=True)
    purge.add_argument(
        "--apply", action="store_true", help="delete; without it only count"
    )
    for command in (build, sync):
        command.add_argument(
            "--device", choices=("auto", "cpu", "cuda"), default="auto"
        )
        command.add_argument("--precision", choices=("fp32", "fp16"), default="fp32")


def load_generation_configuration(path: Path) -> GenerationIndexConfiguration:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("generation configuration must be a JSON object")
    return GenerationIndexConfiguration.from_dict(raw)


async def execute_generation_command(
    args: argparse.Namespace, settings: Settings, pool: asyncpg.Pool
) -> None:
    configuration = load_generation_configuration(args.configuration)
    registry = GenerationRegistry(pool)
    collection_id = await registry.ensure_collection(args.collection_name)
    async with httpx.AsyncClient(
        base_url=settings.qdrant_url.rstrip("/"), timeout=60
    ) as http:
        if args.generation_command == "build":
            vector_source = None
            if args.reuse_dense_configuration is not None:
                stored = IndexConfiguration.from_dict(
                    json.loads(args.reuse_dense_configuration.read_text("utf-8"))
                )
                vector_source = QdrantDenseVectorSource(
                    http,
                    stored=stored,
                    expected=configuration.dense_configuration(),
                    snapshot_id=args.reuse_dense_snapshot_id or args.snapshot_id,
                )
            embedder = create_embedder_for_configuration(
                configuration.dense_configuration(),
                device=args.device,
                precision=args.precision,
            )
            try:
                report = await build_generation_passages(
                    registry=registry,
                    inputs=GenerationInputRepository(pool),
                    passages=GenerationQdrantCollection(
                        configuration, "passages", http
                    ),
                    embedder=embedder,
                    configuration=configuration,
                    collection_id=collection_id,
                    snapshot_id=args.snapshot_id,
                    vector_source=vector_source,
                )
            finally:
                embedder.close()
            print(json.dumps(asdict(report), indent=2, default=str))
        elif args.generation_command == "verify":
            verification = await verify_generation(
                registry=registry,
                inputs=GenerationInputRepository(pool),
                papers_repository=PaperIndexRepository(pool),
                passages=GenerationQdrantCollection(configuration, "passages", http),
                papers=GenerationQdrantCollection(configuration, "papers", http),
                collection_id=collection_id,
                configuration_id=configuration.configuration_id,
                generation=args.generation,
            )
            print(json.dumps(asdict(verification), indent=2))
        elif args.generation_command == "publish":
            await publish_generation(
                registry, collection_id, configuration.configuration_id, args.generation
            )
            print(json.dumps({"published_generation": args.generation}))
        elif args.generation_command == "purge":
            purged = await purge_retired(
                pool=pool,
                registry=registry,
                passages=GenerationQdrantCollection(configuration, "passages", http),
                collection_id=collection_id,
                configuration_id=configuration.configuration_id,
                dry_run=not args.apply,
            )
            print(json.dumps({"purgeable_points": purged, "deleted": args.apply}))
        elif args.generation_command == "sync-papers":
            record = await registry.get(
                collection_id, configuration.configuration_id, args.generation
            )
            embedder = create_embedder_for_configuration(
                configuration.dense_configuration(),
                device=args.device,
                precision=args.precision,
            )
            try:
                paper_report = await sync_papers(
                    repository=PaperIndexRepository(pool),
                    papers=GenerationQdrantCollection(configuration, "papers", http),
                    embedder=embedder,
                    configuration=configuration,
                    generation=record.generation,
                    snapshot_id=record.snapshot_id,
                )
            finally:
                embedder.close()
            print(json.dumps(asdict(paper_report), indent=2))
