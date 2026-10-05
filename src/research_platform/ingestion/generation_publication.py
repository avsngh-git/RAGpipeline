"""Verify, publish and purge index generations (P35-08, ADR-0023 items 4 and 7)."""

from __future__ import annotations

import hashlib
import random
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Protocol, cast
from uuid import UUID

import asyncpg  # type: ignore[import-untyped]

from research_platform.ingestion.generation_build import PassageInputSource
from research_platform.ingestion.generation_index import (
    GenerationQdrantCollection,
    generation_filter,
    indexed_paper_filter,
    passage_point_id,
    with_conditions,
)
from research_platform.ingestion.generation_registry import (
    GenerationRecord,
    PublicationConflict,
)

REQUIRED_PASSAGE_FIELDS = (
    "evidence_id",
    "paper_id",
    "document_id",
    "document_version",
    "document_version_kind",
    "extraction_id",
    "source_artifact_id",
    "source_artifact_sha256",
    "publication_year",
    "evidence_kind",
    "paper_title",
    "section_id",
    "section_title",
    "chunking_configuration_id",
    "source_location",
    "source_spans",
    "evidence_metadata",
    "section_ordinal",
    "start_offset",
    "end_offset",
    "text",
    "text_sha256",
    "index_configuration_id",
    "payload_revision",
    "added_generation",
)
_PROBE_SCORE = 0.9999


@dataclass(frozen=True)
class VerificationReport:
    generation: int
    expected_count: int
    observed_count: int
    missing_count: int
    unexpected_count: int
    hash_mismatch_count: int
    missing_payload_field_count: int
    unindexed_member_paper_count: int
    probe_failures: int
    passed: bool


class VerificationRegistry(Protocol):
    async def get(
        self, collection_id: UUID, configuration_id: str, generation: int
    ) -> GenerationRecord: ...

    async def mark_verified(
        self,
        collection_id: UUID,
        configuration_id: str,
        generation: int,
        *,
        point_count: int,
        details: Mapping[str, object],
    ) -> None: ...

    async def mark_failed(
        self,
        collection_id: UUID,
        configuration_id: str,
        generation: int,
        *,
        reason: str,
    ) -> None: ...


class PublicationRegistry(Protocol):
    async def get(
        self, collection_id: UUID, configuration_id: str, generation: int
    ) -> GenerationRecord: ...

    async def published(
        self, collection_id: UUID, configuration_id: str
    ) -> GenerationRecord | None: ...

    async def publish(
        self,
        collection_id: UUID,
        configuration_id: str,
        generation: int,
        *,
        expected_predecessor: int | None,
    ) -> None: ...


class SnapshotMembers(Protocol):
    async def snapshot_member_ids(self, snapshot_id: UUID) -> frozenset[str]: ...


async def inspect_generation(
    *,
    record: GenerationRecord,
    inputs: PassageInputSource,
    papers_repository: SnapshotMembers,
    passages: GenerationQdrantCollection,
    papers: GenerationQdrantCollection,
    probe_count: int = 3,
    seed: int = 35,
) -> VerificationReport:
    """Compare a generation's points with its snapshot without changing its state."""
    configuration_id = record.configuration_id
    generation = record.generation
    expected = {
        item.evidence_id: item.text_sha256
        for item in await inputs.load_passage_inputs(record.snapshot_id)
    }
    visible = generation_filter(generation)
    observed = {
        cast(str, payload["evidence_id"]): payload
        for payload in await passages.scroll_payloads(
            filter_=visible, fields=list(REQUIRED_PASSAGE_FIELDS)
        )
    }
    observed_count = await passages.count(visible)
    missing = set(expected) - set(observed)
    unexpected = set(observed) - set(expected)
    hash_mismatches = 0
    missing_fields = 0
    for evidence_id, payload in observed.items():
        if any(field not in payload for field in REQUIRED_PASSAGE_FIELDS):
            missing_fields += 1
        text = payload.get("text")
        text_hash = payload.get("text_sha256")
        if (
            not isinstance(text, str)
            or hashlib.sha256(text.encode("utf-8")).hexdigest() != text_hash
            or (evidence_id in expected and expected[evidence_id] != text_hash)
            or payload.get("index_configuration_id") != configuration_id
        ):
            hash_mismatches += 1
    members = await papers_repository.snapshot_member_ids(record.snapshot_id)
    indexed = {
        cast(str, payload["paper_id"])
        for payload in await papers.scroll_payloads(
            filter_=indexed_paper_filter(generation), fields=["paper_id"]
        )
    }
    probe_failures = await _probe(
        passages,
        sorted(set(expected) & set(observed)),
        observed,
        configuration_id=configuration_id,
        generation=generation,
        probe_count=probe_count,
        seed=seed,
    )
    unindexed = len(members - indexed)
    passed = (
        observed_count == len(expected) == len(observed)
        and not missing
        and not unexpected
        and hash_mismatches == 0
        and missing_fields == 0
        and unindexed == 0
        and probe_failures == 0
    )
    return VerificationReport(
        generation=generation,
        expected_count=len(expected),
        observed_count=observed_count,
        missing_count=len(missing),
        unexpected_count=len(unexpected),
        hash_mismatch_count=hash_mismatches,
        missing_payload_field_count=missing_fields,
        unindexed_member_paper_count=unindexed,
        probe_failures=probe_failures,
        passed=passed,
    )


async def verify_generation(
    *,
    registry: VerificationRegistry,
    inputs: PassageInputSource,
    papers_repository: SnapshotMembers,
    passages: GenerationQdrantCollection,
    papers: GenerationQdrantCollection,
    collection_id: UUID,
    configuration_id: str,
    generation: int,
    probe_count: int = 3,
    seed: int = 35,
) -> VerificationReport:
    """Compare a built generation with its snapshot; mark it verified or failed."""
    record = await registry.get(collection_id, configuration_id, generation)
    if record.state != "building":
        raise PublicationConflict(f"generation {generation} is {record.state}")
    report = await inspect_generation(
        record=record,
        inputs=inputs,
        papers_repository=papers_repository,
        passages=passages,
        papers=papers,
        probe_count=probe_count,
        seed=seed,
    )
    if report.passed:
        await registry.mark_verified(
            collection_id,
            configuration_id,
            generation,
            point_count=report.observed_count,
            details=asdict(report),
        )
    else:
        await registry.mark_failed(
            collection_id, configuration_id, generation, reason="verification_failed"
        )
    return report


async def publish_generation(
    registry: PublicationRegistry,
    collection_id: UUID,
    configuration_id: str,
    generation: int,
) -> None:
    """Publish a verified generation after the currently published one.

    Generations between the two must all have failed; a failed build never blocks
    later publication.
    """
    current = await registry.published(collection_id, configuration_id)
    current_generation = None if current is None else current.generation
    first_skipped = 1 if current_generation is None else current_generation + 1
    if generation < first_skipped:
        raise PublicationConflict(
            f"generation {generation} must follow published generation "
            f"{current_generation}"
        )
    for skipped in range(first_skipped, generation):
        record = await registry.get(collection_id, configuration_id, skipped)
        if record.state != "failed":
            raise PublicationConflict(
                f"generation {generation} must follow published generation "
                f"{current_generation}; generation {skipped} is {record.state}"
            )
    await registry.publish(
        collection_id,
        configuration_id,
        generation,
        expected_predecessor=current_generation,
    )


async def oldest_readable_generation(
    pool: asyncpg.Pool, published_generation: int
) -> int:
    """The oldest generation a published pointer or an unfinished run can still read."""
    async with pool.acquire() as connection:
        oldest_run = await connection.fetchval(
            """
            SELECT min(generation) FROM research_runs
            WHERE generation IS NOT NULL AND status NOT IN ('completed', 'failed')
            """
        )
    return (
        published_generation
        if oldest_run is None
        else min(published_generation, int(oldest_run))
    )


async def purge_retired(
    *,
    pool: asyncpg.Pool,
    registry: PublicationRegistry,
    passages: GenerationQdrantCollection,
    collection_id: UUID,
    configuration_id: str,
    dry_run: bool = True,
) -> int:
    """Count, and unless ``dry_run`` delete, points no readable generation can see."""
    published = await registry.published(collection_id, configuration_id)
    if published is None:
        return 0
    oldest = await oldest_readable_generation(pool, published.generation)
    purgeable = {"must": [{"key": "retired_generation", "range": {"lte": oldest}}]}
    count = await passages.count(purgeable)
    if count and not dry_run:
        await passages.delete_matching(purgeable)
    return count


async def _probe(
    passages: GenerationQdrantCollection,
    candidates: list[str],
    observed: Mapping[str, Mapping[str, object]],
    *,
    configuration_id: str,
    generation: int,
    probe_count: int,
    seed: int,
) -> int:
    """Each probe point's own vector must find it, or an identical-text twin, first."""
    if not candidates:
        return probe_count
    chosen = random.Random(seed).sample(candidates, min(probe_count, len(candidates)))
    points = await passages.retrieve(
        [passage_point_id(evidence_id, configuration_id) for evidence_id in chosen],
        with_dense=True,
    )
    failures = len(chosen) - len(points)
    for point in points:
        payload = observed[cast(str, point.payload["evidence_id"])]
        if point.dense is None:
            failures += 1
            continue
        top = await passages.query_dense(
            point.dense,
            filter_=with_conditions(
                generation_filter(generation),
                [{"key": "paper_id", "match": {"value": payload["paper_id"]}}],
            ),
            limit=1,
        )
        if (
            not top
            or top[0].score < _PROBE_SCORE
            or top[0].payload.get("text_sha256") != payload["text_sha256"]
        ):
            failures += 1
    return failures
