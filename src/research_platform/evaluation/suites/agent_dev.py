"""Run the private development tasks through the research API."""

from __future__ import annotations

import asyncio
import json
import os
import statistics
import time
from collections import Counter
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import asyncpg  # type: ignore[import-untyped]
import httpx
from pydantic import ValidationError

from research_platform.evaluation.experiments import (
    DatasetIdentity,
    ExperimentOutcome,
    canonical_repository_root,
    file_sha256,
    read_items,
)
from research_platform.evaluation.suites.base import SuiteContext
from research_platform.runs.contracts import ResearchRunView
from research_platform.runs.repository import RunRepository
from research_platform.runs.store import RunStore

MODES = ("quick", "deep_research")
TASK_SOURCES = {
    "calibration-v1",
    "benchmark-development-questions-v1",
    "calibration-v13-development",
}


@dataclass(frozen=True, slots=True)
class DevelopmentTask:
    task_id: str
    source: str
    question: str
    filters: dict[str, int] | None
    unsupported: bool
    judged_paper_ids: frozenset[str]


def _task_path(value: str | Path | None) -> Path:
    path = (
        canonical_repository_root() / "local-reference/phase3-runs/dev-tasks-v1.json"
        if value is None
        else Path(value)
    )
    if not path.is_absolute():
        path = canonical_repository_root() / path
    return path.resolve()


def _load_tasks(path: Path) -> tuple[DevelopmentTask, ...]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("could not read the private development task file") from exc
    if not isinstance(document, dict) or document.get("schema_version") != 1:
        raise ValueError("development task file has an unsupported schema")
    raw_tasks = document.get("tasks")
    if not isinstance(raw_tasks, list):
        raise ValueError("development task file does not contain a task list")

    tasks: list[DevelopmentTask] = []
    for value in raw_tasks:
        if not isinstance(value, dict):
            raise ValueError("development task file contains an invalid task")
        task_id = value.get("task_id")
        source = value.get("source")
        question = value.get("question")
        filters_value = value.get("filters")
        unsupported = value.get("unsupported")
        judged_ids_value = value.get("judged_paper_ids")
        if (
            not isinstance(task_id, str)
            or not task_id
            or not isinstance(source, str)
            or source not in TASK_SOURCES
            or not isinstance(question, str)
            or not question.strip()
            or not isinstance(unsupported, bool)
            or not isinstance(judged_ids_value, list)
            or any(not isinstance(item, str) for item in judged_ids_value)
        ):
            raise ValueError("development task file contains invalid task fields")
        if filters_value is None:
            filters = None
        elif isinstance(filters_value, dict) and all(
            key in {"year_from", "year_to"}
            and isinstance(item, int)
            and not isinstance(item, bool)
            for key, item in filters_value.items()
        ):
            filters = dict(filters_value)
        else:
            raise ValueError("development task file contains invalid filters")
        if len(judged_ids_value) != len(set(judged_ids_value)):
            raise ValueError("development task contains duplicate judged papers")
        tasks.append(
            DevelopmentTask(
                task_id=task_id,
                source=source,
                question=question,
                filters=filters,
                unsupported=unsupported,
                judged_paper_ids=frozenset(judged_ids_value),
            )
        )
    if not tasks or len({task.task_id for task in tasks}) != len(tasks):
        raise ValueError("development task set must contain unique task IDs")
    return tuple(tasks)


def _parse_modes(value: str) -> tuple[str, ...]:
    modes = tuple(item.strip() for item in value.split(",") if item.strip())
    if len(modes) != len(MODES) or set(modes) != set(MODES):
        raise ValueError("both quick and deep_research modes are required")
    return modes


def _nearest_rank(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, int(len(ordered) * percentile + 0.999999999))
    return ordered[rank - 1]


def _summary(items: list[dict[str, object]]) -> dict[str, int | float | None]:
    outcomes = [item.get("answer_outcome") for item in items]
    durations = [
        value
        for item in items
        if isinstance((value := item.get("active_seconds")), (int, float))
    ]
    claims = [
        value for item in items if isinstance((value := item.get("kept_claims")), int)
    ]
    unsupported_declined = sum(
        item.get("unsupported") is True
        and item.get("answer_outcome") == "insufficient_evidence"
        for item in items
    )
    runs = len(items)
    completed = sum(item.get("status") == "completed" for item in items)
    return {
        "runs": runs,
        "completed": completed,
        "completion_rate": completed / runs if runs else 0.0,
        "answered": outcomes.count("answered"),
        "partially_supported": outcomes.count("partially_supported"),
        "insufficient_evidence": outcomes.count("insufficient_evidence"),
        "median_active_seconds": statistics.median(durations) if durations else None,
        "p90_active_seconds": _nearest_rank(durations, 0.9),
        "mean_kept_claims": statistics.fmean(claims) if claims else None,
        "unsupported_tasks_declined": unsupported_declined,
    }


def _configuration_versions(
    configuration: Mapping[str, object],
) -> tuple[dict[str, str], int | None]:
    versions: dict[str, str] = {}
    model = configuration.get("model")
    if isinstance(model, Mapping):
        name = model.get("name")
        digest = model.get("digest")
        if isinstance(name, str):
            versions["model"] = name
        versions["model_digest"] = digest if isinstance(digest, str) else ""
    prompt_versions = configuration.get("prompt_versions")
    if isinstance(prompt_versions, Mapping):
        versions.update(
            {
                f"prompt.{name}": version
                for name, version in prompt_versions.items()
                if isinstance(name, str) and isinstance(version, str)
            }
        )
    tool_schema = configuration.get("tool_schema_digest")
    if isinstance(tool_schema, str):
        versions["tool_schema"] = tool_schema
    decoding = configuration.get("decoding")
    seed = decoding.get("seed") if isinstance(decoding, Mapping) else None
    return versions, seed if isinstance(seed, int) else None


class AgentDevSuite:
    """Evaluate the development task set through a running research API."""

    name = "agent-dev"

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        store: RunStore | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._client = client
        self._store = store
        self._sleep = sleep

    def dataset(self, options: Mapping[str, str]) -> DatasetIdentity:
        path = _task_path(options.get("tasks"))
        return DatasetIdentity("phase3-dev-tasks", "v1", file_sha256(path))

    async def run(self, context: SuiteContext) -> ExperimentOutcome:
        task_path = _task_path(context.options.get("tasks"))
        tasks = _load_tasks(task_path)
        modes = _parse_modes(context.options.get("modes", "quick,deep_research"))
        api = context.options.get("api", "http://127.0.0.1:8001").rstrip("/")
        timeout = float(context.options.get("run_timeout_seconds", "3600"))

        client = self._client
        owns_client = client is None
        if client is None:
            client = httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0))
        store = self._store
        pool: asyncpg.Pool | None = None
        items: list[dict[str, object]] = []
        try:
            if store is None:
                pool = await asyncpg.create_pool(
                    context.settings.database_url, min_size=1, max_size=2
                )
                store = RunRepository(pool)
            resume_path = context.options.get("resume_items")
            completed_pairs: set[tuple[str, str]] = set()
            if resume_path is not None:
                for item in read_items(Path(resume_path)):
                    task_id, mode = item.get("task_id"), item.get("mode")
                    if isinstance(task_id, str) and isinstance(mode, str):
                        pair = (task_id, mode)
                        if pair in completed_pairs:
                            continue
                        completed_pairs.add(pair)
                        context.writer.append(item)
                        items.append(item)
                        self._print_progress(item)

            headers: dict[str, str] = {}
            api_key = os.environ.get("RESEARCH_PLATFORM_API_KEY")
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"

            for mode in modes:
                for task in tasks:
                    pair = (task.task_id, mode)
                    if pair in completed_pairs:
                        continue
                    item = await self._run_item(
                        client,
                        task,
                        mode,
                        api=api,
                        headers=headers,
                        timeout=timeout,
                    )
                    completed_pairs.add(pair)
                    context.writer.append(item)
                    items.append(item)
                    self._print_progress(item)

            ids = [item.get("configuration_id") for item in items]
            unique_ids = set(ids)
            configuration_id: str | None = None
            configuration: dict[str, object] = {}
            versions: dict[str, str] = {}
            random_seed: int | None = None
            failures: Counter[str] = Counter()
            if len(unique_ids) == 1 and isinstance(ids[0] if ids else None, str):
                configuration_id = cast(str, ids[0])
                configuration = await store.load_run_configuration(configuration_id)
                versions, random_seed = _configuration_versions(configuration)
            else:
                failures["mixed_configuration"] = len(unique_ids)

            for item in items:
                failure_category = item.get("failure_category")
                status = item.get("status")
                if isinstance(failure_category, str):
                    failures[failure_category] += 1
                elif status in {"submit_failed", "poll_timeout"}:
                    failures[status] += 1

            metrics = _summary(items)
            for mode in modes:
                mode_summary = _summary(
                    [item for item in items if item.get("mode") == mode]
                )
                metrics.update(
                    {f"{mode}.{key}": value for key, value in mode_summary.items()}
                )
            return ExperimentOutcome(
                configuration_id=configuration_id,
                configuration=configuration,
                versions=versions,
                random_seed=random_seed,
                metrics=metrics,
                failures=dict(failures),
                item_count=context.writer.count,
            )
        finally:
            if owns_client:
                await client.aclose()
            if pool is not None:
                await pool.close()

    async def _run_item(
        self,
        client: httpx.AsyncClient,
        task: DevelopmentTask,
        mode: str,
        *,
        api: str,
        headers: Mapping[str, str],
        timeout: float,
    ) -> dict[str, object]:
        payload: dict[str, object] = {"question": task.question, "mode": mode}
        if task.filters is not None:
            payload["filters"] = task.filters
        response = await client.post(
            f"{api}/v1/research", json=payload, headers=headers
        )
        if response.status_code != 202:
            return self._empty_item(task, mode, status="submit_failed")
        body = response.json()
        run_id = body.get("run_id") if isinstance(body, dict) else None
        if not isinstance(run_id, str):
            return self._empty_item(task, mode, status="submit_failed")

        started = time.monotonic()
        while True:
            if time.monotonic() - started >= timeout:
                return self._empty_item(
                    task, mode, status="poll_timeout", run_id=run_id
                )
            await self._sleep(2.0)
            response = await client.get(f"{api}/v1/research/{run_id}", headers=headers)
            response.raise_for_status()
            value = response.json()
            if not isinstance(value, dict):
                raise RuntimeError("research API returned a malformed run view")
            status = value.get("status")
            if status in {"completed", "failed"}:
                try:
                    view = ResearchRunView.model_validate(value)
                except ValidationError:
                    raise RuntimeError(
                        "research API returned a malformed run view"
                    ) from None
                return {
                    "item_id": f"{task.task_id}:{mode}",
                    "task_id": task.task_id,
                    "mode": mode,
                    "unsupported": task.unsupported,
                    "run_id": str(view.run_id),
                    "status": view.status.value,
                    "answer_outcome": (
                        view.answer_outcome.value if view.answer_outcome else None
                    ),
                    "failure_category": (
                        view.failure_category.value if view.failure_category else None
                    ),
                    "active_seconds": view.usage.active_seconds,
                    "tool_calls": view.usage.tool_calls,
                    "model_calls": view.usage.model_calls,
                    "kept_claims": len(view.claims),
                    "rejected_claims": view.usage.rejected_claims,
                    "unsupported_claims": view.usage.unsupported_claims,
                    "configuration_id": (
                        view.provenance.configuration_id if view.provenance else None
                    ),
                }

    @staticmethod
    def _empty_item(
        task: DevelopmentTask,
        mode: str,
        *,
        status: str,
        run_id: str | None = None,
    ) -> dict[str, object]:
        return {
            "item_id": f"{task.task_id}:{mode}",
            "task_id": task.task_id,
            "mode": mode,
            "unsupported": task.unsupported,
            "run_id": run_id,
            "status": status,
            "answer_outcome": None,
            "failure_category": None,
            "active_seconds": None,
            "tool_calls": None,
            "model_calls": None,
            "kept_claims": 0,
            "rejected_claims": 0,
            "unsupported_claims": 0,
            "configuration_id": None,
        }

    @staticmethod
    def _print_progress(item: Mapping[str, object]) -> None:
        print(
            json.dumps(
                {
                    "item_id": item.get("item_id"),
                    "status": item.get("status"),
                    "answer_outcome": item.get("answer_outcome"),
                }
            )
        )
