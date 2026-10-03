"""Build the private Phase 3 development task set from approved inputs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import subprocess
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any, Sequence

import tomllib


def _canonical_root() -> Path:
    """Resolve the primary checkout from this checkout's Git common directory."""
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
CALIBRATION_PATH = CANONICAL_ROOT / "benchmarks/phase2/calibration-v1.toml"
QUESTIONS_PATH = (
    CANONICAL_ROOT / "benchmarks/phase2/benchmark-development-questions-v1.toml"
)
ALLOWLIST_PATH = CANONICAL_ROOT / "benchmarks/phase2/phase2-dev-input-allowlist-v1.json"
V13_PATH = (
    CANONICAL_ROOT
    / "local-reference/phase2-runs/benchmark-v13-backup-20260929/"
    / "calibration-v13-development.toml"
)


def _load_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as source:
        value = tomllib.load(source)
    if not isinstance(value, dict):
        raise ValueError("development input must contain a TOML table")
    return value


def _task(family: dict[str, Any], *, source: str) -> dict[str, Any]:
    family_id = family.get("id")
    queries = family.get("queries")
    if not isinstance(family_id, str) or not family_id:
        raise ValueError(f"{source} contains a family without an ID")
    if not isinstance(queries, list) or not queries or not isinstance(queries[0], dict):
        raise ValueError(f"{source} contains a family without a first query")
    question = queries[0].get("text")
    if not isinstance(question, str) or not question.strip():
        raise ValueError(f"{source} contains a family with an invalid first query")

    raw_filters = family.get("filters")
    if raw_filters is None:
        filters = None
    elif isinstance(raw_filters, dict):
        if set(raw_filters) - {"year_from", "year_to"}:
            raise ValueError(f"{source} contains unsupported family filters")
        if any(type(value) is not int for value in raw_filters.values()):
            raise ValueError(f"{source} contains invalid year filters")
        filters = {
            name: raw_filters[name]
            for name in ("year_from", "year_to")
            if raw_filters.get(name) is not None
        }
        if not filters:
            filters = None
    else:
        raise ValueError(f"{source} contains invalid family filters")

    judgments = family.get("paper_judgments", [])
    if not isinstance(judgments, list) or any(
        not isinstance(item, dict)
        or not isinstance(item.get("paper_id"), str)
        or not isinstance(item.get("label"), int)
        or item.get("label") not in {0, 1, 2}
        for item in judgments
    ):
        raise ValueError(f"{source} contains invalid paper judgments")
    judged_paper_ids = [
        item["paper_id"] for item in judgments if item.get("label") == 2
    ]
    if len(judged_paper_ids) != len(set(judged_paper_ids)):
        raise ValueError(f"{source} contains duplicate direct-judgment papers")

    unsupported = family.get("unsupported", False)
    if not isinstance(unsupported, bool):
        raise ValueError(f"{source} contains an invalid unsupported flag")
    return {
        "task_id": family_id,
        "source": source,
        "question": question.strip(),
        "filters": filters,
        "unsupported": unsupported,
        "judged_paper_ids": judged_paper_ids,
    }


def build_tasks() -> tuple[dict[str, Any], ...]:
    """Read only the approved development inputs and build their task records."""
    calibration = _load_toml(CALIBRATION_PATH)
    question_manifest = _load_toml(QUESTIONS_PATH)
    v13 = _load_toml(V13_PATH)
    allowlist = json.loads(ALLOWLIST_PATH.read_text(encoding="utf-8"))

    try:
        reviewed = allowlist["reviewed_development"]
        allowed_ids = reviewed["allowed_family_ids"]
        recorded_digest = reviewed["question_manifest_sha256"]
    except (KeyError, TypeError) as exc:
        raise ValueError("development allowlist has an invalid schema") from exc
    actual_digest = f"sha256:{hashlib.sha256(QUESTIONS_PATH.read_bytes()).hexdigest()}"
    if recorded_digest != actual_digest:
        raise ValueError("development allowlist does not match the question manifest")
    if (
        not isinstance(allowed_ids, list)
        or any(not isinstance(item, str) for item in allowed_ids)
        or len(allowed_ids) != len(set(allowed_ids))
    ):
        raise ValueError("development allowlist family IDs are invalid")

    calibration_families = calibration.get("families")
    question_families = question_manifest.get("families")
    v13_families = v13.get("families")
    if not all(
        isinstance(families, list)
        and all(isinstance(family, dict) for family in families)
        for families in (calibration_families, question_families, v13_families)
    ):
        raise ValueError("a development input has an invalid family collection")

    allowlist_set = set(allowed_ids)
    question_by_id = {
        family["id"]: family
        for family in question_families
        if isinstance(family.get("id"), str)
    }
    if not allowlist_set.issubset(question_by_id):
        raise ValueError("development allowlist refers to missing families")
    selected_questions = [question_by_id[family_id] for family_id in allowed_ids]

    tasks = [
        *(_task(family, source="calibration-v1") for family in calibration_families),
        *(
            _task(family, source="benchmark-development-questions-v1")
            for family in selected_questions
        ),
        *(
            _task(family, source="calibration-v13-development")
            for family in v13_families
        ),
    ]
    task_ids = [task["task_id"] for task in tasks]
    if len(task_ids) != len(set(task_ids)):
        raise ValueError("development inputs contain overlapping task families")
    if (
        len(calibration_families) != 10
        or len(selected_questions) != 9
        or len(v13_families) != 2
        or len(tasks) != 21
    ):
        raise ValueError(
            "development task counts do not match the approved 21-family set"
        )
    return tuple(tasks)


def _private_destination(value: str) -> Path:
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = CANONICAL_ROOT / candidate
    destination = candidate.resolve()
    private_root = PRIVATE_ROOT.resolve()
    if not destination.is_relative_to(private_root):
        raise ValueError("output must be under the canonical Phase 3 private directory")
    return destination


def _write_new_private_file(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as target:
            target.write(payload)
            target.flush()
            os.fsync(target.fileno())
    except Exception:
        path.unlink(missing_ok=True)
        raise
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        default=str(PRIVATE_ROOT / "dev-tasks-v1.json"),
        help="private output path (defaults under canonical local-reference)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    tasks = build_tasks()
    document = {
        "schema_version": 1,
        "dataset_id": "phase3-dev-tasks-v1",
        "tasks": tasks,
    }
    output = _private_destination(args.output)
    _write_new_private_file(
        output,
        (json.dumps(document, indent=2, ensure_ascii=False) + "\n").encode("utf-8"),
    )
    counts = Counter(task["source"] for task in tasks)
    print(
        json.dumps(
            {"task_count": len(tasks), "counts_by_source": dict(sorted(counts.items()))}
        )
    )


if __name__ == "__main__":
    main()
