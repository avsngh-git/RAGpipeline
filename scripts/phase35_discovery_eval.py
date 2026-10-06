"""Run the private Phase 3.5 leave-out discovery diagnostic."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import shlex
import statistics
from collections import Counter
from contextlib import AsyncExitStack
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import asyncpg
import httpx

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = Path("local-reference/phase3-runs/dev-tasks-v1.json")
DEFAULT_CONFIG = Path("local-reference/phase35/leaveout-dev-generation-index.json")
DEFAULT_RAW_OUTPUT = Path("local-reference/phase35/discovery-report-raw.json")
DEFAULT_REPORT = Path("docs/reference/phase-3.5-discovery-report.md")


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
        question = task.get("question")
        judged = task.get("judged_paper_ids")
        filters = task.get("filters")
        if (
            not isinstance(task_id, str)
            or not task_id.strip()
            or not isinstance(question, str)
            or not question.strip()
            or not isinstance(judged, list)
            or any(not isinstance(paper_id, str) or not paper_id for paper_id in judged)
            or (filters is not None and not isinstance(filters, dict))
        ):
            raise ValueError(
                "development task is missing identity, question, or judgments"
            )
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


async def _evaluate(args: argparse.Namespace) -> dict[str, object]:
    _load_local_env()
    from research_platform.api.app import _build_discovery_embedder
    from research_platform.config import DiscoverySettings, Settings
    from research_platform.discovery.online import OnlineDiscovery, SpendLedger
    from research_platform.ingestion.catalog import CatalogRepository
    from research_platform.ingestion.config import (
        DiscoveryConfig,
        DiscoveryLimits,
        YearRange,
    )
    from research_platform.ingestion.embeddings import create_embedder_for_configuration
    from research_platform.ingestion.generation_index import (
        GenerationIndexConfiguration,
        GenerationQdrantCollection,
    )
    from research_platform.ingestion.openalex import (
        OPENALEX_API_BASE,
        OpenAlexClient,
        OpenAlexRequestError,
    )
    from research_platform.persistence.migrations import apply_migrations

    tasks = _load_tasks(args.dataset)
    settings = Settings()
    if settings.openalex_api_key is None:
        raise ValueError(
            "OPENALEX_API_KEY is required for the live development diagnostic"
        )
    database_url = _database_url_for_review_database(settings.database_url)
    os.environ["RESEARCH_PLATFORM_DATABASE_URL"] = database_url
    configuration_raw = json.loads(args.configuration.read_text(encoding="utf-8"))
    if not isinstance(configuration_raw, dict):
        raise ValueError("generation configuration must be an object")
    configuration = GenerationIndexConfiguration.from_dict(configuration_raw)
    discovery_settings = DiscoverySettings()
    discovery_config = DiscoveryConfig(
        queries=("development leave-out evaluation",),
        year_range=YearRange(start_year=2020, end_year=datetime.now(UTC).year),
        limits=DiscoveryLimits(
            per_page=discovery_settings.results_per_request,
            max_pages_per_query=discovery_settings.max_search_requests_per_run,
            max_total_requests=discovery_settings.max_search_requests_per_run,
            max_retries=2,
            timeout_seconds=15.0,
            minimum_request_interval_seconds=1.0,
        ),
    )
    dense_embedder = create_embedder_for_configuration(
        configuration.dense_configuration(), device="cpu"
    )
    pool = await asyncpg.create_pool(database_url, min_size=1, max_size=3)
    output_root = args.raw_output.parent
    output_root.mkdir(parents=True, exist_ok=True)
    request_count = 0
    failures: Counter[str] = Counter()
    recalls: list[float] = []
    discovered_hidden_count = 0
    route_confirmed_count = 0
    judged_hidden_count = 0
    started_at = datetime.now(UTC)
    try:
        async with AsyncExitStack() as stack:
            stack.callback(dense_embedder.close)
            http = await stack.enter_async_context(
                httpx.AsyncClient(base_url=settings.qdrant_url.rstrip("/"), timeout=60)
            )
            openalex_http = await stack.enter_async_context(
                httpx.AsyncClient(
                    base_url=OPENALEX_API_BASE,
                    timeout=httpx.Timeout(15.0),
                )
            )
            await apply_migrations(database_url)
            embedder = await _build_discovery_embedder(
                dense_embedder, pool, configuration
            )
            service = OnlineDiscovery(
                openalex=OpenAlexClient(
                    discovery_config, settings.openalex_api_key, openalex_http
                ),
                catalog=CatalogRepository(pool),
                papers=GenerationQdrantCollection(configuration, "papers", http),
                embedder=embedder,
                configuration=configuration,
                ledger=SpendLedger(pool),
                settings=discovery_settings,
            )
            original_reserve = service.ledger.reserve

            async def counted_reserve(
                *call_args: object, **call_kwargs: object
            ) -> None:
                nonlocal request_count
                await original_reserve(*call_args, **call_kwargs)
                request_count += 1

            service.ledger.reserve = counted_reserve
            async with pool.acquire() as connection:
                published = await connection.fetchval(
                    """
                    SELECT pointer.published_generation
                    FROM index_generation_pointers AS pointer
                    JOIN collections AS collection ON collection.id = pointer.collection_id
                    WHERE collection.name = 'leave-out-dev'
                      AND pointer.configuration_id = $1
                    """,
                    configuration.configuration_id,
                )
                if published != 1:
                    raise ValueError("leave-out-dev generation 1 is not published")

            for task in tasks:
                question = task["question"]
                hidden = set(task["judged_paper_ids"])
                if not isinstance(question, str):
                    raise ValueError("development task is malformed")
                judged_hidden_count += len(hidden)
                filters = task.get("filters")
                filter_values = filters if isinstance(filters, dict) else {}
                try:
                    discovered = await service.discover(
                        run_id=None,
                        question=question,
                        query=_openalex_search_query(question),
                        year_from=_optional_year(filter_values.get("year_from")),
                        year_to=_optional_year(filter_values.get("year_to")),
                        limit=10,
                    )
                except Exception as error:
                    category = type(error).__name__
                    if isinstance(error, OpenAlexRequestError):
                        category = f"{category}: {error}"
                    failures[category] += 1
                    continue
                discovered_ids = {paper.openalex_id for paper in discovered}
                found = discovered_ids & hidden
                discovered_hidden_count += len(found)
                recalls.append(len(found) / len(hidden))
                if found:
                    async with pool.acquire() as connection:
                        route_confirmed = await connection.fetch(
                            """
                            SELECT DISTINCT document.paper_id
                            FROM documents AS document
                            JOIN document_artifacts AS artifact
                              ON artifact.document_id = document.id
                            JOIN document_permission_evidence AS permission
                              ON permission.document_id = artifact.document_id
                             AND permission.id = artifact.permission_evidence_id
                            WHERE document.paper_id = ANY($1::text[])
                              AND artifact.storage_permitted
                              AND artifact.indexing_permitted
                              AND permission.storage_permitted
                              AND permission.indexing_permitted
                            """,
                            sorted(found),
                        )
                    route_confirmed_count += len(route_confirmed)
    finally:
        await pool.close()

    finished_at = datetime.now(UTC)
    spend_usd = request_count * float(discovery_settings.search_request_cost_usd)
    return {
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "dataset_sha256": "sha256:"
        + hashlib.sha256(args.dataset.read_bytes()).hexdigest(),
        "generation_configuration_id": configuration.configuration_id,
        "collection_name": "leave-out-dev",
        "generation": 1,
        "selected_family_count": len(tasks),
        "successful_family_count": len(tasks) - sum(failures.values()),
        "failure_count": sum(failures.values()),
        "failure_types": dict(sorted(failures.items())),
        "mean_recall_at_10": statistics.fmean(recalls) if recalls else None,
        "median_recall_at_10": statistics.median(recalls) if recalls else None,
        "judged_hidden_paper_count_with_repeats": judged_hidden_count,
        "hidden_papers_found_at_10_with_repeats": discovered_hidden_count,
        "found_hidden_papers_with_permitted_route": route_confirmed_count,
        "openalex_search_requests": request_count,
        "openalex_spend_usd": round(spend_usd, 6),
        "limitations": [
            "This is a development-only diagnostic; it does not establish production discovery quality.",
            "The family sample is small and selected from tasks with direct-evidence paper judgments.",
            "Recall is based on OpenAlex work identifiers and a top-10 candidate limit; metrics are unavailable when every family fails.",
            "A recorded permitted route means stored permission evidence allows storage and indexing; it does not guarantee a new download will succeed.",
        ],
    }


def _openalex_search_query(question: str) -> str:
    """Remove OpenAlex wildcard syntax while preserving the ranking question."""
    normalized = question.translate(str.maketrans({"?": " ", "*": " "}))
    return " ".join(normalized.split())


def _optional_year(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("development year filters must be integers")
    return value


def _format_metric(value: object) -> str:
    return "N/A" if value is None else f"{float(value):.3f}"


def _render_report(result: dict[str, object]) -> str:
    return "\n".join(
        (
            "# Phase 3.5 discovery report",
            "",
            "Status: development-only Gate C measurement; reported, not gated.",
            "",
            "The leave-out corpus excludes every directly judged paper from selected development families. OpenAlex search uses each question with wildcard punctuation removed; candidate ranking keeps the original question and uses the published leave-out generation.",
            "",
            "| Measure | Result |",
            "|---|---:|",
            f"| Selected development families | {result['selected_family_count']} |",
            f"| Families completed | {result['successful_family_count']} |",
            f"| Families with discovery errors | {result['failure_count']} |",
            f"| Mean hidden-paper recall@10 | {_format_metric(result['mean_recall_at_10'])} |",
            f"| Median hidden-paper recall@10 | {_format_metric(result['median_recall_at_10'])} |",
            f"| Hidden-paper hits at 10 (with repeats) | {result['hidden_papers_found_at_10_with_repeats']} |",
            f"| Hits with a recorded permitted source route | {result['found_hidden_papers_with_permitted_route']} |",
            f"| OpenAlex search requests | {result['openalex_search_requests']} |",
            f"| OpenAlex search spend | ${float(result['openalex_spend_usd']):.3f} |",
            "",
            "## Limitations",
            "",
            *[f"- {item}" for item in result["limitations"]],
            "",
            "Raw family-level inputs and outputs remain under `local-reference/phase35/` and are not part of this report.",
            "",
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--configuration", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--raw-output", type=Path, default=DEFAULT_RAW_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    result = asyncio.run(_evaluate(args))
    args.raw_output.parent.mkdir(parents=True, exist_ok=True)
    args.raw_output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(_render_report(result), encoding="utf-8")
    print(
        json.dumps(
            {key: value for key, value in result.items() if key != "limitations"},
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
