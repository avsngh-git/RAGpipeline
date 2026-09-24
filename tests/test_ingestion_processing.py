"""Tests for asynchronous orchestration around PDF evidence processing."""

import asyncio
import threading
import time
from pathlib import Path
from uuid import UUID

from research_platform.ingestion.evidence import (
    ChunkingConfig,
    ExtractedSection,
    ExtractionResult,
    TokenSpan,
)
from research_platform.ingestion.pdf_extraction import DoclingPdfConfig
from research_platform.ingestion.processing import PdfEvidenceProcessor

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
