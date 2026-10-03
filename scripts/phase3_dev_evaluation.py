"""Run both Phase 3 research modes on the approved private development tasks."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import stat
import subprocess
import tempfile
import time
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Sequence
from urllib.parse import urlsplit
from uuid import UUID

import asyncpg  # type: ignore[import-untyped]
import httpx
from pydantic import ValidationError

from research_platform.config import Settings
from research_platform.evaluation.phase3_metrics import (
    Phase3RunMetricsInput,
    aggregate_phase3_metrics,
)
from research_platform.runs.contracts import ResearchRunView


def _canonical_root() -> Path:
    """Resolve private-data paths through the repository's shared Git metadata."""
    checkout = Path(__file__).resolve().parents[1]
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
            cwd=checkout,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        raise RuntimeError("could not resolve the canonical Git checkout") from None
    common_dir = Path(result.stdout.strip()).resolve()
    root = common_dir.parent if common_dir.name == ".git" else checkout
    temporary_root = Path(tempfile.gettempdir()).resolve()
    if root == temporary_root or root.is_relative_to(temporary_root):
        raise RuntimeError(
            "private Phase 3 data cannot be rooted in a temporary checkout"
        )
    return root


CANONICAL_ROOT = _canonical_root()
PRIVATE_ROOT = CANONICAL_ROOT / "local-reference/phase3-runs"
DEFAULT_TASKS = PRIVATE_ROOT / "dev-tasks-v1.json"
API_BASE_URL = "http://127.0.0.1:8001"
POLL_INTERVAL_SECONDS = 2.0
POLL_TIMEOUT_SECONDS = 900.0
GPU_POLL_INTERVAL_SECONDS = 0.5
EXPECTED_SOURCE_COUNTS = {
    "calibration-v1": 10,
    "benchmark-development-questions-v1": 9,
    "calibration-v13-development": 2,
}
MODES = ("quick", "deep_research")


@dataclass(frozen=True, slots=True)
class DevelopmentTask:
    task_id: str
    source: str
    question: str
    filters: dict[str, int] | None
    unsupported: bool
    judged_paper_ids: frozenset[str]


def _private_path(value: str | Path) -> Path:
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = CANONICAL_ROOT / candidate
    resolved = candidate.resolve()
    if not resolved.is_relative_to(PRIVATE_ROOT.resolve()):
        raise ValueError(
            "private data paths must be under canonical local-reference/phase3-runs"
        )
    return resolved


def _load_tasks(path_value: str | Path) -> tuple[DevelopmentTask, ...]:
    path = _private_path(path_value)
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
            or source not in EXPECTED_SOURCE_COUNTS
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

    if len(tasks) != 21 or len({task.task_id for task in tasks}) != 21:
        raise ValueError("development task set must contain 21 unique families")
    counts = Counter(task.source for task in tasks)
    if dict(counts) != EXPECTED_SOURCE_COUNTS:
        raise ValueError("development task source counts do not match the approved set")
    return tuple(tasks)


def _parse_modes(value: str) -> tuple[str, ...]:
    modes = tuple(item.strip() for item in value.split(",") if item.strip())
    if len(modes) != len(MODES) or set(modes) != set(MODES):
        raise argparse.ArgumentTypeError(
            "both quick and deep_research modes are required"
        )
    return modes


def _safe_output_directory(value: str | None) -> Path:
    if value is None:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        destination = PRIVATE_ROOT / f"eval-{stamp}"
    else:
        destination = _private_path(value)
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        destination.mkdir(mode=0o700)
    except FileExistsError as exc:
        raise ValueError("evaluation output directory already exists") from exc
    os.chmod(destination, stat.S_IRWXU)
    return destination


def _create_private_file(path: Path) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(descriptor)
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)


def _append_private_jsonl(path: Path, value: object) -> None:
    encoded = (
        json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    descriptor = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        with os.fdopen(descriptor, "ab") as target:
            target.write(encoded)
            target.flush()
            os.fsync(target.fileno())
    except Exception:
        raise
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)


def _write_private_json(path: Path, value: object) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as target:
            json.dump(value, target, indent=2, ensure_ascii=False)
            target.write("\n")
            target.flush()
            os.fsync(target.fileno())
    except Exception:
        path.unlink(missing_ok=True)
        raise
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)


def _write_private_json_atomic(path: Path, value: object) -> None:
    """Atomically persist a mode-0600 private progress checkpoint."""
    temporary = path.with_suffix(path.suffix + ".tmp")
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
        stat.S_IRUSR | stat.S_IWUSR,
    )
    os.fchmod(descriptor, stat.S_IRUSR | stat.S_IWUSR)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as target:
            json.dump(value, target, separators=(",", ":"), ensure_ascii=False)
            target.write("\n")
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary, path)
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _resume_output_directory(value: str | Path) -> Path:
    """Validate an existing private evaluation directory for journal recovery."""
    directory = _private_path(value)
    journal = directory / "runs.jsonl"
    if not directory.is_dir() or not journal.is_file():
        raise ValueError("resume requires an existing private run journal")
    if stat.S_IMODE(directory.stat().st_mode) & 0o077:
        raise ValueError("resume directory permissions must be owner-only")
    if stat.S_IMODE(journal.stat().st_mode) & 0o077:
        raise ValueError("resume journal permissions must be owner-only")
    return directory


def _read_run_journal(path: Path) -> tuple[dict[str, object], ...]:
    """Read journal events without emitting their private contents."""
    events: list[dict[str, object]] = []
    try:
        with path.open(encoding="utf-8") as source:
            for line in source:
                if line.strip():
                    value = json.loads(line)
                    if not isinstance(value, dict):
                        raise ValueError
                    events.append(value)
    except (OSError, json.JSONDecodeError, ValueError):
        raise ValueError("private run journal is malformed") from None
    return tuple(events)


def _validate_private_service(settings: Settings) -> None:
    parsed = urlsplit(settings.database_url)
    if parsed.hostname not in {"localhost", "127.0.0.1"}:
        raise ValueError("evaluation database must be a loopback service")
    if parsed.path.rstrip("/") != "/research_phase1_review":
        raise ValueError("evaluation database must be research_phase1_review")
    api = urlsplit(API_BASE_URL)
    if api.hostname not in {"localhost", "127.0.0.1"}:
        raise ValueError("evaluation API must be a loopback service")


def _view(payload: object, *, mode: str) -> ResearchRunView:
    if not isinstance(payload, dict):
        raise RuntimeError("research API returned a malformed run view")
    try:
        view = ResearchRunView.model_validate(payload)
    except ValidationError:
        raise RuntimeError("research API returned a malformed run view") from None
    if view.mode.value != mode:
        raise RuntimeError("research API returned a run in the wrong mode")
    return view


def _validate_view_identity(
    view: ResearchRunView, *, task: DevelopmentTask, mode: str, run_id: UUID | None
) -> None:
    if view.question != task.question or view.mode.value != mode:
        raise RuntimeError("research API returned a mismatched run view")
    if run_id is not None and view.run_id != run_id:
        raise RuntimeError("research API returned a mismatched run view")


def _json_value(value: Any) -> object:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


async def _read_run_artifacts(
    pool: asyncpg.Pool, run_id: UUID
) -> tuple[tuple[dict[str, object], ...], tuple[str, ...]]:
    async with pool.acquire() as connection:
        async with connection.transaction(readonly=True):
            call_rows = await connection.fetch(
                """
                SELECT ordinal, tool_name, arguments, result, status,
                       duration_ms, error_category
                FROM tool_calls
                WHERE run_id = $1
                ORDER BY ordinal
                """,
                run_id,
            )
            handle_rows = await connection.fetch(
                """
                SELECT handle
                FROM research_run_evidence
                WHERE run_id = $1
                ORDER BY substring(handle FROM 2)::integer
                """,
                run_id,
            )
    calls = tuple(
        {
            "ordinal": row["ordinal"],
            "tool_name": row["tool_name"],
            "arguments": _json_value(row["arguments"]),
            "result": _json_value(row["result"]),
            "status": row["status"],
            "duration_ms": row["duration_ms"],
            "error_category": row["error_category"],
        }
        for row in call_rows
    )
    handles = tuple(row["handle"] for row in handle_rows)
    return calls, handles


def _metric_input(
    task: DevelopmentTask,
    mode: str,
    view: ResearchRunView,
    tool_calls: tuple[dict[str, object], ...],
    registry_handles: tuple[str, ...],
) -> Phase3RunMetricsInput:
    claims = view.claims
    budget_violations: list[str] = []
    if view.status.value == "completed":
        if view.provenance is None:
            budget_violations.append("missing_provenance")
        else:
            budgets = view.provenance.budgets
            if view.usage.tool_calls > budgets.max_tool_calls:
                budget_violations.append("tool_calls")
            if view.usage.plan_rounds > budgets.max_plan_rounds:
                budget_violations.append("plan_rounds")
            if view.usage.active_seconds > budgets.max_active_seconds:
                budget_violations.append("active_seconds")
    return Phase3RunMetricsInput(
        task_id=task.task_id,
        mode=mode,  # type: ignore[arg-type]
        status=view.status.value,  # type: ignore[arg-type]
        answer_outcome=view.answer_outcome.value if view.answer_outcome else None,
        failure_category=(
            view.failure_category.value if view.failure_category is not None else None
        ),
        cited_handles=tuple(
            citation.handle for claim in claims for citation in claim.evidence
        ),
        registry_handles=frozenset(registry_handles),
        cited_paper_ids=frozenset(
            citation.paper_id for claim in claims for citation in claim.evidence
        ),
        judged_paper_ids=task.judged_paper_ids,
        support_labels=tuple(claim.support.value for claim in claims),
        citation_counts=tuple(len(claim.evidence) for claim in claims),
        tool_calls=view.usage.tool_calls,
        tool_call_records=len(tool_calls),
        plan_rounds=view.usage.plan_rounds,
        model_calls=view.usage.model_calls,
        active_seconds=view.usage.active_seconds,
        unsupported=task.unsupported,
        budget_violations=tuple(budget_violations),
    )


def _journal_submissions(
    events: tuple[dict[str, object], ...],
) -> dict[tuple[str, str], dict[str, object]]:
    """Index already accepted submissions and their newest saved views."""
    submissions: dict[tuple[str, str], dict[str, object]] = {}
    run_keys: dict[str, tuple[str, str]] = {}
    for event in events:
        if event.get("event") != "run_view":
            continue
        task = event.get("task")
        view = event.get("view")
        mode = event.get("mode")
        run_id = event.get("run_id")
        if (
            not isinstance(task, dict)
            or not isinstance(task.get("task_id"), str)
            or not isinstance(mode, str)
            or not isinstance(run_id, str)
            or not isinstance(view, dict)
        ):
            raise ValueError("private run journal contains an invalid submission")
        key = (task["task_id"], mode)
        prior_key = run_keys.get(run_id)
        if prior_key is not None and prior_key != key:
            raise ValueError("private run journal maps one run to multiple tasks")
        run_keys[run_id] = key
        existing = submissions.get(key)
        if existing is not None and existing["run_id"] != run_id:
            raise ValueError("private run journal contains duplicate submissions")
        if existing is None:
            submissions[key] = {
                "task": task,
                "mode": mode,
                "run_id": run_id,
                "latest_view": view,
                "latest_poll": event.get("poll", 0),
                "artifacts": None,
            }
        else:
            existing["latest_view"] = view
            existing["latest_poll"] = event.get("poll", 0)
    artifact_ids: set[str] = set()
    for event in events:
        if event.get("event") != "run_artifacts":
            continue
        run_id = event.get("run_id")
        if not isinstance(run_id, str):
            raise ValueError("private run journal contains invalid artifacts")
        if run_id in artifact_ids or run_id not in run_keys:
            raise ValueError("private run journal contains an unmapped artifact")
        artifact_ids.add(run_id)
        for submission in submissions.values():
            if submission["run_id"] == run_id:
                submission["artifacts"] = event
                break
    for event in events:
        run_id = event.get("run_id")
        if event.get("event") == "run_complete" and run_id is not None:
            if not isinstance(run_id, str) or run_id not in run_keys:
                raise ValueError("private run journal contains an unmapped completion")
    return submissions


def _pending_task_pairs(
    tasks: tuple[DevelopmentTask, ...],
    modes: tuple[str, ...],
    submitted: set[tuple[str, str]],
) -> tuple[tuple[int, DevelopmentTask, str], ...]:
    """Return only task/mode pairs without an accepted submission."""
    return tuple(
        (index, task, mode)
        for mode in modes
        for index, task in enumerate(tasks, start=1)
        if (task.task_id, mode) not in submitted
    )


def _append_run_view(
    path: Path,
    *,
    task: DevelopmentTask,
    mode: str,
    view: ResearchRunView,
    poll: int,
) -> None:
    _append_private_jsonl(
        path,
        {
            "event": "run_view",
            "task": {
                "task_id": task.task_id,
                "source": task.source,
                "question": task.question,
                "filters": task.filters,
                "unsupported": task.unsupported,
                "judged_paper_ids": sorted(task.judged_paper_ids),
            },
            "mode": mode,
            "run_id": str(view.run_id),
            "poll": poll,
            "view": view.model_dump(mode="json"),
        },
    )


async def _poll_existing_run(
    *,
    client: httpx.AsyncClient,
    task: DevelopmentTask,
    mode: str,
    run_id: UUID,
    current: ResearchRunView,
    output_path: Path,
    poll_index: int,
) -> ResearchRunView:
    """Resume polling one existing run without submitting another request."""
    started = time.monotonic()
    while current.status.value not in {"completed", "failed"}:
        if time.monotonic() - started >= POLL_TIMEOUT_SECONDS:
            _append_private_jsonl(
                output_path,
                {
                    "event": "poll_timeout",
                    "task_id": task.task_id,
                    "mode": mode,
                    "run_id": str(run_id),
                    "poll_timeout_seconds": POLL_TIMEOUT_SECONDS,
                },
            )
            raise RuntimeError(
                "research run did not reach a terminal status before the evaluator timeout"
            )
        await asyncio.sleep(POLL_INTERVAL_SECONDS)
        poll_index += 1
        try:
            response = await client.get(f"{API_BASE_URL}/v1/research/{run_id}")
        except httpx.HTTPError:
            raise RuntimeError("research API status request failed") from None
        if response.status_code != 200:
            raise RuntimeError(
                f"research API returned HTTP {response.status_code} while polling"
            )
        try:
            current = _view(response.json(), mode=mode)
        except (ValueError, RuntimeError):
            raise RuntimeError("research API returned an invalid status view") from None
        _validate_view_identity(current, task=task, mode=mode, run_id=run_id)
        _append_run_view(
            output_path,
            task=task,
            mode=mode,
            view=current,
            poll=poll_index,
        )
    return current


async def _resume_submitted_runs(
    *,
    client: httpx.AsyncClient,
    pool: asyncpg.Pool,
    tasks: tuple[DevelopmentTask, ...],
    modes: tuple[str, ...],
    output_path: Path,
    progress_path: Path,
    sampler: _GpuSampler,
) -> tuple[list[Phase3RunMetricsInput], list[dict[str, object]], set[tuple[str, str]]]:
    """Reconcile journaled submissions, polling only their existing run IDs."""
    events = _read_run_journal(output_path)
    submissions = _journal_submissions(events)
    task_by_id = {task.task_id: task for task in tasks}
    allowed_modes = set(modes)
    runs: list[Phase3RunMetricsInput] = []
    contexts: list[dict[str, object]] = []
    for (task_id, mode), submission in submissions.items():
        task = task_by_id.get(task_id)
        if task is None or mode not in allowed_modes:
            raise ValueError("private run journal does not match the approved task set")
        saved_task = submission["task"]
        if not isinstance(saved_task, dict) or saved_task != {
            "task_id": task.task_id,
            "source": task.source,
            "question": task.question,
            "filters": task.filters,
            "unsupported": task.unsupported,
            "judged_paper_ids": sorted(task.judged_paper_ids),
        }:
            raise ValueError("private run journal task differs from the approved set")
        latest_poll = submission["latest_poll"]
        if not isinstance(latest_poll, int) or latest_poll < 0:
            raise ValueError("private run journal contains an invalid poll index")
        run_id = UUID(str(submission["run_id"]))
        current = _view(submission["latest_view"], mode=mode)
        _validate_view_identity(current, task=task, mode=mode, run_id=run_id)
        stored_artifacts = submission["artifacts"]
        if stored_artifacts is None:
            try:
                response = await client.get(f"{API_BASE_URL}/v1/research/{run_id}")
            except httpx.HTTPError:
                raise RuntimeError("research API status request failed") from None
            if response.status_code != 200:
                raise RuntimeError(
                    f"research API returned HTTP {response.status_code} while resuming"
                )
            try:
                current = _view(response.json(), mode=mode)
            except (ValueError, RuntimeError):
                raise RuntimeError(
                    "research API returned an invalid status view"
                ) from None
            _validate_view_identity(current, task=task, mode=mode, run_id=run_id)
            _append_run_view(
                output_path,
                task=task,
                mode=mode,
                view=current,
                poll=latest_poll + 1,
            )
            current = await _poll_existing_run(
                client=client,
                task=task,
                mode=mode,
                run_id=run_id,
                current=current,
                output_path=output_path,
                poll_index=latest_poll + 1,
            )
            tool_calls, registry_handles = await _read_run_artifacts(pool, run_id)
            artifact_event: dict[str, object] = {
                "event": "run_artifacts",
                "task": {
                    "task_id": task.task_id,
                    "source": task.source,
                    "question": task.question,
                    "filters": task.filters,
                    "unsupported": task.unsupported,
                    "judged_paper_ids": sorted(task.judged_paper_ids),
                },
                "mode": mode,
                "run_id": str(run_id),
                "registry_handles": registry_handles,
                "tool_calls": tool_calls,
            }
            _append_private_jsonl(output_path, artifact_event)
        else:
            if not isinstance(stored_artifacts, dict):
                raise ValueError("private run journal contains invalid artifacts")
            tool_calls_value = stored_artifacts.get("tool_calls")
            handles_value = stored_artifacts.get("registry_handles")
            if not isinstance(tool_calls_value, list) or not isinstance(
                handles_value, list
            ):
                raise ValueError("private run journal contains invalid artifacts")
            tool_calls = tuple(
                call for call in tool_calls_value if isinstance(call, dict)
            )
            registry_handles = tuple(
                handle for handle in handles_value if isinstance(handle, str)
            )
            if len(tool_calls) != len(tool_calls_value) or len(registry_handles) != len(
                handles_value
            ):
                raise ValueError("private run journal contains invalid artifacts")
        if current.status.value not in {"completed", "failed"}:
            raise RuntimeError("existing research run is not terminal")
        if stored_artifacts is None:
            _append_private_jsonl(
                output_path,
                {
                    "event": "run_complete",
                    "task_id": task_id,
                    "run_id": str(run_id),
                    "mode": mode,
                    "status": current.status.value,
                    "completed_count": int(current.status.value == "completed"),
                    "failed_count": int(current.status.value == "failed"),
                },
            )
        runs.append(_metric_input(task, mode, current, tool_calls, registry_handles))
        context = _model_context(current)
        if context is not None and context not in contexts:
            contexts.append(context)
        _save_progress(progress_path, runs, sampler, task_count=len(tasks))
    return runs, contexts, set(submissions)


def _save_progress(
    path: Path,
    runs: list[Phase3RunMetricsInput],
    sampler: _GpuSampler,
    *,
    task_count: int,
) -> None:
    """Persist sanitized aggregates and sampler coverage after each run."""
    aggregate = aggregate_phase3_metrics(runs)
    _write_private_json_atomic(
        path,
        {
            "task_count": task_count,
            "run_count": len(runs),
            "gates": aggregate["gates"],
            "reported_by_mode": aggregate["reported_by_mode"],
            "gpu_peak_memory": sampler.report(),
        },
    )


class _GpuSampler:
    def __init__(self, checkpoint_path: Path, *, resume: bool = False) -> None:
        self.mode: str | None = None
        self.peak_mib: dict[str, int] = {mode: 0 for mode in MODES}
        self.samples: dict[str, int] = {mode: 0 for mode in MODES}
        self.errors = 0
        self._stopping = False
        self.checkpoint_path = checkpoint_path
        if resume and checkpoint_path.is_file():
            try:
                saved = json.loads(checkpoint_path.read_text(encoding="utf-8"))
                peaks = saved["peak_mib"]
                samples = saved["samples"]
                if not all(
                    isinstance(peaks[mode], int)
                    and isinstance(samples[mode], int)
                    and samples[mode] >= 0
                    for mode in MODES
                ):
                    raise ValueError
                self.peak_mib = {mode: peaks[mode] for mode in MODES}
                self.samples = {mode: samples[mode] for mode in MODES}
                self.errors = int(saved["errors"])
            except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
                raise ValueError("GPU sampler checkpoint is malformed") from None

    def _checkpoint(self) -> None:
        _write_private_json_atomic(
            self.checkpoint_path,
            {
                "peak_mib": self.peak_mib,
                "samples": self.samples,
                "errors": self.errors,
                "sample_interval_seconds": GPU_POLL_INTERVAL_SECONDS,
            },
        )

    def set_mode(self, mode: str) -> None:
        self.mode = mode

    async def sample(self) -> None:
        while not self._stopping:
            try:
                process = await asyncio.create_subprocess_exec(
                    "nvidia-smi",
                    "--query-gpu=memory.used",
                    "--format=csv,noheader,nounits",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                stdout, _ = await asyncio.wait_for(process.communicate(), timeout=5.0)
                if process.returncode != 0:
                    self.errors += 1
                elif self.mode is not None:
                    values = [
                        int(line.strip())
                        for line in stdout.decode("ascii").splitlines()
                        if line.strip().isdigit()
                    ]
                    if values:
                        self.samples[self.mode] += 1
                        self.peak_mib[self.mode] = max(
                            self.peak_mib[self.mode], max(values)
                        )
                    else:
                        self.errors += 1
            except (OSError, ValueError, asyncio.TimeoutError):
                self.errors += 1
            self._checkpoint()
            await asyncio.sleep(GPU_POLL_INTERVAL_SECONDS)

    def stop(self) -> None:
        self._stopping = True

    def report(self) -> dict[str, object]:
        return {
            mode: self.peak_mib[mode] if self.samples[mode] else None for mode in MODES
        } | {
            "samples_by_mode": self.samples,
            "unit": "MiB",
            "sample_interval_seconds": GPU_POLL_INTERVAL_SECONDS,
            "errors": self.errors,
        }


def _model_context(view: ResearchRunView) -> dict[str, object] | None:
    provenance = view.provenance
    if provenance is None:
        return None
    return {
        "code_revision": provenance.code_revision,
        "model": provenance.model.model_dump(mode="json"),
        "thinking": {
            kind.value: enabled for kind, enabled in provenance.thinking.items()
        },
        "budgets": provenance.budgets.model_dump(mode="json"),
    }


async def _run_one(
    *,
    client: httpx.AsyncClient,
    pool: asyncpg.Pool,
    task: DevelopmentTask,
    mode: str,
    output_path: Path,
    sampler: _GpuSampler,
) -> tuple[ResearchRunView, tuple[dict[str, object], ...], tuple[str, ...]]:
    sampler.set_mode(mode)
    request: dict[str, object] = {"question": task.question, "mode": mode}
    if task.filters is not None:
        request["filters"] = task.filters
    try:
        response = await client.post(f"{API_BASE_URL}/v1/research", json=request)
    except httpx.HTTPError:
        raise RuntimeError("research API request failed") from None
    if response.status_code != 202:
        raise RuntimeError(
            f"research API returned HTTP {response.status_code} on submission"
        )
    try:
        current = _view(response.json(), mode=mode)
    except (ValueError, RuntimeError):
        raise RuntimeError("research API returned an invalid submission view") from None
    _validate_view_identity(current, task=task, mode=mode, run_id=None)
    run_id = current.run_id
    event_base = {
        "task": {
            "task_id": task.task_id,
            "source": task.source,
            "question": task.question,
            "filters": task.filters,
            "unsupported": task.unsupported,
            "judged_paper_ids": sorted(task.judged_paper_ids),
        },
        "mode": mode,
        "run_id": str(run_id),
    }
    initial_view = current.model_dump(mode="json")
    _append_private_jsonl(
        output_path,
        {"event": "run_view", **event_base, "poll": 0, "view": initial_view},
    )
    current = await _poll_existing_run(
        client=client,
        task=task,
        mode=mode,
        run_id=run_id,
        current=current,
        output_path=output_path,
        poll_index=0,
    )

    tool_calls, registry_handles = await _read_run_artifacts(pool, run_id)
    _append_private_jsonl(
        output_path,
        {
            "event": "run_artifacts",
            **event_base,
            "registry_handles": registry_handles,
            "tool_calls": tool_calls,
        },
    )
    _append_private_jsonl(
        output_path,
        {
            "event": "run_complete",
            "task_id": task.task_id,
            "run_id": str(current.run_id),
            "mode": mode,
            "status": current.status.value,
            "completed_count": int(current.status.value == "completed"),
            "failed_count": int(current.status.value == "failed"),
        },
    )
    return current, tool_calls, registry_handles


async def _evaluate(
    tasks: tuple[DevelopmentTask, ...],
    modes: tuple[str, ...],
    output_dir: Path,
    *,
    resume: bool,
) -> dict[str, object]:
    runs_path = output_dir / "runs.jsonl"
    if resume:
        if (output_dir / "summary.json").exists():
            raise ValueError("completed evaluation cannot be resumed")
        if not runs_path.is_file():
            raise ValueError("resume requires an existing private run journal")
    else:
        _create_private_file(runs_path)
    settings = Settings()
    _validate_private_service(settings)
    timeout = httpx.Timeout(30.0, connect=10.0)
    pool = await asyncpg.create_pool(settings.database_url, min_size=1, max_size=2)
    progress_path = output_dir / "progress.json"
    sampler = _GpuSampler(output_dir / "gpu-checkpoint.json", resume=resume)
    sampler_task = asyncio.create_task(sampler.sample())
    runs: list[Phase3RunMetricsInput] = []
    contexts: list[dict[str, object]] = []
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            submitted: set[tuple[str, str]] = set()
            if resume:
                runs, contexts, submitted = await _resume_submitted_runs(
                    client=client,
                    pool=pool,
                    tasks=tasks,
                    modes=modes,
                    output_path=runs_path,
                    progress_path=progress_path,
                    sampler=sampler,
                )
            else:
                _save_progress(progress_path, runs, sampler, task_count=len(tasks))
            for index, task, mode in _pending_task_pairs(tasks, modes, submitted):
                view, tool_calls, handles = await _run_one(
                    client=client,
                    pool=pool,
                    task=task,
                    mode=mode,
                    output_path=runs_path,
                    sampler=sampler,
                )
                runs.append(_metric_input(task, mode, view, tool_calls, handles))
                context = _model_context(view)
                if context is not None and context not in contexts:
                    contexts.append(context)
                submitted.add((task.task_id, mode))
                _save_progress(progress_path, runs, sampler, task_count=len(tasks))
                counts = Counter(
                    run.status == "completed" for run in runs if run.mode == mode
                )
                print(
                    json.dumps(
                        {
                            "event": "task_complete",
                            "mode": mode,
                            "mode_index": index,
                            "mode_total": len(tasks),
                            "completed": counts[True],
                            "failed": counts[False],
                        }
                    ),
                    flush=True,
                )
        result = aggregate_phase3_metrics(runs)
        expected_runs = len(tasks) * len(modes)
        unique_pairs = {(run.task_id, run.mode) for run in runs}
        if len(runs) != expected_runs or len(unique_pairs) != expected_runs:
            raise ValueError("evaluation ledger does not cover every task and mode")
        result["task_counts_by_source"] = dict(
            sorted(Counter(task.source for task in tasks).items())
        )
        result["task_count"] = len(tasks)
        result["run_count"] = len(runs)
        result["model_contexts"] = contexts
        result["gpu_peak_memory"] = sampler.report()
        _write_private_json_atomic(output_dir / "summary.json", result)
        return result
    finally:
        sampler.stop()
        sampler_task.cancel()
        try:
            await sampler_task
        except asyncio.CancelledError:
            pass
        await pool.close()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks", default=str(DEFAULT_TASKS))
    parser.add_argument("--modes", type=_parse_modes, default=MODES)
    parser.add_argument("--output", help="new private evaluation directory")
    parser.add_argument(
        "--resume",
        action="store_true",
        help="resume submissions in an existing private output directory",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    os.umask(0o077)
    args = _parser().parse_args(argv)
    try:
        tasks = _load_tasks(args.tasks)
        if args.resume:
            if args.output is None:
                raise ValueError(
                    "--resume requires --output with an existing directory"
                )
            output_dir = _resume_output_directory(args.output)
        else:
            output_dir = _safe_output_directory(args.output)
        print(
            json.dumps(
                {
                    "event": "evaluation_started",
                    "task_count": len(tasks),
                    "mode_count": len(args.modes),
                }
            ),
            flush=True,
        )
        summary = asyncio.run(
            _evaluate(tasks, args.modes, output_dir, resume=args.resume)
        )
        print(
            json.dumps(
                {"event": "evaluation_complete", "summary": summary},
                ensure_ascii=False,
            )
        )
    except KeyboardInterrupt:
        print(json.dumps({"event": "evaluation_stopped", "reason": "interrupted"}))
        raise SystemExit(130) from None
    except Exception as exc:
        print(
            json.dumps(
                {"event": "evaluation_stopped", "error_type": type(exc).__name__}
            ),
            flush=True,
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
