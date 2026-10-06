"""Shared fixtures for Phase 3.5 integration tests."""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

import asyncpg
import pytest

from research_platform.ingestion.acquisition import PermissionEvidence
from research_platform.ingestion.artifact_repository import ArtifactRepository
from research_platform.ingestion.artifacts import ArtifactStore
from research_platform.ingestion.evidence import (
    ChunkingConfig,
    ExtractedSection,
    ExtractionResult,
    SourceLocation,
    TokenSpan,
    chunk_section,
)
from research_platform.ingestion.evidence_repository import EvidenceRepository


@dataclass(frozen=True)
class PaperFixture:
    paper_id: str
    document_id: UUID
    extraction_id: UUID
    evidence_ids: tuple[str, ...]
    texts: dict[str, str]


class _WordTokenizer:
    def token_spans(self, text: str) -> tuple[TokenSpan, ...]:
        return tuple(
            TokenSpan(match.start(), match.end()) for match in re.finditer(r"\S+", text)
        )


async def _bytes(content: bytes) -> AsyncIterator[bytes]:
    yield content


class EvidenceSnapshotFactory:
    """Create permitted, chunked papers and snapshots over them."""

    def __init__(self, artifact_root: Path) -> None:
        self._artifact_root = artifact_root

    async def paper(
        self,
        pool: asyncpg.Pool,
        *,
        title: str,
        sections: Sequence[str],
        publication_year: int = 2024,
    ) -> PaperFixture:
        paper_id = f"W{uuid4().int % 10**12}"
        async with pool.acquire() as connection:
            await connection.execute(
                "INSERT INTO papers (id, title, publication_year) VALUES ($1, $2, $3)",
                paper_id,
                title,
                publication_year,
            )
            document_id = await connection.fetchval(
                """
                INSERT INTO documents (paper_id, source_type, version, status)
                VALUES ($1, 'integration-test', 'v1', 'acquired') RETURNING id
                """,
                paper_id,
            )
        content = f"%PDF-1.7\n{paper_id} fixture\n%%EOF\n".encode()
        artifact = await ArtifactStore(
            self._artifact_root, maximum_file_bytes=4096, maximum_store_bytes=1 << 20
        ).store_pdf(_bytes(content))
        association_id = await ArtifactRepository(pool).record_download(
            document_id,
            artifact,
            PermissionEvidence(
                source_name="integration-test",
                source_url=f"https://example.org/{paper_id}.pdf",
                license_id="cc-by",
                basis="Synthetic integration fixture permission.",
                terms_url="https://creativecommons.org/licenses/by/4.0/",
                checked_at=datetime.now(timezone.utc),
                reviewer="integration-test-reviewer",
                storage_permitted=True,
                indexing_permitted=True,
            ),
        )
        extraction_id = uuid4()
        extracted = tuple(
            ExtractedSection(
                ordinal=ordinal,
                heading_path=(f"Section {ordinal}",),
                text=text,
                source_location=SourceLocation(page_index_zero_based=ordinal),
            )
            for ordinal, text in enumerate(sections)
        )
        units = tuple(
            unit
            for section in extracted
            for unit in chunk_section(
                section,
                document_id=document_id,
                extraction_id=extraction_id,
                config=ChunkingConfig(64, 0, 4),
                tokenizer=_WordTokenizer(),
            )
        )
        await EvidenceRepository(pool).persist(
            ExtractionResult(
                document_id=document_id,
                extraction_id=extraction_id,
                extractor_name="synthetic",
                extractor_revision="fixture-1",
                configuration_id="sha256:" + "c" * 64,
                status="completed",
                source_artifact_id=association_id,
                sections=extracted,
                configuration={"fixture": True},
            ),
            units,
        )
        async with pool.acquire() as connection:
            rows = await connection.fetch(
                "SELECT id, text FROM chunks WHERE extraction_id = $1 ORDER BY id",
                extraction_id,
            )
        return PaperFixture(
            paper_id=paper_id,
            document_id=document_id,
            extraction_id=extraction_id,
            evidence_ids=tuple(row["id"] for row in rows),
            texts={row["id"]: row["text"] for row in rows},
        )

    async def snapshot(
        self,
        pool: asyncpg.Pool,
        papers: Sequence[PaperFixture],
        *,
        finalized: bool = True,
    ) -> UUID:
        async with pool.acquire() as connection:
            async with connection.transaction():
                snapshot_id = await connection.fetchval(
                    """
                    INSERT INTO snapshots
                        (name, configuration_id, configuration, code_revision)
                    VALUES ($1, $2, '{"fixture": true}'::jsonb, 'integration-test')
                    RETURNING id
                    """,
                    f"phase35-{uuid4().hex}",
                    "sha256:" + "d" * 64,
                )
                for paper in papers:
                    await connection.execute(
                        """
                        INSERT INTO snapshot_items (snapshot_id, paper_id, document_id,
                                                    extraction_id, selection_reason)
                        VALUES ($1, $2, $3, $4, 'synthetic test membership')
                        """,
                        snapshot_id,
                        paper.paper_id,
                        paper.document_id,
                        paper.extraction_id,
                    )
                    await connection.executemany(
                        """
                        INSERT INTO snapshot_item_chunks (snapshot_id, paper_id,
                            document_id, extraction_id, chunk_id)
                        VALUES ($1, $2, $3, $4, $5)
                        """,
                        [
                            (
                                snapshot_id,
                                paper.paper_id,
                                paper.document_id,
                                paper.extraction_id,
                                evidence_id,
                            )
                            for evidence_id in paper.evidence_ids
                        ],
                    )
                if finalized:
                    await connection.execute(
                        """
                        UPDATE snapshots SET status = 'finalized', finalized_at = now(),
                            finalized_by = 'integration-test'
                        WHERE id = $1
                        """,
                        snapshot_id,
                    )
        assert isinstance(snapshot_id, UUID)
        return snapshot_id


@pytest.fixture
def evidence_snapshots(tmp_path: Path) -> EvidenceSnapshotFactory:
    return EvidenceSnapshotFactory(tmp_path / "phase35-artifacts")
