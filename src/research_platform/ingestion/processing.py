"""Permission-gated PDF extraction and source-linked evidence persistence."""

from __future__ import annotations

import asyncio
import hashlib
import json
import resource
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Mapping, cast
from uuid import UUID, uuid5

import asyncpg  # type: ignore[import-untyped]

from research_platform.ingestion.artifact_repository import ArtifactRepository
from research_platform.ingestion.artifacts import ArtifactError, resolve_registered_pdf
from research_platform.ingestion.embeddings import (
    E5_SMALL_V2_MODEL,
    E5_SMALL_V2_PREPROCESSING,
    E5_SMALL_V2_REVISION,
    E5SmallV2Embedder,
)
from research_platform.ingestion.evidence import (
    ChunkingConfig,
    EvidenceUnit,
    ExtractionResult,
    chunk_section,
    chunk_table_rows,
)
from research_platform.ingestion.evidence_repository import EvidenceRepository
from research_platform.ingestion.pdf_extraction import (
    DoclingPdfConfig,
    DoclingPdfExtractor,
    PdfExtractionError,
    tables_requiring_vision_review,
)
from research_platform.ingestion.provenance import code_revision
from research_platform.ingestion.runner import (
    DocumentStageFailure,
    StageContext,
    StageOutcome,
)
from research_platform.ingestion.snapshots import SnapshotRepository


@dataclass(frozen=True)
class PreparedPdfPipeline:
    effective_configuration: Mapping[str, object]
    configuration_id: str


class PdfEvidenceProcessor:
    """Extract, chunk and persist one authorized snapshot member idempotently."""

    def __init__(
        self,
        pool: asyncpg.Pool,
        *,
        snapshot_id: UUID,
        artifact_root: Path,
        parser_config: DoclingPdfConfig,
        chunking_config: ChunkingConfig,
        tokenizer: E5SmallV2Embedder,
    ) -> None:
        self._pool = pool
        self._snapshot_id = snapshot_id
        self._artifact_root = artifact_root
        self._parser = DoclingPdfExtractor(parser_config)
        self._chunking = chunking_config
        self._tokenizer = tokenizer
        self._prepared: PreparedPdfPipeline | None = None

    async def prepare(self) -> PreparedPdfPipeline:
        """Load the fixed parser and offset tokenizer before leasing a job."""
        if self._prepared is not None:
            return self._prepared
        parser_configuration, parser_id = await asyncio.to_thread(self._parser.prepare)
        await asyncio.to_thread(self._tokenizer.token_spans, "")
        processor_revision = await asyncio.to_thread(code_revision)
        effective_configuration: dict[str, object] = {
            "schema_version": 1,
            "parser": parser_configuration,
            "chunking": self._chunking.to_dict(),
            "processor_code_revision": processor_revision,
            "chunk_tokenizer": {
                "model": E5_SMALL_V2_MODEL,
                "revision": E5_SMALL_V2_REVISION,
                "preprocessing_revision": E5_SMALL_V2_PREPROCESSING,
            },
        }
        configuration_id = _identity(effective_configuration)
        self._prepared = PreparedPdfPipeline(
            effective_configuration=effective_configuration,
            configuration_id=configuration_id,
        )
        if not parser_id.startswith("sha256:"):
            raise RuntimeError("parser returned an invalid configuration identity")
        return self._prepared

    async def process(self, context: StageContext) -> StageOutcome:
        prepared = await self.prepare()
        if context.configuration_id != prepared.configuration_id:
            raise DocumentStageFailure(
                "pipeline_configuration_changed",
                "effective extraction configuration changed; create a new job",
                retryable=False,
            )
        started = time.perf_counter()
        artifact = await ArtifactRepository(self._pool).permitted_source_pdf(
            context.document_id, require_indexing=True
        )
        expected_fingerprint = f"sha256:{artifact.sha256}"
        if context.input_fingerprint != expected_fingerprint:
            raise DocumentStageFailure(
                "source_artifact_changed",
                "the selected source PDF checksum changed after job creation",
                retryable=False,
            )
        try:
            pdf_path = await asyncio.to_thread(
                resolve_registered_pdf,
                self._artifact_root,
                artifact.storage_path,
                sha256=artifact.sha256,
                byte_size=artifact.byte_size,
            )
        except ArtifactError:
            raise DocumentStageFailure(
                "source_artifact_invalid",
                "the selected source PDF failed path or checksum validation",
                retryable=False,
            ) from None

        extraction_id = uuid5(context.document_id, prepared.configuration_id)
        try:
            result = await asyncio.to_thread(
                self._parser.extract,
                pdf_path,
                document_id=context.document_id,
                extraction_id=extraction_id,
                source_artifact_id=artifact.association_id,
            )
        except PdfExtractionError as error:
            raise DocumentStageFailure(
                error.category,
                "the selected PDF could not be processed by the pinned parser",
                retryable=error.category in {"parser_error", "parser_partial"},
            ) from None
        parser_id = _identity(dict(result.configuration))
        expected_parser = _identity(
            cast(Mapping[str, object], prepared.effective_configuration["parser"])
        )
        if parser_id != expected_parser:
            raise DocumentStageFailure(
                "parser_configuration_changed",
                "the effective parser options changed during the run",
                retryable=False,
            )

        flagged = set(tables_requiring_vision_review(result))
        reviewed_tables = tuple(
            replace(table, requires_vision_review=table.ordinal in flagged)
            for table in result.tables
        )
        result_configuration = dict(prepared.effective_configuration)
        result = replace(
            result,
            extraction_id=extraction_id,
            configuration_id=prepared.configuration_id,
            configuration=result_configuration,
            tables=reviewed_tables,
        )
        units = await self._chunk_async(result)
        try:
            persisted = await EvidenceRepository(self._pool).persist(result, units)
            await SnapshotRepository(self._pool).set_extraction(
                self._snapshot_id, context.document_id, extraction_id
            )
        except ValueError as error:
            # Parser/data-controlled details are intentionally omitted from job logs.
            category = (
                "table_chunk_limit_exceeded"
                if "table row exceeds" in str(error)
                else "evidence_persistence_invalid"
            )
            raise DocumentStageFailure(
                category, "evidence could not be persisted"
            ) from None

        output_references: dict[str, object] = {
            "snapshot_id": str(self._snapshot_id),
            "extraction_id": str(extraction_id),
            "source_artifact_id": str(artifact.association_id),
            "configuration_id": prepared.configuration_id,
            "section_count": persisted.section_count,
            "table_count": persisted.table_count,
            "chunk_count": persisted.evidence_unit_count,
            "vision_review_table_ordinals": sorted(flagged),
        }
        fingerprint = _identity(
            {
                **output_references,
                "evidence_unit_ids": [unit.id for unit in units],
            }
        )
        measurements = {
            "elapsed_seconds": round(time.perf_counter() - started, 3),
            "source_bytes": artifact.byte_size,
            "process_peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            * 1024,
            "sections": persisted.section_count,
            "tables": persisted.table_count,
            "chunks": persisted.evidence_unit_count,
            "flagged_tables": len(flagged),
            "reused_existing": persisted.reused_existing,
        }
        return StageOutcome(
            output_fingerprint=fingerprint,
            output_references=output_references,
            resource_measurements=measurements,
        )

    def _chunk(self, result: ExtractionResult) -> tuple[EvidenceUnit, ...]:
        units: list[EvidenceUnit] = []
        try:
            for section in result.sections:
                units.extend(
                    chunk_section(
                        section,
                        document_id=result.document_id,
                        extraction_id=result.extraction_id,
                        config=self._chunking,
                        tokenizer=self._tokenizer,
                    )
                )
            for table in result.tables:
                units.extend(
                    chunk_table_rows(
                        table,
                        document_id=result.document_id,
                        extraction_id=result.extraction_id,
                        config=self._chunking,
                        tokenizer=self._tokenizer,
                    )
                )
        except ValueError as error:
            if "one table row exceeds" in str(error):
                raise DocumentStageFailure(
                    "table_chunk_limit_exceeded",
                    "a table row is larger than the searchable token limit",
                    retryable=False,
                ) from None
            raise
        return tuple(units)

    async def _chunk_async(self, result: ExtractionResult) -> tuple[EvidenceUnit, ...]:
        """Keep CPU-bound tokenization off the event loop used for job leases."""
        return await asyncio.to_thread(self._chunk, result)


def _identity(value: Mapping[str, object]) -> str:
    canonical = json.dumps(
        dict(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
