"""Tests for asynchronous orchestration around PDF evidence processing."""

import asyncio
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
