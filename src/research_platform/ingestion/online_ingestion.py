"""Permission-gated acquisition and single-paper PDF ingestion."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, cast
from urllib.parse import urlsplit
from uuid import UUID, uuid5

import asyncpg  # type: ignore[import-untyped]
import httpx

from research_platform.config import DiscoverySettings, Settings
from research_platform.discovery.online import (
    DiscoveryBudgetExceeded,
    SpendLedger,
)
from research_platform.ingestion.acquisition import (
    AcquisitionConfig,
    AcquisitionError,
    DirectSourcePdfAdapter,
    OpenAlexContentAdapter,
    OpenAlexContentAvailability,
    PermissionEvidence,
)
from research_platform.ingestion.artifact_repository import (
    ArtifactRepository,
    PermittedSourcePdf,
)
from research_platform.ingestion.artifacts import (
    ArtifactError,
    ArtifactStore,
    StoredArtifact,
    resolve_registered_pdf,
)
from research_platform.ingestion.embeddings import E5SmallV2Embedder
from research_platform.ingestion.evidence import ChunkingConfig
from research_platform.ingestion.pdf_extraction import DoclingPdfConfig
from research_platform.ingestion.processing import PdfEvidenceProcessor
from research_platform.ingestion.provenance import code_revision
from research_platform.ingestion.runner import (
    IngestionDocument,
    IngestionExecutionError,
    IngestionRunner,
    PipelineStage,
)
from research_platform.ingestion.stage_repository import IngestionJobRepository

PaperOutcomeStatus = Literal["ingested", "metadata_only", "failed"]
_LOG = logging.getLogger(__name__)
_OPENALEX_ID = re.compile(r"^W[0-9]+$")
_LICENSE_TERMS = {
    "cc-by": "https://creativecommons.org/licenses/by/4.0/",
    "public-domain": "https://creativecommons.org/publicdomain/zero/1.0/",
}
_DIRECT_SOURCE_NAMES = {
    "link.springer.com": "springer-nature",
    "arxiv.org": "arxiv",
    "eprints.gla.ac.uk": "university-of-glasgow-eprints",
}
_ARXIV_VERSIONED_PDF = re.compile(
    r"^https://arxiv\.org/pdf/(?:\d{4}\.\d{4,5}|[A-Za-z.-]+/\d{7})v\d+$"
)


@dataclass(frozen=True)
class PaperIngestOutcome:
    paper_id: str
    status: PaperOutcomeStatus
    reason: str
    document_id: UUID | None = None
    extraction_id: UUID | None = None
    chunking_configuration_id: str | None = None


@dataclass(frozen=True)
class _PermittedRoute:
    source_name: str
    source_url: str
    version: str
    license_id: str
    terms_url: str
    version_kind: Literal["published", "preprint", "other", "unknown"]
    permission_basis: str
    openalex_content: bool


class OnlineIngestionService:
    """Acquire and process one paper without changing snapshot membership."""

    def __init__(
        self,
        *,
        pool: asyncpg.Pool,
        http: httpx.AsyncClient,
        ledger: SpendLedger,
        settings: DiscoverySettings,
        artifact_root: Path,
        chunking_configuration: Mapping[str, object],
        device: str = "auto",
    ) -> None:
        self._pool = pool
        self._http = http
        self._ledger = ledger
        self._settings = settings
        self._artifact_root = artifact_root
        chunking_payload = chunking_configuration.get("chunking")
        if isinstance(chunking_payload, Mapping):
            chunking_configuration = cast(Mapping[str, object], chunking_payload)
        self._chunking = ChunkingConfig.from_dict(chunking_configuration)
        self._device = device

    async def ingest_paper(
        self, paper_id: str, *, run_id: UUID | None
    ) -> PaperIngestOutcome:
        if not isinstance(paper_id, str) or not paper_id.strip():
            raise ValueError("paper_id must be a non-empty string")
        paper_id = paper_id.strip()
        try:
            paper_row, metadata = await self._load_latest_metadata(paper_id)
            catalog_paper_id = paper_row["id"]
            if not isinstance(catalog_paper_id, str):
                raise ValueError("catalog returned an invalid paper ID")
            openalex_id = _openalex_id(paper_row["openalex_id"], metadata)
        except (KeyError, ValueError, TypeError):
            return self._outcome(
                PaperIngestOutcome(paper_id, "metadata_only", "metadata_unavailable")
            )
        try:
            route = _resolve_permitted_route(openalex_id, metadata)
        except (TypeError, ValueError):
            route = None
        if route is None:
            return self._outcome(
                PaperIngestOutcome(paper_id, "metadata_only", "no_permitted_source")
            )

        document_id = await self._upsert_document(catalog_paper_id, route)
        permission = PermissionEvidence(
            source_name=route.source_name,
            source_url=route.source_url,
            license_id=route.license_id,
            basis=route.permission_basis,
            terms_url=route.terms_url,
            checked_at=datetime.now(UTC),
            reviewer="OpenAlex exact-version license metadata",
            storage_permitted=True,
            indexing_permitted=True,
            passage_display_permitted=False,
        )
        artifact_repository = ArtifactRepository(self._pool)
        artifact = await artifact_repository.matching_permissioned_pdf(
            document_id,
            source_name=permission.source_name,
            source_url=permission.source_url,
            license_id=permission.license_id,
        )
        if artifact is not None:
            try:
                await _resolve_artifact(self._artifact_root, artifact)
            except ArtifactError:
                artifact = None

        if artifact is None:
            if route.openalex_content and not Settings().openalex_api_key:
                return self._outcome(
                    PaperIngestOutcome(
                        paper_id,
                        "metadata_only",
                        "download_unavailable",
                        document_id=document_id,
                    )
                )
            try:
                await self._ledger.reserve(
                    run_id=run_id,
                    kind="content_download",
                    cost_usd=self._settings.content_download_cost_usd,
                    run_limit=self._settings.max_downloads_per_run,
                    daily_cap_usd=self._settings.daily_spend_cap_usd,
                )
            except DiscoveryBudgetExceeded:
                return self._outcome(
                    PaperIngestOutcome(
                        paper_id,
                        "metadata_only",
                        "download_budget",
                        document_id=document_id,
                    )
                )
            try:
                stored = await self._download(route, metadata, permission)
            except (AcquisitionError, httpx.HTTPError, ValueError):
                return self._outcome(
                    PaperIngestOutcome(
                        paper_id,
                        "metadata_only",
                        "download_failed",
                        document_id=document_id,
                    )
                )
            await artifact_repository.record_download(document_id, stored, permission)
            artifact = await artifact_repository.matching_permissioned_pdf(
                document_id,
                source_name=permission.source_name,
                source_url=permission.source_url,
                license_id=permission.license_id,
            )
            if artifact is None:
                raise RuntimeError("downloaded PDF was not registered")

        await _resolve_artifact(self._artifact_root, artifact)
        try:
            result = await self._extract_and_chunk(
                paper_id=paper_id,
                document_id=document_id,
                artifact_sha256=artifact.sha256,
            )
        except (IngestionExecutionError, ImportError, RuntimeError, ValueError):
            result = PaperIngestOutcome(
                paper_id,
                "failed",
                "extraction_failed",
                document_id=document_id,
            )
        return self._outcome(result)

    async def _load_latest_metadata(
        self, paper_id: str
    ) -> tuple[Mapping[str, object], Mapping[str, object]]:
        openalex_id_filter = paper_id.removeprefix("https://openalex.org/")
        async with self._pool.acquire() as connection:
            row = await connection.fetchrow(
                """
                SELECT paper.id, paper.openalex_id,
                       COALESCE(revision.metadata, paper.metadata) AS metadata
                FROM papers AS paper
                LEFT JOIN LATERAL (
                    SELECT metadata FROM paper_metadata_revisions
                    WHERE paper_id = paper.id
                    ORDER BY revision DESC LIMIT 1
                ) AS revision ON TRUE
                WHERE paper.id = $1 OR paper.openalex_id = $2
                   OR EXISTS (
                       SELECT 1 FROM paper_identifiers identifier
                       WHERE identifier.paper_id = paper.id
                         AND identifier.namespace = 'openalex'
                         AND identifier.normalized_identifier = $2
                   )
                LIMIT 1
                """,
                paper_id,
                openalex_id_filter,
            )
        if row is None or not isinstance(row["id"], str):
            raise ValueError("paper is absent from the catalog")
        raw_metadata = row["metadata"]
        if isinstance(raw_metadata, str):
            raw_metadata = json.loads(raw_metadata)
        if not isinstance(raw_metadata, Mapping):
            raise ValueError("paper metadata is unavailable")
        return row, cast(Mapping[str, object], raw_metadata)

    async def _upsert_document(self, paper_id: str, route: _PermittedRoute) -> UUID:
        source_type = f"selected-source:{route.source_name}"
        metadata = json.dumps(
            {
                "selected_source_name": route.source_name,
                "selected_pdf_url": route.source_url,
                "terms_url": route.terms_url,
                "license_id": route.license_id,
                "online_ingestion": True,
            },
            sort_keys=True,
        )
        async with self._pool.acquire() as connection:
            document_id = await connection.fetchval(
                """
                INSERT INTO documents
                    (paper_id, source_type, source_url, version, status,
                     version_kind, metadata)
                VALUES ($1, $2, $3, $4, 'metadata_only', $5, $6::jsonb)
                ON CONFLICT (paper_id, source_type, version) DO UPDATE
                    SET source_url = EXCLUDED.source_url,
                        version_kind = EXCLUDED.version_kind,
                        metadata = documents.metadata || EXCLUDED.metadata
                RETURNING id
                """,
                paper_id,
                source_type,
                route.source_url,
                route.version,
                route.version_kind,
                metadata,
            )
        if not isinstance(document_id, UUID):
            raise RuntimeError("database did not return the online document ID")
        return document_id

    async def _download(
        self,
        route: _PermittedRoute,
        metadata: Mapping[str, object],
        permission: PermissionEvidence,
    ) -> StoredArtifact:
        acquisition_config = AcquisitionConfig(
            maximum_documents=1,
            maximum_requests=4,
            maximum_retries=1,
            permitted_licenses=tuple(_LICENSE_TERMS),
        )
        store = ArtifactStore(
            self._artifact_root,
            maximum_file_bytes=acquisition_config.maximum_file_bytes,
            maximum_store_bytes=acquisition_config.maximum_store_bytes,
        )
        if route.openalex_content:
            api_key = Settings().openalex_api_key
            if not api_key:
                raise AcquisitionError("OpenAlex content requires an API key")
            availability = OpenAlexContentAvailability.from_work_metadata(
                _openalex_id(None, metadata), metadata
            )
            adapter = OpenAlexContentAdapter(
                acquisition_config, api_key, self._http, store
            )
            return await adapter.download_pdf(availability, permission)
        return await DirectSourcePdfAdapter(
            acquisition_config, self._http, store
        ).download_pdf(permission)

    async def _extract_and_chunk(
        self, *, paper_id: str, document_id: UUID, artifact_sha256: str
    ) -> PaperIngestOutcome:
        parser_config = DoclingPdfConfig(device=self._device)  # type: ignore[arg-type]
        processor = PdfEvidenceProcessor(
            self._pool,
            snapshot_id=None,
            artifact_root=self._artifact_root,
            parser_config=parser_config,
            chunking_config=self._chunking,
            tokenizer=E5SmallV2Embedder(device=self._device),  # type: ignore[arg-type]
        )
        prepared = await processor.prepare()
        configuration: dict[str, object] = {
            "schema_version": 1,
            "operation": "online_single_paper_ingestion",
            "paper_id": paper_id,
            "document_id": str(document_id),
            "artifact_sha256": artifact_sha256,
            "parser_configuration": parser_config.to_dict(),
            "chunking_configuration": self._chunking.to_dict(),
            "extraction_configuration_id": prepared.extraction_configuration_id,
            "chunking_configuration_id": prepared.chunking_configuration_id,
        }
        configuration_id = _configuration_id(configuration)
        jobs = IngestionJobRepository(self._pool)
        job_id = await jobs.create_job(
            configuration=configuration,
            configuration_id=configuration_id,
            code_revision=code_revision(),
            execution_profile="online-single-paper",
            storage_limit_bytes=AcquisitionConfig().maximum_store_bytes,
        )
        fingerprint = f"sha256:{artifact_sha256}"
        stages = (
            PipelineStage(
                "extraction", prepared.extraction_configuration_id, processor
            ),
            PipelineStage("chunking", prepared.chunking_configuration_id, processor),
        )
        try:
            report = await IngestionRunner(jobs).run(
                job_id,
                (IngestionDocument(document_id, fingerprint),),
                stages,
            )
        except IngestionExecutionError:
            return PaperIngestOutcome(
                paper_id,
                "failed",
                "extraction_failed",
                document_id=document_id,
                extraction_id=uuid5(document_id, prepared.extraction_configuration_id),
                chunking_configuration_id=prepared.chunking_configuration_id,
            )
        if report.documents_failed:
            return PaperIngestOutcome(
                paper_id,
                "failed",
                "extraction_failed",
                document_id=document_id,
                extraction_id=uuid5(document_id, prepared.extraction_configuration_id),
                chunking_configuration_id=prepared.chunking_configuration_id,
            )
        extraction_id = uuid5(document_id, prepared.extraction_configuration_id)
        return PaperIngestOutcome(
            paper_id,
            "ingested",
            "ingested",
            document_id=document_id,
            extraction_id=extraction_id,
            chunking_configuration_id=prepared.chunking_configuration_id,
        )

    @staticmethod
    def _outcome(outcome: PaperIngestOutcome) -> PaperIngestOutcome:
        _LOG.info(
            "online paper ingestion finished",
            extra={
                "paper_id": outcome.paper_id,
                "status": outcome.status,
                "reason": outcome.reason,
            },
        )
        return outcome


def _openalex_id(raw_id: object, metadata: Mapping[str, object]) -> str:
    candidate = raw_id
    if isinstance(candidate, str):
        candidate = candidate.removeprefix("https://openalex.org/")
    if not isinstance(candidate, str) or not _OPENALEX_ID.fullmatch(candidate):
        candidate = metadata.get("id")
    if isinstance(candidate, str):
        candidate = candidate.removeprefix("https://openalex.org/")
    if not isinstance(candidate, str) or not _OPENALEX_ID.fullmatch(candidate):
        raise ValueError("catalog metadata has no valid OpenAlex ID")
    return candidate


def _resolve_permitted_route(
    openalex_id: str, metadata: Mapping[str, object]
) -> _PermittedRoute | None:
    availability = OpenAlexContentAvailability.from_work_metadata(openalex_id, metadata)
    best_location = metadata.get("best_oa_location")
    if not isinstance(best_location, Mapping):
        return None
    license_id = availability.license_id
    if license_id not in _LICENSE_TERMS:
        return None
    version = _location_version(best_location)
    if availability.pdf_available:
        source_url = f"https://content.openalex.org/works/{openalex_id}.pdf"
        return _PermittedRoute(
            "openalex-content-api",
            source_url,
            version,
            license_id,
            _LICENSE_TERMS[license_id],
            _version_kind(version, best_location),
            (
                f"OpenAlex best_oa_location records {version} under {license_id}; "
                "the OpenAlex content API cache supplies this exact work PDF."
            ),
            True,
        )

    locations = metadata.get("locations")
    if not isinstance(locations, list):
        return None
    for location in locations:
        if not isinstance(location, Mapping):
            continue
        location_license = location.get("license")
        if isinstance(location_license, str):
            location_license = location_license.removeprefix(
                "https://openalex.org/licenses/"
            )
        if location_license != license_id:
            continue
        pdf_url = location.get("pdf_url")
        if not isinstance(pdf_url, str):
            continue
        parsed = urlsplit(pdf_url)
        host = parsed.hostname or ""
        source_name = _DIRECT_SOURCE_NAMES.get(host)
        if source_name is None or not _is_supported_direct_url(pdf_url, host):
            continue
        route_version = (
            urlsplit(pdf_url).path.rsplit("/", 1)[-1]
            if host == "arxiv.org"
            else _location_version(location)
        )
        return _PermittedRoute(
            source_name,
            pdf_url,
            route_version,
            license_id,
            _LICENSE_TERMS[license_id],
            _version_kind(route_version, location),
            (
                f"OpenAlex records the exact supported PDF location as {license_id}; "
                "the download adapter enforces the fixed host and file-path allowlist."
            ),
            False,
        )
    return None


def _location_version(location: Mapping[str, object]) -> str:
    version = location.get("version")
    if isinstance(version, str) and version.strip():
        return version.strip()
    return "publishedVersion" if location.get("is_published") is True else "unknown"


def _version_kind(
    version: str, location: Mapping[str, object]
) -> Literal["published", "preprint", "other", "unknown"]:
    normalized = version.lower()
    if location.get("is_published") is True or normalized == "publishedversion":
        return "published"
    if normalized in {"submittedversion", "preprint"}:
        return "preprint"
    if normalized == "acceptedversion":
        return "other"
    return "unknown"


def _is_supported_direct_url(url: str, host: str) -> bool:
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError:
        return False
    if (
        parsed.scheme != "https"
        or parsed.hostname != host
        or port not in {None, 443}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        return False
    if host == "arxiv.org":
        return _ARXIV_VERSIONED_PDF.fullmatch(url) is not None
    if host == "link.springer.com":
        return parsed.path.startswith("/content/pdf/") and parsed.path.endswith(".pdf")
    return re.fullmatch(r"/\d+/\d+/\d+\.pdf", parsed.path) is not None


async def _resolve_artifact(artifact_root: Path, artifact: PermittedSourcePdf) -> Path:
    return await asyncio.to_thread(
        resolve_registered_pdf,
        artifact_root,
        artifact.storage_path,
        sha256=artifact.sha256,
        byte_size=artifact.byte_size,
    )


def _configuration_id(value: Mapping[str, object]) -> str:
    canonical = json.dumps(
        dict(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
