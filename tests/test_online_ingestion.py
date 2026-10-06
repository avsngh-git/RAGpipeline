from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from research_platform.config import DiscoverySettings
from research_platform.discovery.online import DiscoveryBudgetExceeded
from research_platform.ingestion.artifact_repository import PermittedSourcePdf
from research_platform.ingestion.artifacts import StoredArtifact
from research_platform.ingestion.online_ingestion import (
    OnlineIngestionService,
    PaperIngestOutcome,
)

PAPER_ID = "W1234567890"
DOCUMENT_ID = UUID("0a8ef9c7-08c6-4dc7-a1b7-4f2ef8f4517a")
PDF_SHA256 = "a" * 64


def _metadata(*, pdf_available: bool = True) -> dict[str, object]:
    return {
        "id": f"https://openalex.org/{PAPER_ID}",
        "has_content": {"pdf": pdf_available},
        "best_oa_location": {
            "license": "cc-by",
            "version": "publishedVersion",
            "is_published": True,
        },
        "locations": [],
    }


class _Connection:
    async def fetchval(self, *_args: object) -> UUID:
        return DOCUMENT_ID


class _Pool:
    @asynccontextmanager
    async def acquire(self):
        yield _Connection()


class _Ledger:
    def __init__(self, *, refusal: bool = False) -> None:
        self.reservations = 0
        self.refusal = refusal

    async def reserve(self, **_kwargs: object) -> None:
        self.reservations += 1
        if self.refusal:
            raise DiscoveryBudgetExceeded("daily_spend_cap")


class _ApiSettings:
    openalex_api_key = "test-key"


class _ArtifactRepository:
    current: PermittedSourcePdf | None = None
    recorded = 0

    def __init__(self, _pool: object) -> None:
        pass

    async def matching_permissioned_pdf(self, *_args: object, **_kwargs: object):
        return self.current

    async def record_download(self, *_args: object, **_kwargs: object) -> None:
        type(self).recorded += 1
        self.current = PermittedSourcePdf(
            association_id=uuid4(),
            document_id=DOCUMENT_ID,
            sha256=PDF_SHA256,
            storage_path=f"sha256/{PDF_SHA256[:2]}/{PDF_SHA256}.pdf",
            byte_size=1024,
        )


def _service(ledger: _Ledger) -> OnlineIngestionService:
    return OnlineIngestionService(
        pool=_Pool(),  # type: ignore[arg-type]
        http=None,  # type: ignore[arg-type]
        ledger=ledger,  # type: ignore[arg-type]
        settings=DiscoverySettings(),
        artifact_root=Path("/tmp/online-ingestion-test"),
        chunking_configuration={
            "schema_version": 1,
            "maximum_text_tokens": 512,
            "overlapping_text_tokens": 64,
            "maximum_table_rows_per_group": 10,
        },
        device="cpu",
    )


async def _load_metadata(
    _paper_id: str,
) -> tuple[dict[str, object], dict[str, object]]:
    return {"id": PAPER_ID, "openalex_id": PAPER_ID}, _metadata()


async def _load_metadata_without_pdf(
    _paper_id: str,
) -> tuple[dict[str, object], dict[str, object]]:
    return {"id": PAPER_ID, "openalex_id": PAPER_ID}, _metadata(pdf_available=False)


async def _resolve_artifact(*_args: object, **_kwargs: object) -> Path:
    return Path("/tmp/online-ingestion-test/source.pdf")


@pytest.mark.anyio
async def test_no_permitted_route_is_metadata_only_without_download(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger = _Ledger()
    service = _service(ledger)
    monkeypatch.setattr(service, "_load_latest_metadata", _load_metadata_without_pdf)

    outcome = await service.ingest_paper(PAPER_ID, run_id=None)

    assert outcome == PaperIngestOutcome(
        PAPER_ID, "metadata_only", "no_permitted_source"
    )
    assert ledger.reservations == 0


@pytest.mark.anyio
async def test_existing_permissioned_pdf_is_reused_without_spend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger = _Ledger(refusal=True)
    service = _service(ledger)
    _ArtifactRepository.current = PermittedSourcePdf(
        association_id=uuid4(),
        document_id=DOCUMENT_ID,
        sha256=PDF_SHA256,
        storage_path=f"sha256/{PDF_SHA256[:2]}/{PDF_SHA256}.pdf",
        byte_size=1024,
    )
    monkeypatch.setattr(service, "_load_latest_metadata", _load_metadata)
    monkeypatch.setattr(
        "research_platform.ingestion.online_ingestion.ArtifactRepository",
        _ArtifactRepository,
    )
    monkeypatch.setattr(
        "research_platform.ingestion.online_ingestion._resolve_artifact",
        _resolve_artifact,
    )

    async def extract(*, paper_id: str, document_id: UUID, artifact_sha256: str):
        return PaperIngestOutcome(
            paper_id,
            "ingested",
            "ingested",
            document_id=document_id,
            extraction_id=uuid4(),
            chunking_configuration_id="sha256:" + "b" * 64,
        )

    monkeypatch.setattr(service, "_extract_and_chunk", extract)
    outcome = await service.ingest_paper(PAPER_ID, run_id=None)

    assert outcome.status == "ingested"
    assert ledger.reservations == 0


@pytest.mark.anyio
async def test_download_budget_refusal_is_metadata_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger = _Ledger(refusal=True)
    service = _service(ledger)
    _ArtifactRepository.current = None
    monkeypatch.setattr(service, "_load_latest_metadata", _load_metadata)
    monkeypatch.setattr(
        "research_platform.ingestion.online_ingestion.ArtifactRepository",
        _ArtifactRepository,
    )
    monkeypatch.setattr(
        "research_platform.ingestion.online_ingestion.Settings",
        lambda: _ApiSettings(),
    )
    monkeypatch.setattr(
        service,
        "_download",
        lambda *_args: pytest.fail("download must not happen after budget refusal"),
    )

    outcome = await service.ingest_paper(PAPER_ID, run_id=None)

    assert outcome.status == "metadata_only"
    assert outcome.reason == "download_budget"
    assert ledger.reservations == 1


@pytest.mark.anyio
async def test_successful_ingest_returns_document_and_extraction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger = _Ledger()
    service = _service(ledger)
    _ArtifactRepository.current = None
    monkeypatch.setattr(service, "_load_latest_metadata", _load_metadata)
    monkeypatch.setattr(
        "research_platform.ingestion.online_ingestion.ArtifactRepository",
        _ArtifactRepository,
    )
    monkeypatch.setattr(
        "research_platform.ingestion.online_ingestion.Settings",
        lambda: _ApiSettings(),
    )
    monkeypatch.setattr(
        "research_platform.ingestion.online_ingestion._resolve_artifact",
        _resolve_artifact,
    )

    async def download(*_args: object) -> StoredArtifact:
        return StoredArtifact(
            sha256=PDF_SHA256,
            storage_path=f"sha256/{PDF_SHA256[:2]}/{PDF_SHA256}.pdf",
            byte_size=1024,
        )

    monkeypatch.setattr(service, "_download", download)

    async def extract(*, paper_id: str, document_id: UUID, artifact_sha256: str):
        return PaperIngestOutcome(
            paper_id,
            "ingested",
            "ingested",
            document_id=document_id,
            extraction_id=uuid4(),
            chunking_configuration_id="sha256:" + "b" * 64,
        )

    monkeypatch.setattr(service, "_extract_and_chunk", extract)
    outcome = await service.ingest_paper(PAPER_ID, run_id=None)

    assert outcome.status == "ingested"
    assert outcome.document_id == DOCUMENT_ID
    assert outcome.extraction_id is not None
    assert outcome.chunking_configuration_id is not None
    assert ledger.reservations == 1
    assert _ArtifactRepository.recorded == 1


@pytest.mark.anyio
async def test_extraction_failure_returns_failed_and_keeps_outputs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger = _Ledger()
    service = _service(ledger)
    _ArtifactRepository.current = PermittedSourcePdf(
        association_id=uuid4(),
        document_id=DOCUMENT_ID,
        sha256=PDF_SHA256,
        storage_path=f"sha256/{PDF_SHA256[:2]}/{PDF_SHA256}.pdf",
        byte_size=1024,
    )
    monkeypatch.setattr(service, "_load_latest_metadata", _load_metadata)
    monkeypatch.setattr(
        "research_platform.ingestion.online_ingestion.ArtifactRepository",
        _ArtifactRepository,
    )
    monkeypatch.setattr(
        "research_platform.ingestion.online_ingestion._resolve_artifact",
        _resolve_artifact,
    )

    async def extract(*, paper_id: str, document_id: UUID, artifact_sha256: str):
        return PaperIngestOutcome(
            paper_id,
            "failed",
            "extraction_failed",
            document_id=document_id,
            extraction_id=uuid4(),
        )

    monkeypatch.setattr(service, "_extract_and_chunk", extract)
    outcome = await service.ingest_paper(PAPER_ID, run_id=None)

    assert outcome.status == "failed"
    assert outcome.reason == "extraction_failed"
    assert outcome.document_id == DOCUMENT_ID
    assert outcome.extraction_id is not None
    assert ledger.reservations == 0
