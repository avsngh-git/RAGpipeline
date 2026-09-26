"""Permission-gated PDF extraction and source-linked evidence persistence."""

from __future__ import annotations

import asyncio
import hashlib
import json
import resource
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Mapping
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
    EvidenceChunkingError,
    EvidenceUnit,
    ExtractedSection,
    ExtractedTable,
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
from research_platform.ingestion.runner import (
    DocumentStageFailure,
    StageContext,
    StageOutcome,
)
from research_platform.ingestion.snapshots import SnapshotRepository


@dataclass(frozen=True)
class PreparedPdfPipeline:
    extraction_configuration: Mapping[str, object]
    extraction_configuration_id: str
    chunking_configuration: Mapping[str, object]
    chunking_configuration_id: str


EXTRACTION_IMPLEMENTATION_REVISION = "phase1-pdf-extraction-v2"
CHUNKING_IMPLEMENTATION_REVISION = "phase1-evidence-chunking-v2"


class PdfEvidenceProcessor:
    """Extract source evidence once, then chunk its persisted output independently."""

    def __init__(
        self,
        pool: asyncpg.Pool,
        *,
        snapshot_id: UUID,
        artifact_root: Path,
        parser_config: DoclingPdfConfig,
        chunking_config: ChunkingConfig,
        tokenizer: E5SmallV2Embedder,
        excluded_source_pages_by_document: Mapping[UUID, frozenset[int]] | None = None,
        source_content_review_identity: str | None = None,
    ) -> None:
        self._pool = pool
        self._snapshot_id = snapshot_id
        self._artifact_root = artifact_root
        self._parser = DoclingPdfExtractor(parser_config)
        self._chunking = chunking_config
        self._tokenizer = tokenizer
        self._excluded_source_pages_by_document = dict(
            excluded_source_pages_by_document or {}
        )
        for page_numbers in self._excluded_source_pages_by_document.values():
            if not page_numbers or any(
                isinstance(page, bool) or not isinstance(page, int) or page < 1
                for page in page_numbers
            ):
                raise ValueError("excluded source pages must be positive page numbers")
        if (
            source_content_review_identity is not None
            and not source_content_review_identity.startswith("sha256:")
        ):
            raise ValueError("source content review identity must be a SHA-256 ID")
        self._source_content_review_identity = source_content_review_identity
        self._prepared: PreparedPdfPipeline | None = None

    async def prepare(self) -> PreparedPdfPipeline:
        """Prepare deterministic fingerprints for parser and chunking stages."""
        if self._prepared is not None:
            return self._prepared
        parser_configuration, parser_id = await asyncio.to_thread(self._parser.prepare)
        if not parser_id.startswith("sha256:"):
            raise RuntimeError("parser returned an invalid configuration identity")
        await asyncio.to_thread(self._tokenizer.token_spans, "")
        extraction_configuration: dict[str, object] = {
            "schema_version": 1,
            "implementation_revision": EXTRACTION_IMPLEMENTATION_REVISION,
            "parser": parser_configuration,
            "parser_configuration_id": parser_id,
            "source_content_review": {
                "identity": self._source_content_review_identity,
                "excluded_source_pages_by_document": {
                    str(document_id): sorted(page_numbers)
                    for document_id, page_numbers in sorted(
                        self._excluded_source_pages_by_document.items(),
                        key=lambda item: str(item[0]),
                    )
                },
            },
        }
        chunking_configuration: dict[str, object] = {
            "schema_version": 1,
            "implementation_revision": CHUNKING_IMPLEMENTATION_REVISION,
            "chunking": self._chunking.to_dict(),
            "tokenizer": {
                "model": E5_SMALL_V2_MODEL,
                "revision": E5_SMALL_V2_REVISION,
                "preprocessing_revision": E5_SMALL_V2_PREPROCESSING,
            },
        }
        self._prepared = PreparedPdfPipeline(
            extraction_configuration=extraction_configuration,
            extraction_configuration_id=_identity(extraction_configuration),
            chunking_configuration=chunking_configuration,
            chunking_configuration_id=_identity(chunking_configuration),
        )
        return self._prepared

    async def process(self, context: StageContext) -> StageOutcome:
        prepared = await self.prepare()
        if context.stage == "extraction":
            return await self._extract(context, prepared)
        if context.stage == "chunking":
            return await self._chunk_and_persist(context, prepared)
        raise ValueError("PDF processor received an unsupported stage")

    async def _extract(
        self, context: StageContext, prepared: PreparedPdfPipeline
    ) -> StageOutcome:
        if context.configuration_id != prepared.extraction_configuration_id:
            raise DocumentStageFailure(
                "pipeline_configuration_changed",
                "effective parser configuration changed; create a new job",
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
        extraction_id = uuid5(context.document_id, prepared.extraction_configuration_id)
        try:
            stored = await EvidenceRepository(self._pool).load_for_correction(
                extraction_id
            )
        except ValueError:
            stored = None
        if stored is not None and stored.result.status == "failed":
            stored = None
        if stored is not None:
            if (
                stored.result.document_id != context.document_id
                or stored.result.configuration_id
                != prepared.extraction_configuration_id
                or stored.source_pdf_sha256 != artifact.sha256
                or stored.result.source_artifact_id != artifact.association_id
            ):
                raise DocumentStageFailure(
                    "extraction_checkpoint_mismatch",
                    "the stored extraction does not match the selected source",
                    retryable=False,
                )
            await SnapshotRepository(self._pool).set_extraction(
                self._snapshot_id, context.document_id, extraction_id
            )
            cached_references: dict[str, object] = {
                "snapshot_id": str(self._snapshot_id),
                "extraction_id": str(extraction_id),
                "source_artifact_id": str(artifact.association_id),
                "configuration_id": prepared.extraction_configuration_id,
                "section_count": len(stored.result.sections),
                "table_count": len(stored.result.tables),
            }
            return StageOutcome(
                output_fingerprint=stored.output_fingerprint,
                output_references=cached_references,
                resource_measurements={
                    "elapsed_seconds": round(time.perf_counter() - started, 3),
                    "source_bytes": artifact.byte_size,
                    "sections": len(stored.result.sections),
                    "tables": len(stored.result.tables),
                    "reused_existing": True,
                },
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
        expected_parser_id = prepared.extraction_configuration[
            "parser_configuration_id"
        ]
        if result.configuration_id != expected_parser_id:
            raise DocumentStageFailure(
                "parser_configuration_changed",
                "the effective parser options changed during the run",
                retryable=False,
            )

        excluded_pages = self._excluded_source_pages_by_document.get(
            context.document_id, frozenset()
        )
        if excluded_pages:
            result = _exclude_source_pages(result, excluded_pages)

        flagged = set(tables_requiring_vision_review(result))
        reviewed_tables = tuple(
            replace(table, requires_vision_review=table.ordinal in flagged)
            for table in result.tables
        )
        result = replace(
            result,
            extraction_id=extraction_id,
            configuration_id=prepared.extraction_configuration_id,
            configuration=dict(prepared.extraction_configuration),
            tables=reviewed_tables,
        )
        try:
            persisted = await EvidenceRepository(self._pool).persist(result, ())
            await SnapshotRepository(self._pool).set_extraction(
                self._snapshot_id, context.document_id, extraction_id
            )
        except ValueError:
            raise DocumentStageFailure(
                "evidence_persistence_invalid",
                "extracted evidence could not be persisted",
            ) from None

        output_references: dict[str, object] = {
            "snapshot_id": str(self._snapshot_id),
            "extraction_id": str(extraction_id),
            "source_artifact_id": str(artifact.association_id),
            "configuration_id": prepared.extraction_configuration_id,
            "section_count": persisted.section_count,
            "table_count": persisted.table_count,
            "vision_review_table_ordinals": sorted(flagged),
        }
        return StageOutcome(
            output_fingerprint=persisted.output_fingerprint,
            output_references=output_references,
            resource_measurements={
                "elapsed_seconds": round(time.perf_counter() - started, 3),
                "source_bytes": artifact.byte_size,
                "process_peak_rss_bytes": resource.getrusage(
                    resource.RUSAGE_SELF
                ).ru_maxrss
                * 1024,
                "sections": persisted.section_count,
                "tables": persisted.table_count,
                "reused_existing": persisted.reused_existing,
            },
        )

    async def _chunk_and_persist(
        self, context: StageContext, prepared: PreparedPdfPipeline
    ) -> StageOutcome:
        if context.configuration_id != prepared.chunking_configuration_id:
            raise DocumentStageFailure(
                "chunking_configuration_changed",
                "effective chunking configuration changed; retry the chunking stage",
                retryable=False,
            )
        started = time.perf_counter()
        artifact = await ArtifactRepository(self._pool).permitted_source_pdf(
            context.document_id, require_indexing=True
        )
        if context.input_fingerprint != f"sha256:{artifact.sha256}":
            raise DocumentStageFailure(
                "source_artifact_changed",
                "the selected source PDF checksum changed after job creation",
                retryable=False,
            )
        extraction_id = uuid5(context.document_id, prepared.extraction_configuration_id)
        try:
            stored = await EvidenceRepository(self._pool).load_for_correction(
                extraction_id
            )
        except ValueError:
            raise DocumentStageFailure(
                "extraction_checkpoint_missing",
                "the matching extraction checkpoint is unavailable",
                retryable=False,
            ) from None
        if stored.result.status == "failed":
            raise DocumentStageFailure(
                "extraction_checkpoint_failed",
                "the stored extraction did not produce usable evidence",
                retryable=False,
            )
        if (
            stored.result.configuration_id != prepared.extraction_configuration_id
            or stored.result.document_id != context.document_id
            or stored.source_pdf_sha256 != artifact.sha256
            or stored.result.source_artifact_id != artifact.association_id
        ):
            raise DocumentStageFailure(
                "extraction_checkpoint_mismatch",
                "the stored extraction does not match the selected source",
                retryable=False,
            )
        units = await self._chunk_async(stored.result)
        try:
            persisted = await EvidenceRepository(self._pool).persist_chunks(
                stored.result,
                units,
                chunking_configuration_id=prepared.chunking_configuration_id,
            )
            await SnapshotRepository(self._pool).set_chunking_configuration(
                self._snapshot_id,
                context.document_id,
                extraction_id,
                prepared.chunking_configuration_id,
            )
        except ValueError:
            raise DocumentStageFailure(
                "evidence_persistence_invalid",
                "chunked evidence could not be persisted",
            ) from None
        output_references = {
            "extraction_id": str(extraction_id),
            "chunking_configuration_id": prepared.chunking_configuration_id,
            "chunk_count": persisted.evidence_unit_count,
        }
        return StageOutcome(
            output_fingerprint=persisted.output_fingerprint,
            output_references=output_references,
            resource_measurements={
                "elapsed_seconds": round(time.perf_counter() - started, 3),
                "source_bytes": artifact.byte_size,
                "process_peak_rss_bytes": resource.getrusage(
                    resource.RUSAGE_SELF
                ).ru_maxrss
                * 1024,
                "sections": len(stored.result.sections),
                "tables": len(stored.result.tables),
                "chunks": persisted.evidence_unit_count,
                "reused_existing": persisted.reused_existing,
            },
        )

    def _chunk(self, result: ExtractionResult) -> tuple[EvidenceUnit, ...]:
        units: list[EvidenceUnit] = []
        chunking_configuration_id = (
            self._prepared.chunking_configuration_id
            if self._prepared is not None
            else self._chunking.config_id
        )
        try:
            for section in result.sections:
                units.extend(
                    chunk_section(
                        section,
                        document_id=result.document_id,
                        extraction_id=result.extraction_id,
                        config=self._chunking,
                        tokenizer=self._tokenizer,
                        chunking_configuration_id=chunking_configuration_id,
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
                        chunking_configuration_id=chunking_configuration_id,
                    )
                )
        except EvidenceChunkingError:
            raise DocumentStageFailure(
                "table_chunk_limit_exceeded",
                "table evidence exceeds the searchable token limit",
                retryable=False,
            ) from None
        return tuple(units)

    async def _chunk_async(self, result: ExtractionResult) -> tuple[EvidenceUnit, ...]:
        """Keep CPU-bound tokenization off the event loop used for job leases."""
        return await asyncio.to_thread(self._chunk, result)


def _identity(value: Mapping[str, object]) -> str:
    canonical = json.dumps(
        dict(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _exclude_source_pages(
    result: ExtractionResult, excluded_page_numbers: frozenset[int]
) -> ExtractionResult:
    """Drop evidence located on excluded one-based PDF pages and keep stable links."""
    old_to_new_sections: dict[int, int] = {}
    sections: list[ExtractedSection] = []
    for section in result.sections:
        page_index = section.source_location.page_index_zero_based
        if page_index is not None and page_index + 1 in excluded_page_numbers:
            continue
        new_ordinal = len(sections)
        old_to_new_sections[section.ordinal] = new_ordinal
        sections.append(replace(section, ordinal=new_ordinal))

    tables: list[ExtractedTable] = []
    for table in result.tables:
        page_index = table.source_location.page_index_zero_based
        if page_index is not None and page_index + 1 in excluded_page_numbers:
            continue
        new_section_ordinal = (
            old_to_new_sections.get(table.section_ordinal)
            if table.section_ordinal is not None
            else None
        )
        tables.append(
            replace(
                table,
                ordinal=len(tables),
                section_ordinal=new_section_ordinal,
            )
        )
    if not sections and not tables:
        raise DocumentStageFailure(
            "source_page_exclusion_removed_all_evidence",
            "reviewed source-page exclusions removed all extracted evidence",
            retryable=False,
        )
    return replace(result, sections=tuple(sections), tables=tuple(tables))
