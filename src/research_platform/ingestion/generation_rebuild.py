"""Rebuild published generations into empty collections (ADR-0023; spec section 22).

Qdrant is a derived store: replaying each published generation's snapshot from
PostgreSQL reproduces the passages and papers collections, which are then inspected
against their manifests without changing registry state.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from research_platform.ingestion.generation_build import (
    DenseVectorSource,
    GenerationBuildReport,
    GenerationInputRepository,
    passage_manifest_sha256,
    write_generation_points,
)
from research_platform.ingestion.generation_index import (
    GenerationIndexConfiguration,
    GenerationQdrantCollection,
)
from research_platform.ingestion.generation_publication import (
    VerificationReport,
    inspect_generation,
)
from research_platform.ingestion.generation_registry import GenerationRegistry
from research_platform.ingestion.indexing import VectorEmbedder
from research_platform.ingestion.paper_index import PaperIndexRepository, sync_papers


@dataclass(frozen=True)
class RebuildReport:
    builds: tuple[GenerationBuildReport, ...]
    inspections: tuple[VerificationReport, ...]

    @property
    def passed(self) -> bool:
        return bool(self.inspections) and all(i.passed for i in self.inspections)


async def rebuild_generations(
    *,
    registry: GenerationRegistry,
    inputs: GenerationInputRepository,
    papers_repository: PaperIndexRepository,
    passages: GenerationQdrantCollection,
    papers: GenerationQdrantCollection,
    embedder: VectorEmbedder,
    configuration: GenerationIndexConfiguration,
    collection_id: UUID,
    vector_source: DenseVectorSource | None = None,
) -> RebuildReport:
    """Replay generations 1..published into empty collections and inspect each."""
    configuration_id = configuration.configuration_id
    published = await registry.published(collection_id, configuration_id)
    if published is None:
        raise ValueError("the collection has no published generation to rebuild")
    for collection in (passages, papers):
        if await collection.exists() and await collection.count({}) > 0:
            raise ValueError(f"rebuild requires an empty collection: {collection.name}")
    builds: list[GenerationBuildReport] = []
    records = []
    async with registry.build_lock(configuration_id):
        for generation in range(1, published.generation + 1):
            record = await registry.get(collection_id, configuration_id, generation)
            if record.state != "published":
                raise ValueError(f"generation {generation} was never published")
            loaded = await inputs.load_passage_inputs(record.snapshot_id)
            if passage_manifest_sha256(loaded) != record.manifest_sha256:
                raise ValueError(
                    f"generation {generation} snapshot evidence no longer matches "
                    "its manifest"
                )
            builds.append(
                await write_generation_points(
                    record,
                    loaded,
                    passages=passages,
                    embedder=embedder,
                    configuration=configuration,
                    vector_source=vector_source,
                    sparse_encoder=None,
                )
            )
            await sync_papers(
                repository=papers_repository,
                papers=papers,
                embedder=embedder,
                configuration=configuration,
                generation=generation,
                snapshot_id=record.snapshot_id,
            )
            records.append(record)
    inspections = [
        await inspect_generation(
            record=record,
            inputs=inputs,
            papers_repository=papers_repository,
            passages=passages,
            papers=papers,
        )
        for record in records
    ]
    return RebuildReport(builds=tuple(builds), inspections=tuple(inspections))
