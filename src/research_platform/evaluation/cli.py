"""Command line interface for evaluation experiments."""

from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Sequence
from pathlib import Path
from uuid import UUID

import asyncpg  # type: ignore[import-untyped]

from research_platform.config import Settings
from research_platform.evaluation.compare import compare_experiments, render_markdown
from research_platform.evaluation.experiments import (
    PostgresExperimentStore,
    canonical_repository_root,
    read_items,
)
from research_platform.evaluation.suites import SUITES
from research_platform.evaluation.suites.base import run_suite
from research_platform.runs.diagnosis import diagnose, load_diagnosis_inputs
from research_platform.runs.repository import RunNotFound, RunRepository


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
    compare = commands.add_parser(
        "compare", help="compare two experiments of the same suite and dataset"
    )
    compare.add_argument("baseline_id", type=UUID)
    compare.add_argument("candidate_id", type=UUID)
    compare.add_argument("--output", type=Path)
    compare.add_argument("--with-stages", action="store_true")
    return parser


def _positive_limit(value: str) -> int:
    try:
        limit = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("limit must be a positive integer") from None
    if limit < 1:
        raise argparse.ArgumentTypeError("limit must be a positive integer")
    return limit


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
        elif args.command == "show":
            record = await store.get(args.experiment_id)
            print(record.model_dump_json(indent=2))
        else:
            baseline = await store.get(args.baseline_id)
            candidate = await store.get(args.candidate_id)
            baseline_items = read_items(Path(baseline.items_path))
            candidate_items = read_items(Path(candidate.items_path))
            stages: dict[str, str] | None = None
            if args.with_stages:
                stages = {}
                run_ids = {
                    run_id
                    for item in (*baseline_items, *candidate_items)
                    if isinstance((run_id := item.get("run_id")), str) and run_id
                }
                run_store = RunRepository(pool)
                for run_id in sorted(run_ids):
                    try:
                        inputs = await load_diagnosis_inputs(run_store, UUID(run_id))
                    except RunNotFound:
                        continue
                    stages[run_id] = diagnose(inputs).stage.value

            comparison = compare_experiments(
                baseline,
                candidate,
                baseline_items,
                candidate_items,
                stages=stages,
            )
            markdown = render_markdown(comparison)
            if args.output is None:
                print(markdown, end="")
            else:
                root = canonical_repository_root()
                local_reference = (root / "local-reference").resolve()
                output_path = args.output
                if not output_path.is_absolute():
                    output_path = root / output_path
                output_path = output_path.resolve()
                if output_path == local_reference or not output_path.is_relative_to(
                    local_reference
                ):
                    raise SystemExit(
                        "output path must be inside the canonical local-reference directory"
                    )
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_text(markdown, encoding="utf-8")
    finally:
        await pool.close()


def main(argv: Sequence[str] | None = None) -> None:
    """Run an evaluation suite or inspect persisted experiments."""
    args = _parser().parse_args(argv)
    asyncio.run(_execute(args, Settings()))


if __name__ == "__main__":
    main()
