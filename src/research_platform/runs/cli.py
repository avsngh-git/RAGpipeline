"""CLI commands for inspecting and pruning persisted research runs."""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict
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
from research_platform.runs.reproduce import (
    check_run,
    inputs_from_configuration,
    reproduction_recipe,
)


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
    reproduce = commands.add_parser(
        "reproduce", help="check and print a research run reproduction recipe"
    )
    reproduce.add_argument("run_id", type=UUID)
    reproduce.add_argument("--json", action="store_true")
    return parser


async def _execute(args: argparse.Namespace, settings: Settings) -> None:
    pool = await asyncpg.create_pool(settings.database_url, min_size=1, max_size=2)
    try:
        store = RunRepository(pool)
        if args.command == "show":
            view = await store.get_run_view(args.run_id)
            print(view.model_dump_json(indent=2))
            return

        if args.command == "reproduce":
            check = await check_run(store, args.run_id)
            output: dict[str, object] = {"check": asdict(check)}
            if check.stored_configuration_found:
                view = await store.get_run_view(args.run_id)
                if view.provenance is None:
                    raise RuntimeError("run has no provenance")
                configuration = await store.load_run_configuration(
                    view.provenance.configuration_id
                )
                inputs = inputs_from_configuration(view.question, configuration)
                output["recipe"] = reproduction_recipe(inputs)
            if args.json:
                print(json.dumps(output, indent=2, default=str))
            else:
                print("Reproduction check:")
                print(json.dumps(asdict(check), indent=2, default=str))
                if "recipe" in output:
                    print("Reproduction recipe:")
                    print(json.dumps(output["recipe"], indent=2, default=str))
            if not check.hash_matches or not check.rebuilt_matches:
                raise SystemExit(1)
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
