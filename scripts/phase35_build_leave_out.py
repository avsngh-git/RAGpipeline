"""Build and publish the Phase 3.5 development leave-out generation."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import shlex
import subprocess
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import asyncpg
import httpx

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = Path("local-reference/phase3-runs/dev-tasks-v1.json")
DEFAULT_OUTPUT_ROOT = Path("local-reference/phase35")


def _load_tasks(path: Path) -> tuple[dict[str, object], ...]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise ValueError("development task schema is unsupported")
    tasks = value.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("development tasks must be a non-empty list")
    selected: list[dict[str, object]] = []
    for task in tasks:
        if not isinstance(task, dict):
            raise ValueError("development task is malformed")
        task_id = task.get("task_id")
        judged = task.get("judged_paper_ids")
        question = task.get("question")
        if (
            not isinstance(task_id, str)
            or not task_id.strip()
            or not isinstance(question, str)
            or not question.strip()
            or not isinstance(judged, list)
            or any(not isinstance(paper_id, str) or not paper_id for paper_id in judged)
        ):
            raise ValueError("development task is missing its identity, question, or judgments")
        if judged:
            selected.append(dict(task))
    if not selected:
        raise ValueError("no development families have direct-evidence paper judgments")
    return tuple(selected)


def _database_url_for_review_database(database_url: str) -> str:
    parsed = urlsplit(database_url)
    return urlunsplit(parsed._replace(path="/research_phase1_review"))


def _load_local_env() -> None:
    env_path = REPOSITORY_ROOT / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        key, separator, value = line.partition("=")
        if separator and key.strip() in {
            "OPENALEX_API_KEY",
            "RESEARCH_PLATFORM_DATABASE_URL",
            "RESEARCH_PLATFORM_QDRANT_URL",
        }:
            parsed = shlex.split(value, comments=True)
            if len(parsed) == 1:
                os.environ.setdefault(key.strip(), parsed[0])


def _sha256_json(value: object) -> str:
    data = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(data).hexdigest()


async def _build(args: argparse.Namespace) -> None:
    _load_local_env()
    from research_platform.config import Settings
    from research_platform.ingestion.generation_index import (
        GenerationIndexConfiguration,
    )
    from research_platform.ingestion.generation_registry import GenerationRegistry
    from research_platform.ingestion.indexing import IndexConfiguration
    from research_platform.ingestion.paper_index import PaperIndexRepository
    from research_platform.ingestion.snapshots import (
        SnapshotRepository,
        SnapshotValidationError,
    )

    tasks = _load_tasks(args.dataset)
    hidden_papers = sorted(
        {
            paper_id
            for task in tasks
            for paper_id in task["judged_paper_ids"]
            if isinstance(paper_id, str)
        }
    )
    settings = Settings()
    database_url = _database_url_for_review_database(settings.database_url)
    os.environ["RESEARCH_PLATFORM_DATABASE_URL"] = database_url
    source_raw = json.loads(settings.generation_configuration.read_text("utf-8"))
    if not isinstance(source_raw, dict):
        raise ValueError("generation configuration must be an object")
    source_configuration = GenerationIndexConfiguration.from_dict(source_raw)
    pool = await asyncpg.create_pool(database_url, min_size=1, max_size=4)
    try:
        async with pool.acquire() as connection:
            parent_row = await connection.fetchrow(
                """
                SELECT pointer.collection_id, pointer.published_generation,
                       generation.snapshot_id
                FROM index_generation_pointers AS pointer
                JOIN collections AS collection ON collection.id = pointer.collection_id
                JOIN index_generations AS generation
                  ON generation.collection_id = pointer.collection_id
                 AND generation.configuration_id = pointer.configuration_id
                 AND generation.generation = pointer.published_generation
                WHERE collection.name = 'research-corpus'
                  AND pointer.configuration_id = $1
                  AND pointer.published_generation = 1
                  AND generation.state = 'published'
                """,
                source_configuration.configuration_id,
            )
            if parent_row is None:
                raise ValueError("published generation 1 for the research collection was not found")
            parent_snapshot_id = parent_row["snapshot_id"]
            parent_members = await connection.fetch(
                "SELECT paper_id FROM snapshot_items WHERE snapshot_id = $1",
                parent_snapshot_id,
            )
        parent_member_ids = {str(row["paper_id"]) for row in parent_members}
        missing_hidden = sorted(set(hidden_papers) - parent_member_ids)
        if missing_hidden:
            raise ValueError(
                "a judged paper is not a member of the published source generation"
            )
        remaining_count = len(parent_member_ids) - len(hidden_papers)
        if remaining_count <= 0:
            raise ValueError("leave-out generation would be empty")

        registry = GenerationRegistry(pool)
        collection_id = await registry.ensure_collection(
            "leave-out-dev", description="Development leave-out corpus for Phase 3.5 discovery evaluation"
        )
        async with pool.acquire() as connection:
            prior_generation = await connection.fetchval(
                """
                SELECT max(generation) FROM index_generations
                WHERE collection_id = $1 AND configuration_id = $2
                """,
                collection_id,
                source_configuration.configuration_id,
            )
        if prior_generation is not None:
            raise ValueError("leave-out-dev already has a generation; refusing to overwrite it")

        snapshots = SnapshotRepository(pool)
        parent_configuration = await snapshots.configuration_for(parent_snapshot_id)
        snapshot_index_id = parent_configuration.get("index_configuration_id")
        legacy_index_options = (
            Path("configs/phase1-e5-small-v2-index.example.json"),
            Path("configs/phase2-bge-base-en-v1-5-index.example.json"),
            Path("configs/phase2-gte-modernbert-base-index.example.json"),
        )
        legacy_index_path = None
        legacy_index_configuration = None
        for candidate in legacy_index_options:
            candidate_raw = json.loads(candidate.read_text(encoding="utf-8"))
            if not isinstance(candidate_raw, dict):
                raise ValueError("legacy snapshot index configuration must be an object")
            candidate_configuration = IndexConfiguration.from_dict(candidate_raw)
            if candidate_configuration.configuration_id == snapshot_index_id:
                legacy_index_path = candidate
                legacy_index_configuration = candidate_configuration
                break
        if legacy_index_path is None or legacy_index_configuration is None:
            raise ValueError(
                "no checked-in legacy index configuration matches the source snapshot"
            )
        parent_snapshot_configuration_id = _sha256_json(parent_configuration)
        async with pool.acquire() as connection:
            existing_draft = await connection.fetchrow(
                """
                SELECT id FROM snapshots
                WHERE name = 'phase35-leave-out-dev'
                  AND status = 'draft'
                  AND configuration_id = $1
                ORDER BY created_at DESC LIMIT 1
                """,
                parent_snapshot_configuration_id,
            )
            existing_draft_members = (
                {
                    str(row["paper_id"])
                    for row in await connection.fetch(
                        "SELECT paper_id FROM snapshot_items WHERE snapshot_id = $1",
                        existing_draft["id"],
                    )
                }
                if existing_draft is not None
                else set()
            )
        if existing_draft is None:
            snapshot_id = await snapshots.create_variant_draft(
                parent_snapshot_id,
                name="phase35-leave-out-dev",
                configuration_id=parent_snapshot_configuration_id,
                configuration=parent_configuration,
                code_revision="phase35-leave-out-evaluation",
            )
        else:
            snapshot_id = existing_draft["id"]
            target_member_ids = parent_member_ids - set(hidden_papers)
            if existing_draft_members not in (parent_member_ids, target_member_ids):
                raise ValueError("an existing leave-out draft has unexpected membership")
        async with pool.acquire() as connection:
            current_members = {
                str(row["paper_id"])
                for row in await connection.fetch(
                    "SELECT paper_id FROM snapshot_items WHERE snapshot_id = $1",
                    snapshot_id,
                )
            }
        for paper_id in hidden_papers:
            if paper_id in current_members:
                await snapshots.remove_member(snapshot_id, paper_id)
        subprocess.run(
            [
                "research-ingest",
                "index",
                "rebuild",
                "--snapshot-id",
                str(snapshot_id),
                "--configuration",
                str(legacy_index_path),
                "--device",
                "cuda",
            ],
            cwd=REPOSITORY_ROOT,
            check=True,
        )
        try:
            finalized = await snapshots.finalize(
                snapshot_id,
                reviewer="assistant:leave-out-eval",
                minimum_papers=remaining_count,
            )
        except SnapshotValidationError as error:
            if any(issue.code == "index_not_built" for issue in error.report.issues):
                raise RuntimeError(
                    "leave-out finalization is blocked: the temporary legacy validation "
                    "index did not register a valid snapshot index state"
                ) from None
            raise
        if finalized.member_count != remaining_count:
            raise ValueError("finalized leave-out snapshot has an unexpected member count")

        from research_platform.ingestion.generation_build import (
            GenerationInputRepository,
        )
        from research_platform.ingestion.sparse_build import compute_lexical_averages

        lexical = None
        if source_configuration.lexical is not None:
            averages = await compute_lexical_averages(
                GenerationInputRepository(pool),
                PaperIndexRepository(pool),
                snapshot_id,
            )
            lexical = averages.settings()
        leaveout_configuration = replace(
            source_configuration,
            passages_collection="leaveout-passages-gte-bm25-v1",
            papers_collection="leaveout-papers-gte-bm25-v1",
            lexical=lexical,
        )
        await registry.register_configuration(
            leaveout_configuration.configuration_id, leaveout_configuration.to_dict()
        )
        output_root = args.output_root
        output_root.mkdir(parents=True, exist_ok=True)
        configuration_path = output_root / "leaveout-dev-generation-index.json"
        configuration_path.write_text(
            json.dumps(leaveout_configuration.to_dict(), indent=2) + "\n",
            encoding="utf-8",
        )
        details_path = output_root / "leaveout-dev-build.json"
        details_path.write_text(
            json.dumps(
                {
                    "created_at": datetime.now(UTC).isoformat(),
                    "dataset_path": str(args.dataset),
                    "dataset_sha256": "sha256:" + hashlib.sha256(args.dataset.read_bytes()).hexdigest(),
                    "selected_family_count": len(tasks),
                    "hidden_paper_count": len(hidden_papers),
                    "source_snapshot_id": str(parent_snapshot_id),
                    "snapshot_id": str(snapshot_id),
                    "collection_name": "leave-out-dev",
                    "generation_configuration_id": leaveout_configuration.configuration_id,
                    "generation_configuration_path": str(configuration_path),
                    "temporary_validation_index_collection": legacy_index_configuration.collection_name,
                    "hidden_paper_ids": hidden_papers,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    finally:
        await pool.close()

    cli = [
        "research-ingest",
        "generations",
        "build",
        "--collection-name",
        "leave-out-dev",
        "--snapshot-id",
        str(snapshot_id),
        "--configuration",
        str(configuration_path),
        "--reuse-dense-generation-configuration",
        str(settings.generation_configuration),
    ]
    subprocess.run(cli, cwd=REPOSITORY_ROOT, check=True)
    for command in ("sync-papers", "verify", "publish"):
        subprocess.run(
            [
                "research-ingest",
                "generations",
                command,
                "--collection-name",
                "leave-out-dev",
                "--configuration",
                str(configuration_path),
                "--generation",
                "1",
            ],
            cwd=REPOSITORY_ROOT,
            check=True,
        )
    async with httpx.AsyncClient(
        base_url=settings.qdrant_url.rstrip("/"), timeout=30
    ) as http:
        response = await http.delete(
            "/collections/" + legacy_index_configuration.collection_name
        )
        response.raise_for_status()
    build_details = json.loads(details_path.read_text(encoding="utf-8"))
    if not isinstance(build_details, dict):
        raise ValueError("leave-out build record is malformed")
    build_details["temporary_validation_index_deleted"] = True
    details_path.write_text(json.dumps(build_details, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "snapshot_id": str(snapshot_id),
                "generation": 1,
                "member_count": remaining_count,
                "hidden_paper_count": len(hidden_papers),
                "selected_family_count": len(tasks),
                "configuration_path": str(configuration_path),
                "details_path": str(details_path),
            },
            indent=2,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    args = parser.parse_args()
    asyncio.run(_build(args))


if __name__ == "__main__":
    main()
