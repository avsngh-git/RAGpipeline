"""Run or resume a bounded OpenAlex discovery job."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from research_platform.ingestion.config import DiscoveryConfig
from research_platform.ingestion.discovery_repository import (
    DiscoveryRepository,
    RequestBudgetExceeded,
)
from research_platform.ingestion.openalex import (
    OpenAlexClient,
    OpenAlexRequestError,
    OpenAlexResponseError,
)


@dataclass(frozen=True)
class DiscoveryOutcome:
    run_id: UUID
    pages_saved: int
    request_attempts: int
    status: str


async def run_discovery(
    run_id: UUID,
    configuration: DiscoveryConfig,
    repository: DiscoveryRepository,
    client: OpenAlexClient,
) -> DiscoveryOutcome:
    """Run pending queries from their durable cursor checkpoints."""
    await repository.start_run(run_id, configuration.config_id)
    pages_saved = 0
    try:
        resume_points = {
            point.query_index: point for point in await repository.resume_points(run_id)
        }
        for query_index, _query in enumerate(configuration.queries):
            point = resume_points.get(query_index)
            if point is None:
                continue
            async for page in client.pages_for_query(
                query_index,
                start_cursor=point.cursor,
                start_page_number=point.pages_completed,
            ):
                if await repository.save_page(run_id, page, configuration):
                    pages_saved += 1

        for exception_index, openalex_id in enumerate(
            configuration.older_paper_exceptions
        ):
            query_index = len(configuration.queries) + exception_index
            if query_index not in resume_points:
                continue
            page = await client.get_older_exception(openalex_id, query_index)
            if await repository.save_page(run_id, page, configuration):
                pages_saved += 1
    except (OpenAlexRequestError, RequestBudgetExceeded) as error:
        await repository.set_run_status(run_id, "paused", str(error))
        raise
    except OpenAlexResponseError as error:
        await repository.set_run_status(run_id, "failed", str(error))
        raise

    await repository.set_run_status(run_id, "completed")
    return DiscoveryOutcome(
        run_id=run_id,
        pages_saved=pages_saved,
        request_attempts=client.requests_used,
        status="completed",
    )
