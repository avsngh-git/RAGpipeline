"""Dry-run-by-default retention command."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Sequence

import asyncpg  # type: ignore[import-untyped]
import httpx

from research_platform.config import Settings
from research_platform.ingestion.generation_index import (
    GenerationIndexConfiguration,
    GenerationQdrantCollection,
)
from research_platform.ingestion.generation_publication import purge_retired
from research_platform.ingestion.generation_registry import GenerationRegistry
from research_platform.maintenance.retention import (
    RetentionPolicy,
    RetentionReport,
    delete_expired_llm_payloads,
    expired_checkpoint_runs,
    expired_llm_payloads,
    unpublished_generations,
)
from research_platform.runs.checkpointing import (
    delete_run_checkpoints,
    open_checkpointer,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="research-maintenance")
    commands = parser.add_subparsers(dest="command", required=True)
    retention = commands.add_parser("retention", help="apply data retention policy")
    retention.add_argument("--apply", action="store_true", help="delete eligible data")
    retention.add_argument("--collection-name")
    retention.add_argument("--configuration", type=Path)
    return parser


async def _execute(args: argparse.Namespace, settings: Settings) -> None:
    if bool(args.collection_name) != bool(args.configuration):
        raise ValueError(
            "--collection-name and --configuration must be provided together"
        )

    policy = RetentionPolicy()
    pool = await asyncpg.create_pool(settings.database_url, min_size=1, max_size=2)
    try:
        checkpoint_runs = await expired_checkpoint_runs(pool, policy)
        if args.apply:
            async with open_checkpointer(settings.database_url) as saver:
                for run_id in checkpoint_runs:
                    await delete_run_checkpoints(saver, run_id)

        llm_payloads = (
            await delete_expired_llm_payloads(pool, policy)
            if args.apply
            else await expired_llm_payloads(pool, policy)
        )

        retired_points: int | None = None
        if args.collection_name is not None and args.configuration is not None:
            configuration = GenerationIndexConfiguration.from_dict(
                json.loads(args.configuration.read_text(encoding="utf-8"))
            )
            registry = GenerationRegistry(pool)
            collection_id = await registry.ensure_collection(args.collection_name)
            async with httpx.AsyncClient(
                base_url=settings.qdrant_url.rstrip("/"), timeout=60
            ) as http:
                passages = GenerationQdrantCollection(configuration, "passages", http)
                retired_points = await purge_retired(
                    pool=pool,
                    registry=registry,
                    passages=passages,
                    collection_id=collection_id,
                    configuration_id=configuration.configuration_id,
                    dry_run=not args.apply,
                )

        report = RetentionReport(
            dry_run=not args.apply,
            checkpoint_runs=checkpoint_runs,
            llm_payloads=llm_payloads,
            retired_points=retired_points,
            unpublished_generations=await unpublished_generations(pool),
        )
        print(json.dumps(report.to_json(), indent=2))
    finally:
        await pool.close()


def main(argv: Sequence[str] | None = None) -> None:
    """Run the retention report or apply retention policy."""
    args = _parser().parse_args(argv)
    asyncio.run(_execute(args, Settings()))


if __name__ == "__main__":
    main()
