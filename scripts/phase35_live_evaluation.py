"""Gate D live evaluation on the leave-out corpus (P35-29).

Starts the host API and the online ingestion worker against the leave-out corpus
(collection ``leave-out-dev``), runs every selected leave-out development family as
``deep_research`` sequentially with the default budgets, and measures:

- the share of ingestion-triggering runs that finish within the wait cap (gate: at
  least 90%);
- failure categories (gate: every failed run has one);
- hidden papers ingested, metadata-only and failed outcomes by reason, spend, answer
  outcomes and GPU peak memory (reported).

Run from the repository root after sourcing the private environment (database,
Qdrant, model caches, ``RESEARCH_PLATFORM_GENERATION_COLLECTION=leave-out-dev``,
``RESEARCH_PLATFORM_GENERATION_CONFIGURATION`` for the leave-out configuration and
``RESEARCH_PLATFORM_INGESTION_HANDLER=online``)::

    python scripts/phase35_live_evaluation.py

``--forced-ingestion`` measures the operational path when the model does not trigger
it: the first plan of each run is scripted to ``discover_papers`` with the question
and ``request_ingestion`` for the family's hidden papers; evaluation, synthesis, the
membership policy, the worker, ingestion, publication, waiting and the generation
switch are all real. Results are reported separately from the natural runs.

Question text, answers and per-run records stay under
``local-reference/phase35/live/``; the summary holds aggregates only.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import subprocess
import sys
import threading
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import asyncpg  # type: ignore[import-untyped]
import httpx

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = ROOT / "local-reference/phase3-runs/dev-tasks-v1.json"
BUILD_RECORD = ROOT / "local-reference/phase35/leaveout-dev-build.json"
OUTPUT_ROOT = ROOT / "local-reference/phase35/live"
WAIT_CAP_GATE = 0.90
TERMINAL = {"completed", "failed"}


class GpuSampler:
    """Track peak GPU memory with ``nvidia-smi`` once per second."""

    def __init__(self) -> None:
        self.peak_mib = 0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def __enter__(self) -> GpuSampler:
        self._thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self._stop.set()
        self._thread.join(timeout=5)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                output = subprocess.run(
                    [
                        "nvidia-smi",
                        "--query-gpu=memory.used",
                        "--format=csv,noheader,nounits",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=True,
                ).stdout
                self.peak_mib = max(self.peak_mib, int(output.split()[0]))
            except (OSError, subprocess.SubprocessError, ValueError, IndexError):
                pass
            self._stop.wait(1.0)


def selected_tasks(dataset: Path) -> tuple[dict[str, Any], ...]:
    """The leave-out families: development tasks with direct-evidence judgments."""
    sys.path.insert(0, str(ROOT))
    from scripts.phase35_build_leave_out import _load_tasks

    return _load_tasks(dataset)


def summarize(runs: list[dict[str, Any]], hidden: set[str]) -> dict[str, Any]:
    """Aggregate per-run records into the Gate D measures."""
    triggering = [run for run in runs if run["ingestion_requests"]]
    within_cap = [
        run
        for run in triggering
        if any(
            call["tool_name"] == "ingestion_wait" and call["status"] == "succeeded"
            for call in run["tool_calls"]
        )
    ]
    failed = [run for run in runs if run["status"] == "failed"]
    outcomes = [
        outcome
        for run in runs
        for request in run["ingestion_requests"]
        for outcome in request.get("result", {}).get("outcomes", [])
    ]
    decisions = Counter(
        decision["reason"] for run in runs for decision in run["decisions"]
    )
    tool_counts = Counter(
        call["tool_name"] for run in runs for call in run["tool_calls"]
    )
    share = len(within_cap) / len(triggering) if triggering else None
    return {
        "runs": len(runs),
        "completed": sum(run["status"] == "completed" for run in runs),
        "failed": len(failed),
        "failed_with_category": sum(bool(run["failure_category"]) for run in failed),
        "failure_categories": dict(Counter(run["failure_category"] for run in failed)),
        "ingestion_triggering_runs": len(triggering),
        "ingestion_runs_within_wait_cap": len(within_cap),
        "within_wait_cap_share": share,
        "wait_cap_gate": (
            "not measurable"
            if share is None
            else "pass"
            if share >= WAIT_CAP_GATE
            else "fail"
        ),
        "failure_category_gate": "pass"
        if all(run["failure_category"] for run in failed)
        else "fail",
        "generation_switches": sum(
            any(
                call["tool_name"] == "ingestion_wait"
                and call["result"].get("to_generation")
                != call["result"].get("from_generation")
                for call in run["tool_calls"]
            )
            for run in runs
        ),
        "hidden_papers_ingested": sorted(
            {
                outcome["paper_id"]
                for outcome in outcomes
                if outcome.get("status") == "ingested"
                and outcome.get("paper_id") in hidden
            }
        ),
        "ingested_papers": sum(o.get("status") == "ingested" for o in outcomes),
        "outcomes_by_status_and_reason": dict(
            Counter(f"{o.get('status')}:{o.get('reason')}" for o in outcomes)
        ),
        "membership_decisions_by_reason": dict(decisions),
        "tool_calls_by_name": dict(tool_counts),
        "answer_outcomes": dict(
            Counter(run["answer_outcome"] for run in runs if run["answer_outcome"])
        ),
    }


async def _run_records(pool: asyncpg.Pool, run_id: UUID) -> dict[str, Any]:
    async with pool.acquire() as connection:
        calls = await connection.fetch(
            "SELECT ordinal, tool_name, status, error_category, result "
            "FROM tool_calls WHERE run_id = $1 ORDER BY ordinal",
            run_id,
        )
        requests = await connection.fetch(
            "SELECT id, paper_ids, status, attempts, result, created_at, updated_at "
            "FROM ingestion_requests WHERE run_id = $1 ORDER BY created_at",
            run_id,
        )
        decisions = await connection.fetch(
            "SELECT paper_id, decision, reason FROM ingestion_decisions "
            "WHERE run_id = $1 ORDER BY id",
            run_id,
        )
    return {
        "tool_calls": [
            {
                "ordinal": row["ordinal"],
                "tool_name": row["tool_name"],
                "status": row["status"],
                "error_category": row["error_category"],
                "result": _json(row["result"]),
            }
            for row in calls
        ],
        "ingestion_requests": [
            {
                "id": str(row["id"]),
                "paper_ids": list(row["paper_ids"]),
                "status": row["status"],
                "attempts": row["attempts"],
                "result": _json(row["result"]),
                "seconds": (row["updated_at"] - row["created_at"]).total_seconds(),
            }
            for row in requests
        ],
        "decisions": [dict(row) for row in decisions],
    }


def _json(value: object) -> dict[str, Any]:
    if isinstance(value, str):
        value = json.loads(value)
    return value if isinstance(value, dict) else {}


class ForcedPlanLLM:
    """Script only the next plan call; everything else uses the live model."""

    def __init__(self, inner: Any, holder: dict[str, Any]) -> None:
        self._inner = inner
        self._holder = holder

    async def identity(self) -> Any:
        return await self._inner.identity()

    async def generate(self, call: Any) -> Any:
        return await self._inner.generate(call)

    async def call_tools(self, request: Any) -> Any:
        from research_platform.llm.contracts import ToolCallResult

        calls = self._holder.pop("calls", None)
        if calls is None:
            return await self._inner.call_tools(request)
        return ToolCallResult(
            calls=tuple(calls),
            thinking=None,
            prompt_tokens=None,
            output_tokens=None,
            duration_ms=0.0,
            attempts=1,
        )


def forced_calls(task: dict[str, Any], hidden: set[str]) -> list[dict[str, Any]]:
    """The scripted first plan: discover, then request the family's hidden papers."""
    papers = sorted(set(task["judged_paper_ids"]) & hidden)[:5]
    calls: list[dict[str, Any]] = [
        {
            "function": {
                "name": "discover_papers",
                "arguments": {"query": str(task["question"])[:300], "limit": 10},
            }
        }
    ]
    if papers:
        calls.append(
            {
                "function": {
                    "name": "request_ingestion",
                    "arguments": {"paper_ids": papers, "reason": "forced evaluation"},
                }
            }
        )
    return calls


async def _forced_runs(
    tasks: tuple[dict[str, Any], ...],
    hidden: set[str],
    output: Path,
    run_timeout: float,
) -> list[dict[str, Any]]:
    from contextlib import AsyncExitStack

    from research_platform.api import app as app_module
    from research_platform.config import Settings
    from research_platform.llm import ollama
    from research_platform.runs.contracts import ResearchMode, ResearchRequest
    from research_platform.search.application import create_phase2_runtime

    holder: dict[str, Any] = {}
    original = ollama.OllamaClient.from_settings

    def patched(http: Any, settings: Any) -> Any:
        return ForcedPlanLLM(original(http, settings), holder)

    ollama.OllamaClient.from_settings = staticmethod(patched)  # type: ignore[method-assign]
    settings = Settings()
    runtime = await create_phase2_runtime(settings)
    runs: list[dict[str, Any]] = []
    try:
        async with AsyncExitStack() as stack:
            services = await app_module._build_research_services(
                settings, runtime, stack
            )
            for task in tasks:
                holder["calls"] = forced_calls(task, hidden)
                request = ResearchRequest.model_validate(
                    {
                        "question": task["question"],
                        "mode": ResearchMode.DEEP_RESEARCH.value,
                        **({"filters": task["filters"]} if task.get("filters") else {}),
                    }
                )
                run_id = await services.store.create_run(request)
                await services.executor.submit(run_id)
                begun = time.monotonic()
                view = await services.store.get_run_view(run_id)
                while view.status.value not in TERMINAL:
                    if time.monotonic() - begun > run_timeout:
                        break
                    await asyncio.sleep(10)
                    view = await services.store.get_run_view(run_id)
                runs.append(
                    await _record(
                        task,
                        run_id,
                        view.model_dump(mode="json"),
                        begun,
                        runtime.pool,
                        output,
                    )
                )
    finally:
        await runtime.close()
        ollama.OllamaClient.from_settings = original  # type: ignore[method-assign]
    return runs


async def _record(
    task: dict[str, Any],
    run_id: UUID,
    view: dict[str, Any],
    begun: float,
    pool: asyncpg.Pool,
    output: Path,
) -> dict[str, Any]:
    record = {
        "task_id": task["task_id"],
        "run_id": str(run_id),
        "status": view["status"],
        "failure_category": view.get("failure_category"),
        "answer_outcome": view.get("answer_outcome"),
        "generation": view.get("generation"),
        "starting_generation": (view.get("provenance") or {}).get("generation"),
        "seconds": round(time.monotonic() - begun, 1),
        **await _run_records(pool, run_id),
    }
    with (output / "runs.jsonl").open("a") as handle:
        handle.write(json.dumps({**record, "view": view}, default=str) + "\n")
    print(
        f"{record['status']} {record['seconds']}s generation "
        f"{record['starting_generation']}->{record['generation']}",
        flush=True,
    )
    return record


async def _wait_ready(client: httpx.AsyncClient, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if (await client.get("/ready")).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        await asyncio.sleep(2)
    raise SystemExit("the API did not become ready")


async def evaluate(args: argparse.Namespace) -> dict[str, Any]:
    tasks = selected_tasks(args.dataset)
    if args.limit:
        tasks = tasks[: args.limit]
    hidden = set(json.loads(BUILD_RECORD.read_text("utf-8"))["hidden_paper_ids"])
    output = OUTPUT_ROOT / datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output.mkdir(parents=True, exist_ok=True)
    started_at = datetime.now(UTC)
    environment = dict(os.environ)
    api_log = (output / "api.log").open("w")
    worker_log = (output / "worker.log").open("w")
    api = (
        None
        if args.forced_ingestion
        else subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "research_platform.api.app:create_app",
                "--factory",
                "--host",
                "127.0.0.1",
                "--port",
                str(args.port),
            ],
            env=environment,
            stdout=api_log,
            stderr=api_log,
        )
    )
    worker = subprocess.Popen(
        ["research-worker"], env=environment, stdout=worker_log, stderr=worker_log
    )
    pool = await asyncpg.create_pool(environment["RESEARCH_PLATFORM_DATABASE_URL"])
    runs: list[dict[str, Any]] = []
    try:
        if args.forced_ingestion:
            with GpuSampler() as gpu:
                runs = await _forced_runs(tasks, hidden, output, args.run_timeout)
                peak = gpu.peak_mib
        async with httpx.AsyncClient(
            base_url=f"http://127.0.0.1:{args.port}", timeout=60
        ) as client:
            if not args.forced_ingestion:
                await _wait_ready(client, 600)
            with GpuSampler() as gpu:
                for task in tasks if not args.forced_ingestion else ():
                    body: dict[str, Any] = {
                        "question": task["question"],
                        "mode": "deep_research",
                    }
                    if task.get("filters"):
                        body["filters"] = task["filters"]
                    response = await client.post("/v1/research", json=body)
                    if response.status_code != 202:
                        raise SystemExit(f"submission failed: {response.status_code}")
                    run_id = UUID(response.json()["run_id"])
                    begun = time.monotonic()
                    view: dict[str, Any] = response.json()
                    while view["status"] not in TERMINAL:
                        if time.monotonic() - begun > args.run_timeout:
                            break
                        await asyncio.sleep(10)
                        view = (await client.get(f"/v1/research/{run_id}")).json()
                    runs.append(await _record(task, run_id, view, begun, pool, output))
                if not args.forced_ingestion:
                    peak = gpu.peak_mib
        async with pool.acquire() as connection:
            spend = await connection.fetch(
                "SELECT kind, count(*) AS requests, sum(cost_usd) AS cost "
                "FROM discovery_spend WHERE created_at >= $1 GROUP BY kind",
                started_at,
            )
    finally:
        await pool.close()
        processes = [process for process in (worker, api) if process is not None]
        for process in processes:
            process.send_signal(signal.SIGINT)
        for process in processes:
            try:
                process.wait(timeout=60)
            except subprocess.TimeoutExpired:
                process.kill()
        api_log.close()
        worker_log.close()
    summary = summarize(runs, hidden)
    summary.update(
        {
            "started_at": started_at.isoformat(),
            "pass": "forced_ingestion" if args.forced_ingestion else "natural",
            "hidden_papers": len(hidden),
            "gpu_peak_mib": peak,
            "median_run_seconds": sorted(run["seconds"] for run in runs)[len(runs) // 2]
            if runs
            else None,
            "spend": {
                row["kind"]: {"requests": row["requests"], "usd": str(row["cost"])}
                for row in spend
            },
            "code_revision": subprocess.run(
                ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
            ).stdout.strip(),
        }
    )
    (output / "summary.json").write_text(json.dumps(summary, indent=1, default=str))
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--port", type=int, default=8002)
    parser.add_argument("--run-timeout", type=float, default=3600.0)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--forced-ingestion", action="store_true")
    summary = asyncio.run(evaluate(parser.parse_args()))
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()
