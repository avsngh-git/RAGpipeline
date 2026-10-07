"""Command line interface for evaluation experiments."""

from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Sequence
from uuid import UUID

import asyncpg  # type: ignore[import-untyped]

from research_platform.config import Settings
from research_platform.evaluation.experiments import (
    ExperimentRecord,
    PostgresExperimentStore,
)
from research_platform.evaluation.suites import SUITES
from research_platform.evaluation.suites.base import run_suite


def _option(value: str) -> tuple[str, str]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("options must use KEY=VALUE")
    key, option_value = value.split("=", 1)
    if not key:
        raise argparse.ArgumentTypeError("option keys must not be empty")
    return key, option_value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="research-eval")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="run an evaluation suite")
    run.add_argument("suite")
    run.add_argument("--option", action="append", type=_option, default=[])
    run.add_argument("--notes")
    listing = commands.add_parser("list", help="list evaluation experiments")
    listing.add_argument("--suite")
    listing.add_argument("--limit", type=_positive_limit, default=50)
    show = commands.add_parser("show", help="show an evaluation experiment")
    show.add_argument("experiment_id", type=UUID)
    return parser


def _positive_limit(value: str) -> int:
    try:
        limit = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("limit must be a positive integer") from None
    if limit < 1:
        raise argparse.ArgumentTypeError("limit must be a positive integer")
    return limit


def _record_json(record: ExperimentRecord) -> str:
    return record.model_dump_json()


async def _execute(args: argparse.Namespace, settings: Settings) -> None:
    if args.command == "run" and args.suite not in SUITES:
        raise SystemExit(f"unknown suite: {args.suite}")
    pool = await asyncpg.create_pool(settings.database_url, min_size=1, max_size=2)
    try:
        store = PostgresExperimentStore(pool)
        if args.command == "run":
            options = dict(args.option)
            record = await run_suite(
                SUITES[args.suite],
                store=store,
                settings=settings,
                options=options,
                notes=args.notes,
            )
            print(
                json.dumps(
                    {
                        "experiment_id": str(record.experiment_id),
                        "status": record.status.value,
                        "metrics": record.metrics,
                        "items_path": record.items_path,
                    }
                )
            )
        elif args.command == "list":
            records = await store.list(suite=args.suite, limit=args.limit)
            for record in records:
                print(
                    json.dumps(
                        {
                            "experiment_id": str(record.experiment_id),
                            "suite": record.suite,
                            "status": record.status.value,
                            "dataset_version": record.dataset_version,
                            "started_at": record.started_at.isoformat(),
                            "metrics": record.metrics,
                        }
                    )
                )
        else:
            record = await store.get(args.experiment_id)
            print(record.model_dump_json(indent=2))
    finally:
        await pool.close()


def main(argv: Sequence[str] | None = None) -> None:
    """Run an evaluation suite or inspect persisted experiments."""
    args = _parser().parse_args(argv)
    asyncio.run(_execute(args, Settings()))


if __name__ == "__main__":
    main()
