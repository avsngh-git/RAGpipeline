"""Tests for permission-gated downloads and atomic artifact storage."""

import asyncio
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from research_platform.ingestion.acquisition import (
    OPENALEX_CONTENT_BASE,
    AcquisitionConfig,
    AcquisitionError,
    OpenAlexContentAdapter,
    OpenAlexContentAvailability,
    PermissionEvidence,
)
from research_platform.ingestion.artifacts import (
    ArtifactError,
    ArtifactLimitExceeded,
    ArtifactStore,
    resolve_registered_pdf,
)

PDF_BYTES = b"%PDF-1.7\nsmall fixture\n%%EOF\n"


def _permission(license_id: str = "cc-by") -> PermissionEvidence:
    return PermissionEvidence(
        source_name="openalex-content-api",
        source_url=f"{OPENALEX_CONTENT_BASE}/works/W123.pdf",
        license_id=license_id,
        basis="Human checked the source record and its license.",
        terms_url="https://creativecommons.org/licenses/by/4.0/",
        checked_at=datetime(2026, 9, 23, tzinfo=timezone.utc),
        reviewer="test-reviewer",
        storage_permitted=True,
        indexing_permitted=True,
    )


def _availability(license_id: str | None = "cc-by") -> OpenAlexContentAvailability:
    return OpenAlexContentAvailability("W123", True, license_id)


def _async_chunks(payload: bytes):
    async def chunks():
        yield payload[:5]
        yield payload[5:]

    return chunks()


def test_registered_pdf_resolver_checks_checksum_and_rejects_symlinks(
    tmp_path: Path,
) -> None:
    store = ArtifactStore(
        tmp_path / "store", maximum_file_bytes=1024, maximum_store_bytes=4096
    )
    artifact = asyncio.run(store.store_pdf(_async_chunks(PDF_BYTES)))

    resolved = resolve_registered_pdf(
        store.root,
        artifact.storage_path,
        sha256=artifact.sha256,
        byte_size=artifact.byte_size,
    )
    assert resolved.read_bytes() == PDF_BYTES
    with pytest.raises(ArtifactError, match="checksum or byte size"):
        resolve_registered_pdf(
            store.root,
            artifact.storage_path,
            sha256=artifact.sha256,
            byte_size=artifact.byte_size + 1,
        )

    outside = tmp_path / "outside.pdf"
    outside.write_bytes(PDF_BYTES)
    content_path = store.root / artifact.storage_path
    content_path.unlink()
    content_path.symlink_to(outside)
    with pytest.raises(ArtifactError, match="symlinks"):
        resolve_registered_pdf(
            store.root,
            artifact.storage_path,
            sha256=artifact.sha256,
            byte_size=artifact.byte_size,
        )


def test_acquisition_config_round_trips_and_has_stable_identity() -> None:
    config = AcquisitionConfig()

    assert AcquisitionConfig.from_dict(config.to_dict()) == config
    assert AcquisitionConfig.from_dict(config.to_dict()).config_id == config.config_id
    assert AcquisitionConfig(maximum_documents=11).config_id != config.config_id


def test_acquisition_config_rejects_invalid_budgets() -> None:
    with pytest.raises(ValueError, match="positive"):
        AcquisitionConfig(maximum_requests=0)
    with pytest.raises(ValueError, match="at least 1"):
        AcquisitionConfig(minimum_request_interval_seconds=0.5)
    with pytest.raises(ValueError, match="cannot exceed"):
        AcquisitionConfig(maximum_file_bytes=10, maximum_store_bytes=9)


def test_content_availability_requires_explicit_license_metadata() -> None:
    availability = OpenAlexContentAvailability.from_work_metadata(
        "https://openalex.org/W123",
        {
            "has_content": {"pdf": True},
            "best_oa_location": {"license": "https://openalex.org/licenses/cc-by"},
        },
    )

    assert availability == _availability()
    with pytest.raises(ValueError, match="does not state"):
        OpenAlexContentAvailability.from_work_metadata("W123", {})


def test_permission_evidence_requires_storage_before_indexing() -> None:
    with pytest.raises(ValueError, match="requires storage"):
        PermissionEvidence(
            source_name="openalex-content-api",
            source_url=f"{OPENALEX_CONTENT_BASE}/works/W123.pdf",
            license_id="cc-by",
            basis="reviewed",
            terms_url="https://creativecommons.org/licenses/by/4.0/",
            checked_at=datetime(2026, 9, 23),
            reviewer="test-reviewer",
            storage_permitted=False,
            indexing_permitted=True,
        )


def test_artifact_store_publishes_pdf_by_checksum_and_deduplicates(
    tmp_path: Path,
) -> None:
    store = ArtifactStore(
        tmp_path / "artifacts", maximum_file_bytes=100, maximum_store_bytes=200
    )

    first = asyncio.run(store.store_pdf(_async_chunks(PDF_BYTES)))
    second = asyncio.run(store.store_pdf(_async_chunks(PDF_BYTES)))

    assert first == second
    assert first.byte_size == len(PDF_BYTES)
    assert first.storage_path == f"sha256/{first.sha256[:2]}/{first.sha256}.pdf"
    assert (tmp_path / "artifacts" / first.storage_path).read_bytes() == PDF_BYTES
    assert not list((tmp_path / "artifacts").glob(".partial-*"))


def test_artifact_store_rejects_invalid_or_oversized_content(tmp_path: Path) -> None:
    store = ArtifactStore(
        tmp_path / "artifacts", maximum_file_bytes=32, maximum_store_bytes=64
    )

    with pytest.raises(ArtifactError, match="PDF header"):
        asyncio.run(store.store_pdf(_async_chunks(b"not a PDF")))
    with pytest.raises(ArtifactLimitExceeded, match="per-file"):
        asyncio.run(store.store_pdf(_async_chunks(b"%PDF-1.7\n" + b"x" * 40)))
    assert not list((tmp_path / "artifacts").glob(".partial-*"))


def test_artifact_store_enforces_total_store_limit(tmp_path: Path) -> None:
    store = ArtifactStore(
        tmp_path / "artifacts", maximum_file_bytes=30, maximum_store_bytes=30
    )
    asyncio.run(store.store_pdf(_async_chunks(PDF_BYTES)))

    with pytest.raises(ArtifactLimitExceeded, match="store size limit"):
        asyncio.run(store.store_pdf(_async_chunks(b"%PDF-1.7\nsecond file")))


def test_openalex_adapter_downloads_only_explicitly_permitted_pdf(
    tmp_path: Path,
) -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            headers={
                "content-type": "application/pdf",
                "content-length": str(len(PDF_BYTES)),
            },
            content=PDF_BYTES,
        )

    async def no_sleep(_delay: float) -> None:
        return None

    async def exercise() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
            adapter = OpenAlexContentAdapter(
                AcquisitionConfig(),
                "test-secret",
                http,
                ArtifactStore(
                    tmp_path / "artifacts",
                    maximum_file_bytes=1024,
                    maximum_store_bytes=2048,
                ),
                sleep=no_sleep,
                clock=lambda: 0.0,
            )
            result = await adapter.download_pdf(_availability(), _permission())
            assert result.byte_size == len(PDF_BYTES)
            assert adapter.requests_used == 1

    asyncio.run(exercise())

    assert len(requests) == 1
    assert requests[0].url.host == "content.openalex.org"
    assert requests[0].url.path == "/works/W123.pdf"


def test_openalex_adapter_rejects_missing_or_unpermitted_rights_before_request(
    tmp_path: Path,
) -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, content=PDF_BYTES)

    async def no_sleep(_delay: float) -> None:
        return None

    async def exercise() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
            adapter = OpenAlexContentAdapter(
                AcquisitionConfig(),
                "test-secret",
                http,
                ArtifactStore(
                    tmp_path / "artifacts",
                    maximum_file_bytes=1024,
                    maximum_store_bytes=2048,
                ),
                sleep=no_sleep,
                clock=lambda: 0.0,
            )
            with pytest.raises(AcquisitionError, match="license"):
                await adapter.download_pdf(_availability(None), _permission())
            with pytest.raises(AcquisitionError, match="permitted-license"):
                await adapter.download_pdf(
                    _availability("cc-by-nc-nd"), _permission("cc-by-nc-nd")
                )
            with pytest.raises(AcquisitionError, match="permissions"):
                await adapter.download_pdf(
                    _availability(),
                    PermissionEvidence(
                        source_name="openalex-content-api",
                        source_url=f"{OPENALEX_CONTENT_BASE}/works/W123.pdf",
                        license_id="cc-by",
                        basis="reviewed",
                        terms_url="https://creativecommons.org/licenses/by/4.0/",
                        checked_at=datetime(2026, 9, 23, tzinfo=timezone.utc),
                        reviewer="test-reviewer",
                        storage_permitted=False,
                        indexing_permitted=False,
                    ),
                )

    asyncio.run(exercise())

    assert requests == []


def test_openalex_adapter_never_follows_redirects_or_accepts_non_pdf(
    tmp_path: Path,
) -> None:
    async def no_sleep(_delay: float) -> None:
        return None

    async def exercise() -> None:
        for response in (
            httpx.Response(302, headers={"location": "http://127.0.0.1/private"}),
            httpx.Response(200, headers={"content-type": "text/html"}, content=b"html"),
        ):
            async with httpx.AsyncClient(
                transport=httpx.MockTransport(lambda _request, result=response: result)
            ) as http:
                adapter = OpenAlexContentAdapter(
                    AcquisitionConfig(),
                    "test-secret",
                    http,
                    ArtifactStore(
                        tmp_path / "artifacts",
                        maximum_file_bytes=1024,
                        maximum_store_bytes=2048,
                    ),
                    sleep=no_sleep,
                    clock=lambda: 0.0,
                )
                with pytest.raises(AcquisitionError):
                    await adapter.download_pdf(_availability(), _permission())

    asyncio.run(exercise())


def test_interrupted_stream_removes_its_partial_file(tmp_path: Path) -> None:
    store = ArtifactStore(
        tmp_path / "artifacts", maximum_file_bytes=1024, maximum_store_bytes=2048
    )

    async def interrupted_chunks():
        yield b"%PDF-1.7\npartial"
        raise OSError("simulated stream interruption")

    with pytest.raises(OSError, match="stream interruption"):
        asyncio.run(store.store_pdf(interrupted_chunks()))

    assert not list((tmp_path / "artifacts").glob(".partial-*"))


def test_stale_file_cleanup_rechecks_age_and_preserves_recent_files(
    tmp_path: Path,
) -> None:
    root = tmp_path / "artifacts"
    store = ArtifactStore(root, maximum_file_bytes=1024, maximum_store_bytes=4096)
    old_pdf = asyncio.run(store.store_pdf(_async_chunks(PDF_BYTES)))
    recent_pdf = asyncio.run(
        store.store_pdf(_async_chunks(b"%PDF-1.7\nrecent orphan\n%%EOF\n"))
    )
    old_pdf_path = root / old_pdf.storage_path
    old_partial_path = root / ".partial-old"
    recent_partial_path = root / ".partial-recent"
    old_partial_path.write_bytes(b"partial")
    recent_partial_path.write_bytes(b"active")
    older_timestamp = datetime.now(timezone.utc) - timedelta(days=3)
    os.utime(old_pdf_path, (older_timestamp.timestamp(),) * 2)
    os.utime(old_partial_path, (older_timestamp.timestamp(),) * 2)
    cutoff = datetime.now(timezone.utc) - timedelta(days=1)

    unregistered = store.stale_unregistered_files(
        {recent_pdf.storage_path}, created_before=cutoff
    )
    partials = store.stale_partial_files(created_before=cutoff)

    assert [item.storage_path for item in unregistered] == [old_pdf.storage_path]
    assert [item.storage_path for item in partials] == [".partial-old"]
    store.remove_unregistered_pdf(unregistered[0], created_before=cutoff)
    store.remove_stale_partial(partials[0], created_before=cutoff)
    assert not old_pdf_path.exists()
    assert not old_partial_path.exists()
    assert (root / recent_pdf.storage_path).exists()
    assert recent_partial_path.exists()


def test_artifact_removal_rejects_checksum_path_mismatch(tmp_path: Path) -> None:
    store = ArtifactStore(
        tmp_path / "artifacts", maximum_file_bytes=1024, maximum_store_bytes=2048
    )
    with pytest.raises(ArtifactError, match="does not match"):
        store.remove_content_addressed_pdf(
            sha256="a" * 64,
            storage_path=f"sha256/bb/{'b' * 64}.pdf",
        )


def test_artifact_store_reports_capacity_and_unregistered_files(
    tmp_path: Path,
) -> None:
    root = tmp_path / "artifacts"
    store = ArtifactStore(root, maximum_file_bytes=1024, maximum_store_bytes=2048)
    stored = asyncio.run(store.store_pdf(_async_chunks(PDF_BYTES)))
    orphan = root / "sha256" / "ff" / ("f" * 64 + ".pdf")
    orphan.parent.mkdir(parents=True)
    orphan.write_bytes(PDF_BYTES)
    partial = root / ".partial-interrupted"
    partial.write_bytes(b"partial")

    report = store.inspect()

    assert report.stored_bytes == len(PDF_BYTES) * 2
    assert report.remaining_store_bytes == 2048 - len(PDF_BYTES) * 2
    assert report.filesystem_free_bytes > 0
    assert report.partial_file_count == 1
    assert report.partial_bytes == len(b"partial")
    assert store.unregistered_files({stored.storage_path}) == (
        f"sha256/ff/{'f' * 64}.pdf",
    )


def test_artifact_store_serializes_writers_at_the_global_byte_limit(
    tmp_path: Path,
) -> None:
    store = ArtifactStore(
        tmp_path / "artifacts",
        maximum_file_bytes=len(PDF_BYTES),
        maximum_store_bytes=len(PDF_BYTES),
    )

    async def slow_chunks():
        for start in range(0, len(PDF_BYTES), 5):
            await asyncio.sleep(0)
            yield PDF_BYTES[start : start + 5]

    async def exercise() -> None:
        results = await asyncio.gather(
            store.store_pdf(slow_chunks()),
            store.store_pdf(slow_chunks()),
            return_exceptions=True,
        )
        assert sum(not isinstance(result, BaseException) for result in results) == 1
        assert sum(isinstance(result, ArtifactLimitExceeded) for result in results) == 1

    asyncio.run(exercise())
