"""Tests for asynchronous orchestration around PDF evidence processing."""

import asyncio
import hashlib
import json
import threading
import time
from pathlib import Path
from uuid import UUID

from research_platform.ingestion.evidence import (
    ChunkingConfig,
    ExtractedSection,
    ExtractedTable,
    ExtractionResult,
    TableCell,
    TokenSpan,
)
from research_platform.ingestion.pdf_extraction import DoclingPdfConfig
from research_platform.ingestion.processing import (
    PdfEvidenceProcessor,
    PreparedPdfPipeline,
)
from research_platform.ingestion.runner import DocumentStageFailure

DOCUMENT_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
EXTRACTION_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
SNAPSHOT_ID = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")


class BlockingTokenizer:
    def __init__(self) -> None:
        self.started = threading.Event()

    def token_spans(self, text: str) -> tuple[TokenSpan, ...]:
        self.started.set()
        time.sleep(0.05)
        return (TokenSpan(0, len(text)),)


def test_evidence_chunking_does_not_block_async_job_heartbeats() -> None:
    async def exercise_chunking() -> None:
        tokenizer = BlockingTokenizer()
        processor = PdfEvidenceProcessor(
            None,  # type: ignore[arg-type]
            snapshot_id=SNAPSHOT_ID,
            artifact_root=Path("."),
            parser_config=DoclingPdfConfig(device="cpu"),
            chunking_config=ChunkingConfig(8, 0, 2),
            tokenizer=tokenizer,  # type: ignore[arg-type]
        )
        result = ExtractionResult(
            document_id=DOCUMENT_ID,
            extraction_id=EXTRACTION_ID,
            extractor_name="docling",
            extractor_revision="test",
            configuration_id="sha256:" + "0" * 64,
            status="completed",
            sections=(ExtractedSection(ordinal=0, heading_path=(), text="value"),),
        )

        task = asyncio.create_task(processor._chunk_async(result))
        await asyncio.sleep(0.01)
        assert tokenizer.started.is_set()
        assert not task.done()
        await task

    asyncio.run(exercise_chunking())


class CharacterTokenizer:
    def token_spans(self, text: str) -> tuple[TokenSpan, ...]:
        return tuple(TokenSpan(index, index + 1) for index in range(len(text)))


class _ExtractionPlanConnection:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows

    async def fetch(self, query: str, snapshot_id: UUID) -> list[dict[str, object]]:
        del query, snapshot_id
        return self._rows


class _ExtractionPlanAcquire:
    def __init__(self, connection: _ExtractionPlanConnection) -> None:
        self._connection = connection

    async def __aenter__(self) -> _ExtractionPlanConnection:
        return self._connection

    async def __aexit__(self, *_args: object) -> None:
        return None


class _ExtractionPlanPool:
    def __init__(self, connection: _ExtractionPlanConnection) -> None:
        self._connection = connection

    def acquire(self) -> _ExtractionPlanAcquire:
        return _ExtractionPlanAcquire(self._connection)


def _selected_extraction_row(
    parser_config: DoclingPdfConfig,
) -> dict[str, object]:
    configuration = {
        "parser": {
            **parser_config.to_dict(),
            "dependencies": {},
            "pipeline_options": {},
            "model_asset_sha256s": {},
        },
        "source_content_review": {
            "identity": None,
            "excluded_source_pages_by_document": {},
        },
    }
    canonical = json.dumps(
        configuration, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    configuration_id = "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return {
        "document_id": DOCUMENT_ID,
        "extraction_id": EXTRACTION_ID,
        "configuration_id": configuration_id,
        "configuration": json.dumps(configuration),
        "status": "completed",
        "output_sha256": "a" * 64,
        "source_artifact_id": UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd"),
        "source_pdf_sha256": "b" * 64,
    }


def test_snapshot_extraction_reuse_skips_parser_and_pins_existing_member() -> None:
    parser_config = DoclingPdfConfig(device="cpu")
    connection = _ExtractionPlanConnection([_selected_extraction_row(parser_config)])
    processor = PdfEvidenceProcessor(
        _ExtractionPlanPool(connection),  # type: ignore[arg-type]
        snapshot_id=SNAPSHOT_ID,
        artifact_root=Path("."),
        parser_config=parser_config,
        chunking_config=ChunkingConfig(8, 2, 2, strategy="fixed-window"),
        tokenizer=CharacterTokenizer(),  # type: ignore[arg-type]
        reuse_snapshot_extractions=True,
    )

    class UnavailableParser:
        config = parser_config

        def prepare(self) -> tuple[dict[str, object], str]:
            raise AssertionError(
                "rechunking must not load or initialize the PDF parser"
            )

    processor._parser = UnavailableParser()  # type: ignore[assignment]
    prepared = asyncio.run(processor.prepare())

    assert prepared.extraction_configuration["strategy"] == (
        "reuse-snapshot-selected-extractions-v1"
    )
    assert processor._selected_extractions[DOCUMENT_ID].extraction_id == EXTRACTION_ID
    assert processor._selected_extractions[DOCUMENT_ID].configuration_id.startswith(
        "sha256:"
    )


def test_snapshot_extraction_reuse_rejects_changed_source_review() -> None:
    parser_config = DoclingPdfConfig(device="cpu")
    connection = _ExtractionPlanConnection([_selected_extraction_row(parser_config)])
    processor = PdfEvidenceProcessor(
        _ExtractionPlanPool(connection),  # type: ignore[arg-type]
        snapshot_id=SNAPSHOT_ID,
        artifact_root=Path("."),
        parser_config=parser_config,
        chunking_config=ChunkingConfig(8, 2, 2, strategy="fixed-window"),
        tokenizer=CharacterTokenizer(),  # type: ignore[arg-type]
        source_content_review_identity="sha256:" + "c" * 64,
        reuse_snapshot_extractions=True,
    )

    try:
        asyncio.run(processor.prepare())
    except ValueError as error:
        assert "source-content review" in str(error)
    else:
        raise AssertionError("a source-review mismatch must reject checkpoint reuse")


def test_stage_fingerprints_separate_parser_from_chunking_settings() -> None:
    class PreparedParser:
        def prepare(self) -> tuple[dict[str, object], str]:
            return {"parser": "stable-fixture"}, "sha256:" + "1" * 64

    async def prepare_pair() -> tuple[PreparedPdfPipeline, PreparedPdfPipeline]:
        processors = [
            PdfEvidenceProcessor(
                None,  # type: ignore[arg-type]
                snapshot_id=SNAPSHOT_ID,
                artifact_root=Path("."),
                parser_config=DoclingPdfConfig(device="cpu"),
                chunking_config=config,
                tokenizer=CharacterTokenizer(),  # type: ignore[arg-type]
            )
            for config in (ChunkingConfig(8, 0, 2), ChunkingConfig(6, 1, 1))
        ]
        for processor in processors:
            processor._parser = PreparedParser()  # type: ignore[assignment]
        return await processors[0].prepare(), await processors[1].prepare()

    first, second = asyncio.run(prepare_pair())
    assert first.extraction_configuration_id == second.extraction_configuration_id
    assert first.chunking_configuration_id != second.chunking_configuration_id
    assert "processor_code_revision" not in first.extraction_configuration


def test_fixed_window_has_distinct_chunking_but_reuses_extraction_identity() -> None:
    class PreparedParser:
        def prepare(self) -> tuple[dict[str, object], str]:
            return {"parser": "stable-fixture"}, "sha256:" + "1" * 64

    async def prepare(config: ChunkingConfig) -> PreparedPdfPipeline:
        processor = PdfEvidenceProcessor(
            None,  # type: ignore[arg-type]
            snapshot_id=SNAPSHOT_ID,
            artifact_root=Path("."),
            parser_config=DoclingPdfConfig(device="cpu"),
            chunking_config=config,
            tokenizer=CharacterTokenizer(),  # type: ignore[arg-type]
        )
        processor._parser = PreparedParser()  # type: ignore[assignment]
        return await processor.prepare()

    section_aware = asyncio.run(prepare(ChunkingConfig(8, 2, 2)))
    fixed_window = asyncio.run(
        prepare(ChunkingConfig(8, 2, 2, strategy="fixed-window"))
    )

    assert (
        section_aware.extraction_configuration_id
        == fixed_window.extraction_configuration_id
    )
    assert (
        section_aware.chunking_configuration_id
        != fixed_window.chunking_configuration_id
    )
    assert fixed_window.chunking_configuration["implementation_revision"] == (
        "phase2-fixed-window-chunking-v1"
    )


def test_unfittable_table_context_becomes_document_stage_failure() -> None:
    table = ExtractedTable(
        ordinal=0,
        caption="long context " * 40,
        units=None,
        footnotes=(),
        header_rows=1,
        cells=(TableCell(0, 0, "Header"), TableCell(1, 0, "value")),
        section_ordinal=0,
    )
    result = ExtractionResult(
        document_id=DOCUMENT_ID,
        extraction_id=EXTRACTION_ID,
        extractor_name="docling",
        extractor_revision="test",
        configuration_id="sha256:" + "0" * 64,
        status="completed",
        tables=(table,),
    )
    processor = PdfEvidenceProcessor(
        None,  # type: ignore[arg-type]
        snapshot_id=SNAPSHOT_ID,
        artifact_root=Path("."),
        parser_config=DoclingPdfConfig(device="cpu"),
        chunking_config=ChunkingConfig(8, 0, 2),
        tokenizer=CharacterTokenizer(),  # type: ignore[arg-type]
    )

    try:
        processor._chunk(result)
    except DocumentStageFailure as error:
        assert error.category == "table_chunk_limit_exceeded"
        assert error.retryable is False
    else:
        raise AssertionError("an unbounded table caption must fail this document")
