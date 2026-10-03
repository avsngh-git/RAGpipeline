"""CLI commands for inspecting and pruning persisted research runs."""

from __future__ import annotations

import argparse
import asyncio
from datetime import timedelta
from typing import Sequence
from uuid import UUID

import asyncpg  # type: ignore[import-untyped]

from research_platform.config import Settings
from research_platform.runs.checkpointing import (
    delete_run_checkpoints,
    open_checkpointer,
)
from research_platform.runs.repository import RunRepository


def _positive_days(value: str) -> int:
    try:
        days = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("days must be a positive integer") from None
    if days < 1:
        raise argparse.ArgumentTypeError("days must be a positive integer")
    return days


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="research-runs")
    commands = parser.add_subparsers(dest="command", required=True)
    prune = commands.add_parser("prune", help="remove old terminal research runs")
    prune.add_argument("--older-than-days", type=_positive_days, required=True)
    show = commands.add_parser("show", help="print a persisted research run")
    show.add_argument("run_id", type=UUID)
    return parser


async def _execute(args: argparse.Namespace, settings: Settings) -> None:
    pool = await asyncpg.create_pool(settings.database_url, min_size=1, max_size=2)
    try:
        store = RunRepository(pool)
        if args.command == "show":
            view = await store.get_run_view(args.run_id)
            print(view.model_dump_json(indent=2))
            return

        async with open_checkpointer(settings.database_url) as saver:
            removed = await store.prune(older_than=timedelta(days=args.older_than_days))
            for run_id in removed:
                await delete_run_checkpoints(saver, run_id)
        print(len(removed))
    finally:
        await pool.close()


def main(argv: Sequence[str] | None = None) -> None:
    """Run a research run maintenance or inspection command."""
    args = _parser().parse_args(argv)
    asyncio.run(_execute(args, Settings()))


if __name__ == "__main__":
    main()
