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
    DenseVectorSource,
    GenerationDenseVectorSource,
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
from research_platform.ingestion.generation_rebuild import rebuild_generations
from research_platform.ingestion.generation_registry import GenerationRegistry
from research_platform.ingestion.indexing import IndexConfiguration
from research_platform.ingestion.paper_index import PaperIndexRepository, sync_papers
from research_platform.ingestion.sparse_build import (
    SparseEncoder,
    compute_lexical_averages,
)
from research_platform.search.sparse_lexical import VocabularyRepository


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
    rebuild = subcommands.add_parser(
        "rebuild",
        help="replay every published generation into empty collections and inspect",
    )
    rebuild.add_argument("--collection-name", required=True)
    rebuild.add_argument("--configuration", type=Path, required=True)
    purge = subcommands.add_parser(
        "purge", help="delete retired passages no readable generation can see"
    )
    purge.add_argument("--collection-name", required=True)
    purge.add_argument("--configuration", type=Path, required=True)
    purge.add_argument(
        "--apply", action="store_true", help="delete; without it only count"
    )
    lexical = subcommands.add_parser(
        "lexical-settings",
        help="print scientific BM25 settings with averages from a snapshot",
    )
    lexical.add_argument("--snapshot-id", type=UUID, required=True)
    for command in (build, rebuild):
        command.add_argument(
            "--reuse-dense-configuration",
            type=Path,
            help="per-snapshot index configuration whose stored vectors are reused",
        )
        command.add_argument(
            "--reuse-dense-snapshot-id",
            type=UUID,
            help="snapshot whose per-snapshot points hold the vectors",
        )
        command.add_argument(
            "--reuse-dense-generation-configuration",
            type=Path,
            help="generation configuration whose passage vectors are reused",
        )
    for command in (build, sync, rebuild):
        command.add_argument(
            "--device", choices=("auto", "cpu", "cuda"), default="auto"
        )
        command.add_argument("--precision", choices=("fp32", "fp16"), default="fp32")


def load_generation_configuration(path: Path) -> GenerationIndexConfiguration:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("generation configuration must be a JSON object")
    return GenerationIndexConfiguration.from_dict(raw)


def _vector_source(
    args: argparse.Namespace,
    configuration: GenerationIndexConfiguration,
    http: httpx.AsyncClient,
) -> DenseVectorSource | None:
    per_snapshot = args.reuse_dense_configuration
    generation = args.reuse_dense_generation_configuration
    if per_snapshot is not None and generation is not None:
        raise ValueError("choose one dense vector source")
    if generation is not None:
        source = load_generation_configuration(generation)
        return GenerationDenseVectorSource(
            GenerationQdrantCollection(source, "passages", http),
            expected=configuration.dense_configuration(),
        )
    if per_snapshot is not None:
        snapshot_id = args.reuse_dense_snapshot_id or getattr(args, "snapshot_id", None)
        if snapshot_id is None:
            raise ValueError("--reuse-dense-snapshot-id is required for reuse")
        return QdrantDenseVectorSource(
            http,
            stored=IndexConfiguration.from_dict(
                json.loads(per_snapshot.read_text("utf-8"))
            ),
            expected=configuration.dense_configuration(),
            snapshot_id=snapshot_id,
        )
    return None


async def _sparse_encoder(
    configuration: GenerationIndexConfiguration, pool: asyncpg.Pool
) -> SparseEncoder | None:
    if configuration.lexical is None:
        return None
    encoder = SparseEncoder(VocabularyRepository(pool), configuration.lexical)
    await encoder.prepare()
    return encoder


async def execute_generation_command(
    args: argparse.Namespace, settings: Settings, pool: asyncpg.Pool
) -> None:
    if args.generation_command == "lexical-settings":
        averages = await compute_lexical_averages(
            GenerationInputRepository(pool),
            PaperIndexRepository(pool),
            args.snapshot_id,
        )
        print(
            json.dumps(
                {
                    "lexical": averages.settings().to_dict(),
                    "evidence_document_count": averages.evidence_document_count,
                    "paper_document_count": averages.paper_document_count,
                },
                indent=2,
            )
        )
        return
    configuration = load_generation_configuration(args.configuration)
    registry = GenerationRegistry(pool)
    collection_id = await registry.ensure_collection(args.collection_name)
    async with httpx.AsyncClient(
        base_url=settings.qdrant_url.rstrip("/"), timeout=60
    ) as http:
        passages = GenerationQdrantCollection(configuration, "passages", http)
        papers = GenerationQdrantCollection(configuration, "papers", http)
        if args.generation_command in {"build", "sync-papers", "rebuild"}:
            embedder = create_embedder_for_configuration(
                configuration.dense_configuration(),
                device=args.device,
                precision=args.precision,
            )
            try:
                await _execute_embedding_command(
                    args,
                    pool=pool,
                    http=http,
                    registry=registry,
                    configuration=configuration,
                    collection_id=collection_id,
                    passages=passages,
                    papers=papers,
                    embedder=embedder,
                )
            finally:
                embedder.close()
        elif args.generation_command == "verify":
            verification = await verify_generation(
                registry=registry,
                inputs=GenerationInputRepository(pool),
                papers_repository=PaperIndexRepository(pool),
                passages=passages,
                papers=papers,
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
                passages=passages,
                collection_id=collection_id,
                configuration_id=configuration.configuration_id,
                dry_run=not args.apply,
            )
            print(json.dumps({"purgeable_points": purged, "deleted": args.apply}))


async def _execute_embedding_command(
    args: argparse.Namespace,
    *,
    pool: asyncpg.Pool,
    http: httpx.AsyncClient,
    registry: GenerationRegistry,
    configuration: GenerationIndexConfiguration,
    collection_id: UUID,
    passages: GenerationQdrantCollection,
    papers: GenerationQdrantCollection,
    embedder: Any,
) -> None:
    sparse_encoder = await _sparse_encoder(configuration, pool)
    if args.generation_command == "build":
        report = await build_generation_passages(
            registry=registry,
            inputs=GenerationInputRepository(pool),
            passages=passages,
            embedder=embedder,
            configuration=configuration,
            collection_id=collection_id,
            snapshot_id=args.snapshot_id,
            vector_source=_vector_source(args, configuration, http),
            sparse_encoder=sparse_encoder,
        )
        print(json.dumps(asdict(report), indent=2, default=str))
    elif args.generation_command == "sync-papers":
        record = await registry.get(
            collection_id, configuration.configuration_id, args.generation
        )
        paper_report = await sync_papers(
            repository=PaperIndexRepository(pool),
            papers=papers,
            embedder=embedder,
            configuration=configuration,
            generation=record.generation,
            snapshot_id=record.snapshot_id,
            sparse_encoder=sparse_encoder,
        )
        print(json.dumps(asdict(paper_report), indent=2))
    elif args.generation_command == "rebuild":
        rebuilt = await rebuild_generations(
            registry=registry,
            inputs=GenerationInputRepository(pool),
            papers_repository=PaperIndexRepository(pool),
            passages=passages,
            papers=papers,
            embedder=embedder,
            configuration=configuration,
            collection_id=collection_id,
            vector_source=_vector_source(args, configuration, http),
            sparse_encoder=sparse_encoder,
        )
        print(
            json.dumps(
                {
                    "passed": rebuilt.passed,
                    "builds": [asdict(build) for build in rebuilt.builds],
                    "inspections": [asdict(i) for i in rebuilt.inspections],
                },
                indent=2,
                default=str,
            )
        )
        if not rebuilt.passed:
            raise RuntimeError("rebuilt generations failed inspection")
