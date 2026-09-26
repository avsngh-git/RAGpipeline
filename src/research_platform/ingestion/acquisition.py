"""Permission-gated, bounded retrieval of OpenAlex-hosted PDF content."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from math import isfinite
from typing import cast
from urllib.parse import unquote, urlsplit

import httpx

from research_platform.ingestion.artifacts import ArtifactStore, StoredArtifact

OPENALEX_CONTENT_BASE = "https://content.openalex.org"
DIRECT_SOURCE_HOSTS = (
    "link.springer.com",
    "arxiv.org",
    "eprints.gla.ac.uk",
)
_DIRECT_SOURCE_NAMES = {
    "link.springer.com": "springer-nature",
    "arxiv.org": "arxiv",
    "eprints.gla.ac.uk": "university-of-glasgow-eprints",
}
_ARXIV_PDF_PATH = re.compile(r"^/pdf/(?:\d{4}\.\d{4,5}|[A-Za-z.-]+/\d{7})v\d+$")
_OPENALEX_ID_PATTERN = re.compile(r"^W[0-9]+$")
Sleep = Callable[[float], Awaitable[None]]
Clock = Callable[[], float]


@dataclass(frozen=True)
class AcquisitionConfig:
    """Serializable request, license and local storage ceilings."""

    maximum_documents: int = 10
    maximum_requests: int = 20
    maximum_retries: int = 2
    timeout_seconds: float = 30.0
    minimum_request_interval_seconds: float = 1.0
    maximum_file_bytes: int = 25 * 1024 * 1024
    maximum_store_bytes: int = 2 * 1024 * 1024 * 1024
    permitted_licenses: tuple[str, ...] = ("cc-by", "public-domain")

    def __post_init__(self) -> None:
        for field_name, value in (
            ("maximum_documents", self.maximum_documents),
            ("maximum_requests", self.maximum_requests),
            ("maximum_retries", self.maximum_retries),
            ("maximum_file_bytes", self.maximum_file_bytes),
            ("maximum_store_bytes", self.maximum_store_bytes),
        ):
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{field_name} must be an integer")
        if self.maximum_documents <= 0 or self.maximum_requests <= 0:
            raise ValueError("document and request ceilings must be positive")
        if self.maximum_retries < 0:
            raise ValueError("maximum_retries must not be negative")
        if self.maximum_file_bytes <= 0 or self.maximum_store_bytes <= 0:
            raise ValueError("artifact byte limits must be positive")
        if self.maximum_file_bytes > self.maximum_store_bytes:
            raise ValueError("maximum_file_bytes cannot exceed maximum_store_bytes")
        for time_field_name, time_value in (
            ("timeout_seconds", self.timeout_seconds),
            ("minimum_request_interval_seconds", self.minimum_request_interval_seconds),
        ):
            if (
                isinstance(time_value, bool)
                or not isinstance(time_value, (int, float))
                or not isfinite(time_value)
            ):
                raise ValueError(f"{time_field_name} must be a finite number")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if self.minimum_request_interval_seconds < 1:
            raise ValueError("minimum_request_interval_seconds must be at least 1")
        if (
            not isinstance(self.permitted_licenses, tuple)
            or not self.permitted_licenses
        ):
            raise ValueError("permitted_licenses must be a non-empty tuple")
        if any(
            not isinstance(value, str) or not value.strip()
            for value in self.permitted_licenses
        ):
            raise ValueError("permitted_licenses must contain non-empty strings")
        if len(set(self.permitted_licenses)) != len(self.permitted_licenses):
            raise ValueError("permitted_licenses must not contain duplicates")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "maximum_documents": self.maximum_documents,
            "maximum_requests": self.maximum_requests,
            "maximum_retries": self.maximum_retries,
            "timeout_seconds": float(self.timeout_seconds),
            "minimum_request_interval_seconds": float(
                self.minimum_request_interval_seconds
            ),
            "maximum_file_bytes": self.maximum_file_bytes,
            "maximum_store_bytes": self.maximum_store_bytes,
            "permitted_licenses": list(self.permitted_licenses),
        }

    @property
    def config_id(self) -> str:
        canonical = json.dumps(
            self.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        return f"sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> AcquisitionConfig:
        expected = {
            "schema_version",
            "maximum_documents",
            "maximum_requests",
            "maximum_retries",
            "timeout_seconds",
            "minimum_request_interval_seconds",
            "maximum_file_bytes",
            "maximum_store_bytes",
            "permitted_licenses",
        }
        if set(data) != expected or data.get("schema_version") != 1:
            raise ValueError("unsupported acquisition configuration fields or version")
        if isinstance(data.get("schema_version"), bool):
            raise ValueError("unsupported acquisition configuration fields or version")
        license_values = data["permitted_licenses"]
        if not isinstance(license_values, list) or not all(
            isinstance(value, str) for value in license_values
        ):
            raise ValueError("permitted_licenses must be a list of strings")
        integer_fields = (
            "maximum_documents",
            "maximum_requests",
            "maximum_retries",
            "maximum_file_bytes",
            "maximum_store_bytes",
        )
        if any(
            isinstance(data[field], bool) or not isinstance(data[field], int)
            for field in integer_fields
        ):
            raise ValueError("acquisition counts and byte limits must be integers")
        timeout = data["timeout_seconds"]
        interval = data["minimum_request_interval_seconds"]
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or isinstance(interval, bool)
            or not isinstance(interval, (int, float))
        ):
            raise ValueError("acquisition time limits must be numbers")
        return cls(
            maximum_documents=cast(int, data["maximum_documents"]),
            maximum_requests=cast(int, data["maximum_requests"]),
            maximum_retries=cast(int, data["maximum_retries"]),
            timeout_seconds=float(timeout),
            minimum_request_interval_seconds=float(interval),
            maximum_file_bytes=cast(int, data["maximum_file_bytes"]),
            maximum_store_bytes=cast(int, data["maximum_store_bytes"]),
            permitted_licenses=tuple(license_values),
        )


@dataclass(frozen=True)
class OpenAlexContentAvailability:
    openalex_id: str
    pdf_available: bool
    license_id: str | None

    @classmethod
    def from_work_metadata(
        cls, openalex_id: str, metadata: Mapping[str, object]
    ) -> OpenAlexContentAvailability:
        normalized_id = openalex_id.removeprefix("https://openalex.org/")
        if not _OPENALEX_ID_PATTERN.fullmatch(normalized_id):
            raise ValueError("invalid OpenAlex work ID")
        has_content = metadata.get("has_content")
        if not isinstance(has_content, Mapping):
            raise ValueError("work metadata does not state full-text availability")
        pdf_available = has_content.get("pdf")
        if not isinstance(pdf_available, bool):
            raise ValueError("work metadata has an invalid PDF availability value")
        location = metadata.get("best_oa_location")
        license_id: str | None = None
        if isinstance(location, Mapping):
            raw_license = location.get("license")
            if raw_license is not None:
                if not isinstance(raw_license, str):
                    raise ValueError("work metadata has an invalid license identifier")
                license_id = raw_license.removeprefix("https://openalex.org/licenses/")
        return cls(normalized_id, pdf_available, license_id)


@dataclass(frozen=True)
class PermissionEvidence:
    """Reviewer-recorded rights decisions for a particular source/version."""

    source_name: str
    source_url: str
    license_id: str
    basis: str
    terms_url: str
    checked_at: datetime
    reviewer: str
    storage_permitted: bool
    indexing_permitted: bool
    passage_display_permitted: bool = False

    def __post_init__(self) -> None:
        for field_name in (
            "source_name",
            "source_url",
            "license_id",
            "basis",
            "terms_url",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must be a non-empty string")
        if not isinstance(self.checked_at, datetime):
            raise ValueError("checked_at must be a datetime")
        if not isinstance(self.reviewer, str) or not self.reviewer.strip():
            raise ValueError("reviewer must be a non-empty name or identifier")
        if not all(
            isinstance(value, bool)
            for value in (
                self.storage_permitted,
                self.indexing_permitted,
                self.passage_display_permitted,
            )
        ):
            raise ValueError("permission decisions must be booleans")
        if self.checked_at.tzinfo is None:
            object.__setattr__(
                self, "checked_at", self.checked_at.replace(tzinfo=timezone.utc)
            )
        if self.indexing_permitted and not self.storage_permitted:
            raise ValueError("indexing permission requires storage permission")
        if self.passage_display_permitted and not self.indexing_permitted:
            raise ValueError("passage display permission requires indexing permission")


class AcquisitionError(RuntimeError):
    """A bounded document acquisition failed without publishing a partial file."""


class _BoundedPdfDownloader:
    """Shared request, retry, response and storage limits for PDF adapters."""

    def __init__(
        self,
        config: AcquisitionConfig,
        http_client: httpx.AsyncClient,
        store: ArtifactStore,
        *,
        sleep: Sleep,
        clock: Clock,
        reserve_request: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self._config = config
        self._http = http_client
        self._store = store
        self._sleep = sleep
        self._clock = clock
        self._reserve_request = reserve_request
        self.requests_used = 0
        self._documents_started = 0
        self.documents_downloaded = 0
        self._next_request_at = 0.0

    async def download(
        self,
        url: str,
        source_label: str,
        *,
        params: Mapping[str, str] | None = None,
    ) -> StoredArtifact:
        if self._documents_started >= self._config.maximum_documents:
            raise AcquisitionError("configured document acquisition ceiling reached")
        self._documents_started += 1

        for attempt in range(self._config.maximum_retries + 1):
            await self._wait_for_slot()
            if self.requests_used >= self._config.maximum_requests:
                raise AcquisitionError("configured content request ceiling reached")
            if self._reserve_request is not None:
                await self._reserve_request()
            self.requests_used += 1
            try:
                async with self._http.stream(
                    "GET",
                    url,
                    params=params,
                    timeout=httpx.Timeout(self._config.timeout_seconds),
                    follow_redirects=False,
                ) as response:
                    if response.status_code in {429, 500, 502, 503, 504}:
                        if attempt < self._config.maximum_retries:
                            await self._sleep(self._retry_delay(response, attempt))
                            continue
                        raise AcquisitionError(
                            f"{source_label} request failed with HTTP {response.status_code}"
                        )
                    if response.is_redirect:
                        raise AcquisitionError(
                            f"{source_label} redirects are not followed"
                        )
                    if response.status_code != 200:
                        raise AcquisitionError(
                            f"{source_label} request failed with HTTP {response.status_code}"
                        )
                    content_type = response.headers.get("content-type", "").split(
                        ";", 1
                    )[0]
                    if content_type.lower() != "application/pdf":
                        raise AcquisitionError(f"{source_label} response is not a PDF")
                    content_length = _content_length(
                        response.headers.get("content-length"), source_label
                    )
                    if (
                        content_length is not None
                        and content_length > self._config.maximum_file_bytes
                    ):
                        raise AcquisitionError(
                            f"{source_label} PDF exceeds the configured size limit"
                        )
                    artifact = await self._store.store_pdf(
                        response.aiter_bytes(), declared_length=content_length
                    )
                    self.documents_downloaded += 1
                    return artifact
            except httpx.TimeoutException as error:
                if attempt >= self._config.maximum_retries:
                    raise AcquisitionError(
                        f"{source_label} request timed out"
                    ) from error
                await self._sleep(self._retry_delay(None, attempt))
            except httpx.TransportError as error:
                if attempt >= self._config.maximum_retries:
                    raise AcquisitionError(
                        f"{source_label} transport failed"
                    ) from error
                await self._sleep(self._retry_delay(None, attempt))
        raise AcquisitionError(f"{source_label} request exhausted its retry limit")

    async def _wait_for_slot(self) -> None:
        now = self._clock()
        delay = max(0.0, self._next_request_at - now)
        if delay:
            await self._sleep(delay)
        self._next_request_at = self._clock() + max(
            1.0, self._config.minimum_request_interval_seconds
        )

    def _retry_delay(self, response: httpx.Response | None, attempt: int) -> float:
        if response is not None:
            retry_after = response.headers.get("Retry-After")
            if retry_after:
                try:
                    return min(60.0, max(0.0, float(retry_after)))
                except ValueError:
                    try:
                        retry_at = parsedate_to_datetime(retry_after)
                        if retry_at.tzinfo is None:
                            retry_at = retry_at.replace(tzinfo=timezone.utc)
                        return min(
                            60.0,
                            max(
                                0.0,
                                (retry_at - datetime.now(timezone.utc)).total_seconds(),
                            ),
                        )
                    except (TypeError, ValueError, OverflowError):
                        pass
        return min(30.0, 2.0**attempt)


class OpenAlexContentAdapter:
    """Download one permitted OpenAlex PDF at a time to the artifact store."""

    def __init__(
        self,
        config: AcquisitionConfig,
        api_key: str,
        http_client: httpx.AsyncClient,
        store: ArtifactStore,
        *,
        sleep: Sleep = asyncio.sleep,
        clock: Clock = time.monotonic,
        reserve_request: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        if not api_key.strip():
            raise ValueError("an OpenAlex API key is required for content downloads")
        self._config = config
        self._api_key = api_key
        self._downloader = _BoundedPdfDownloader(
            config,
            http_client,
            store,
            sleep=sleep,
            clock=clock,
            reserve_request=reserve_request,
        )

    @property
    def requests_used(self) -> int:
        return self._downloader.requests_used

    @property
    def documents_downloaded(self) -> int:
        return self._downloader.documents_downloaded

    async def download_pdf(
        self,
        availability: OpenAlexContentAvailability,
        permission: PermissionEvidence,
    ) -> StoredArtifact:
        self._validate_permission(availability, permission)
        if not availability.pdf_available:
            raise AcquisitionError(
                "OpenAlex does not report a cached PDF for this work"
            )
        return await self._downloader.download(
            f"{OPENALEX_CONTENT_BASE}/works/{availability.openalex_id}.pdf",
            "OpenAlex content",
            params={"api_key": self._api_key},
        )

    def _validate_permission(
        self,
        availability: OpenAlexContentAvailability,
        permission: PermissionEvidence,
    ) -> None:
        if not permission.storage_permitted or not permission.indexing_permitted:
            raise AcquisitionError("storage and indexing permissions are required")
        if permission.source_name != "openalex-content-api":
            raise AcquisitionError(
                "permission evidence does not match the source adapter"
            )
        if permission.license_id != availability.license_id:
            raise AcquisitionError(
                "permission evidence license does not match source metadata"
            )
        if permission.license_id not in self._config.permitted_licenses:
            raise AcquisitionError(
                "license is not in the configured permitted-license list"
            )
        if permission.source_url != (
            f"{OPENALEX_CONTENT_BASE}/works/{availability.openalex_id}.pdf"
        ):
            raise AcquisitionError(
                "permission evidence does not match the document URL"
            )


class DirectSourcePdfAdapter:
    """Download pinned publisher/repository PDFs from a fixed host allowlist."""

    def __init__(
        self,
        config: AcquisitionConfig,
        http_client: httpx.AsyncClient,
        store: ArtifactStore,
        *,
        sleep: Sleep = asyncio.sleep,
        clock: Clock = time.monotonic,
    ) -> None:
        self._config = config
        self._downloader = _BoundedPdfDownloader(
            config,
            http_client,
            store,
            sleep=sleep,
            clock=clock,
        )

    @property
    def requests_used(self) -> int:
        return self._downloader.requests_used

    @property
    def documents_downloaded(self) -> int:
        return self._downloader.documents_downloaded

    async def download_pdf(self, permission: PermissionEvidence) -> StoredArtifact:
        self._validate_permission(permission)
        return await self._downloader.download(
            permission.source_url, "direct-source PDF"
        )

    def _validate_permission(self, permission: PermissionEvidence) -> None:
        if not permission.storage_permitted or not permission.indexing_permitted:
            raise AcquisitionError("storage and indexing permissions are required")
        if permission.license_id not in self._config.permitted_licenses:
            raise AcquisitionError(
                "license is not in the configured permitted-license list"
            )
        try:
            parsed = urlsplit(permission.source_url)
            host = parsed.hostname
            port = parsed.port
        except ValueError as error:
            raise AcquisitionError("direct-source PDF URL is invalid") from error
        source_name = _DIRECT_SOURCE_NAMES.get(host or "")
        if (
            parsed.scheme != "https"
            or source_name is None
            or port not in {None, 443}
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise AcquisitionError("direct-source PDF URL is not allowed")
        if permission.source_name != source_name:
            raise AcquisitionError(
                "permission evidence does not match the direct source host"
            )

        path = unquote(parsed.path)
        if any(segment in {".", ".."} for segment in path.split("/")):
            raise AcquisitionError("direct-source PDF path is not allowed")
        if host == "arxiv.org":
            path_is_pdf = _ARXIV_PDF_PATH.fullmatch(path) is not None
        elif host == "link.springer.com":
            path_is_pdf = path.startswith("/content/pdf/") and path.endswith(".pdf")
        else:
            path_is_pdf = re.fullmatch(r"/\d+/\d+/\d+\.pdf", path) is not None
        if not path_is_pdf:
            raise AcquisitionError("direct-source URL is not a supported PDF route")


def _content_length(value: str | None, source_label: str) -> int | None:
    if value is None:
        return None
    try:
        length = int(value)
    except ValueError as error:
        raise AcquisitionError(
            f"{source_label} returned an invalid content length"
        ) from error
    if length < 0:
        raise AcquisitionError(f"{source_label} returned an invalid content length")
    return length
