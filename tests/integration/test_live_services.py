"""Live boundary tests for explicitly configured disposable services."""

import asyncio
import hashlib
import json
import os
import re
import sys
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse
from uuid import UUID, uuid4, uuid5

import asyncpg
import httpx
import pytest

from research_platform.config import Settings
from research_platform.ingestion.acquisition import PermissionEvidence
from research_platform.ingestion.artifact_repository import ArtifactRepository
from research_platform.ingestion.artifacts import ArtifactStore
from research_platform.ingestion.citations import (
    CitationMetadataRepository,
    enrich_unresolved_citations,
)
from research_platform.ingestion.cli import main as ingestion_main
from research_platform.ingestion.config import (
    DiscoveryConfig,
    DiscoveryLimits,
    YearRange,
)
from research_platform.ingestion.discovery import run_discovery
from research_platform.ingestion.discovery_repository import DiscoveryRepository
from research_platform.ingestion.evidence import (
    ChunkingConfig,
    ExtractedSection,
    ExtractedTable,
    ExtractionResult,
    SourceLocation,
    TableCell,
    TokenSpan,
    chunk_section,
    chunk_table_rows,
)
from research_platform.ingestion.evidence_repository import (
    EvidenceConflict,
    EvidenceRepository,
)
from research_platform.ingestion.indexing import (
    IndexConfiguration,
    IndexConfigurationMismatch,
    IndexRepository,
    QdrantIndex,
    SnapshotAccessDenied,
    SnapshotIndexMismatch,
    SnapshotIndexNotReady,
    VectorEmbedder,
    rebuild_snapshot_index,
)
from research_platform.ingestion.manifest_report import build_manifest_review_report
from research_platform.ingestion.openalex import (
    OpenAlexClient,
    OpenAlexRequestError,
)
from research_platform.ingestion.papers import PaperRepository
from research_platform.ingestion.pdf_extraction import DoclingPdfConfig
from research_platform.ingestion.processing import (
    PdfEvidenceProcessor,
    PreparedPdfPipeline,
)
from research_platform.ingestion.runner import (
    DocumentStageFailure,
    IngestionDocument,
    IngestionExecutionError,
    IngestionRunner,
    PipelineStage,
    SharedPipelineFailure,
    StageContext,
    StageOutcome,
)
from research_platform.ingestion.snapshot_selection import SnapshotSelection
from research_platform.ingestion.snapshots import (
    SnapshotRepository,
    SnapshotValidationError,
)
from research_platform.ingestion.stage_repository import (
    IngestionJobRepository,
    JobStateError,
)
from research_platform.persistence.migrations import apply_migrations
from research_platform.search.dense_search import SnapshotDenseSearch
from research_platform.search.profiles import (
    CandidateLimits,
    DenseIndexIdentity,
    RetrievalProfile,
)
from research_platform.services.readiness import LiveDependencyChecker

TEST_DATABASE_URL = os.environ.get("RESEARCH_PLATFORM_TEST_DATABASE_URL")
TEST_QDRANT_URL = os.environ.get("RESEARCH_PLATFORM_TEST_QDRANT_URL")


async def _no_sleep(_delay: float) -> None:
    return None


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not TEST_DATABASE_URL or not TEST_QDRANT_URL,
        reason="requires dedicated disposable PostgreSQL and Qdrant services",
    ),
]


async def _wait_for_services() -> None:
    assert TEST_DATABASE_URL is not None
    assert TEST_QDRANT_URL is not None
    loop = asyncio.get_running_loop()
    deadline = loop.time() + 30
    last_error = "no connection attempt"

    while loop.time() < deadline:
        try:
            connection = await asyncpg.connect(TEST_DATABASE_URL, timeout=1)
            try:
                await connection.fetchval("SELECT 1")
            finally:
                await connection.close()

            async with httpx.AsyncClient(timeout=1) as client:
                response = await client.get(f"{TEST_QDRANT_URL.rstrip('/')}/healthz")
                response.raise_for_status()
            return
        except Exception as error:
            last_error = type(error).__name__
            await asyncio.sleep(0.5)

    raise AssertionError(f"disposable services did not become ready: {last_error}")


@pytest.fixture(scope="module", autouse=True)
def disposable_services_ready() -> None:
    assert TEST_DATABASE_URL is not None
    database_name = urlparse(TEST_DATABASE_URL).path.removeprefix("/")
    assert database_name == "research_test", (
        "integration tests require the isolated research_test database"
    )
    asyncio.run(_wait_for_services())


def test_live_readiness_reports_postgres_and_qdrant() -> None:
    assert TEST_DATABASE_URL is not None
    assert TEST_QDRANT_URL is not None
    settings = Settings(
        database_url=TEST_DATABASE_URL,
        qdrant_url=TEST_QDRANT_URL,
        dependency_timeout_seconds=2,
    )

    report = asyncio.run(LiveDependencyChecker(settings).check())

    assert report.dependencies == {"postgres": True, "qdrant": True}


def test_migration_is_repeatable_and_database_constraints_are_enforced(
    tmp_path: Path,
) -> None:
    assert TEST_DATABASE_URL is not None

    async def exercise_database() -> None:
        initial_migration_directory = tmp_path / "phase0"
        initial_migration_directory.mkdir()
        initial_migration = Path(__file__).parents[2] / "migrations" / "001_initial.sql"
        (initial_migration_directory / "001_initial.sql").write_text(
            initial_migration.read_text(encoding="utf-8"), encoding="utf-8"
        )
        await apply_migrations(TEST_DATABASE_URL, initial_migration_directory)
        connection = await asyncpg.connect(TEST_DATABASE_URL)
        try:
            versions = await connection.fetch(
                "SELECT version FROM schema_migrations ORDER BY version"
            )
            assert [row["version"] for row in versions] == ["001_initial"]
        finally:
            await connection.close()

        await asyncio.gather(
            apply_migrations(TEST_DATABASE_URL),
            apply_migrations(TEST_DATABASE_URL),
        )
        await apply_migrations(TEST_DATABASE_URL)
        connection = await asyncpg.connect(TEST_DATABASE_URL)
        transaction = connection.transaction()
        await transaction.start()
        try:
            versions = await connection.fetch(
                "SELECT version FROM schema_migrations ORDER BY version"
            )
            assert [row["version"] for row in versions] == [
                "001_initial",
                "002_ingestion_evidence",
                "003_openalex_discovery",
                "004_identity_and_manifest_imports",
                "005_artifact_permission_checks",
                "006_unresolved_citation_metadata",
                "007_extraction_output_fingerprints",
                "008_evidence_section_cascade",
                "009_extraction_source_artifacts",
                "010_job_leases_and_snapshot_review",
                "011_unique_index_collection_identity",
                "012_targeted_retry_reasons",
                "013_ingestion_job_plans",
                "014_snapshot_chunking_configuration",
                "015_snapshot_variant_lineage",
            ]

            collection_name = f"integration-{uuid4().hex}"
            await connection.execute(
                "INSERT INTO collections (name) VALUES ($1)",
                collection_name,
            )

            with pytest.raises(asyncpg.UniqueViolationError):
                async with connection.transaction():
                    await connection.execute(
                        "INSERT INTO collections (name) VALUES ($1)",
                        collection_name,
                    )

            with pytest.raises(asyncpg.ForeignKeyViolationError):
                async with connection.transaction():
                    await connection.execute(
                        """
                        INSERT INTO documents (paper_id, source_type, version)
                        VALUES ('missing-paper', 'integration-test', 'v1')
                        """
                    )
        finally:
            await transaction.rollback()
            await connection.close()

    asyncio.run(exercise_database())


def test_qdrant_accepts_and_removes_a_temporary_collection() -> None:
    assert TEST_QDRANT_URL is not None
    collection_name = f"phase0-integration-{uuid4().hex}"

    async def exercise_qdrant() -> None:
        async with httpx.AsyncClient(timeout=5) as client:
            created = False
            try:
                response = await client.put(
                    f"{TEST_QDRANT_URL.rstrip('/')}/collections/{collection_name}",
                    json={"vectors": {"size": 2, "distance": "Dot"}},
                )
                response.raise_for_status()
                created = True

                details = await client.get(
                    f"{TEST_QDRANT_URL.rstrip('/')}/collections/{collection_name}"
                )
                details.raise_for_status()
                assert details.json()["result"]["status"] == "green"
            finally:
                if created:
                    deleted = await client.delete(
                        f"{TEST_QDRANT_URL.rstrip('/')}/collections/{collection_name}"
                    )
                    deleted.raise_for_status()

    asyncio.run(exercise_qdrant())


def test_failed_migration_rolls_back_ddl_and_version(tmp_path: Path) -> None:
    assert TEST_DATABASE_URL is not None
    migration_dir = tmp_path
    (migration_dir / "999_failure.sql").write_text(
        "CREATE TABLE migration_failure_probe (id integer);\nTHIS IS NOT VALID SQL;\n",
        encoding="utf-8",
    )

    async def exercise_failure() -> None:
        await apply_migrations(TEST_DATABASE_URL)
        with pytest.raises(asyncpg.PostgresSyntaxError):
            await apply_migrations(TEST_DATABASE_URL, migration_dir)

        connection = await asyncpg.connect(TEST_DATABASE_URL)
        try:
            assert (
                await connection.fetchval(
                    "SELECT to_regclass('public.migration_failure_probe')"
                )
                is None
            )
            assert (
                await connection.fetchval(
                    "SELECT 1 FROM schema_migrations WHERE version = '999_failure'"
                )
                is None
            )
        finally:
            await connection.close()

    asyncio.run(exercise_failure())


def test_discovery_resumes_from_cursor_and_approves_immutable_manifest() -> None:
    assert TEST_DATABASE_URL is not None
    configuration = DiscoveryConfig(
        queries=("hybrid retrieval", "reranking"),
        year_range=YearRange(start_year=2020, end_year=2026),
        older_paper_exceptions=("W17",),
        limits=DiscoveryLimits(
            per_page=1,
            max_pages_per_query=2,
            max_total_requests=8,
            max_retries=0,
        ),
    )

    def record(openalex_id: str, year: int) -> dict[str, object]:
        return {
            "id": f"https://openalex.org/{openalex_id}",
            "title": None if openalex_id == "W456" else f"Research work {openalex_id}",
            "publication_year": year,
            "language": "en",
            "type": "article",
            "doi": None,
            "cited_by_count": 3,
            "abstract_inverted_index": {"Evidence": [0]},
            "authorships": (
                [
                    {
                        "author": {
                            "id": "https://openalex.org/A123",
                            "display_name": "Integration Author",
                        }
                    }
                ]
                if openalex_id == "W123"
                else []
            ),
            "locations": (
                [
                    {
                        "source": {
                            "id": "https://openalex.org/S123",
                            "display_name": "Integration Journal",
                        },
                        "landing_page_url": "https://example.org/paper/W123",
                        "pdf_url": "https://example.org/paper/W123.pdf",
                        "version": "publishedVersion",
                        "is_published": True,
                        "license": "cc-by",
                    }
                ]
                if openalex_id == "W123"
                else []
            ),
            "referenced_works": {
                "W123": ["https://openalex.org/W456", "https://openalex.org/W999"],
                "W456": ["https://openalex.org/W17"],
            }.get(openalex_id, []),
        }

    async def exercise() -> None:
        await apply_migrations(TEST_DATABASE_URL)
        pool = await asyncpg.create_pool(TEST_DATABASE_URL, min_size=1, max_size=2)
        assert pool is not None
        repository = DiscoveryRepository(pool)
        run_id = await repository.create_run(configuration, "test-revision")

        async def reserve_request() -> None:
            await repository.reserve_request(
                run_id, configuration.limits.max_total_requests
            )

        first_calls: list[str] = []

        def fail_after_checkpoint(request: httpx.Request) -> httpx.Response:
            cursor = request.url.params.get("cursor", "single")
            first_calls.append(cursor)
            if cursor == "*":
                return httpx.Response(
                    200,
                    json={
                        "meta": {
                            "count": 2,
                            "next_cursor": "saved-cursor",
                            "cost_usd": 0.001,
                        },
                        "results": [record("W123", 2024)],
                    },
                )
            return httpx.Response(503)

        try:
            async with httpx.AsyncClient(
                transport=httpx.MockTransport(fail_after_checkpoint)
            ) as http:
                first_client = OpenAlexClient(
                    configuration,
                    "test-secret",
                    http,
                    reserve_request=reserve_request,
                    sleep=_no_sleep,
                    clock=lambda: 0.0,
                )
                with pytest.raises(OpenAlexRequestError):
                    await run_discovery(run_id, configuration, repository, first_client)

            resume_points = await repository.resume_points(run_id)
            assert [
                (point.query_index, point.cursor, point.pages_completed)
                for point in resume_points
            ] == [
                (0, "saved-cursor", 1),
                (1, "*", 0),
                (2, "*", 0),
            ]

            resumed_calls: list[tuple[str, str]] = []

            def finish_discovery(request: httpx.Request) -> httpx.Response:
                path = request.url.path
                cursor = request.url.params.get("cursor", "single")
                resumed_calls.append((path, cursor))
                if path.endswith("/W17"):
                    return httpx.Response(200, json=record("W17", 2015))
                if request.url.params.get("search") == "hybrid retrieval":
                    assert cursor == "saved-cursor"
                    result = record("W456", 2025)
                else:
                    assert request.url.params.get("search") == "reranking"
                    result = record("W123", 2024)
                return httpx.Response(
                    200,
                    json={
                        "meta": {"count": 1, "next_cursor": None, "cost_usd": 0.001},
                        "results": [result],
                    },
                )

            async with httpx.AsyncClient(
                transport=httpx.MockTransport(finish_discovery)
            ) as http:
                second_client = OpenAlexClient(
                    configuration,
                    "test-secret",
                    http,
                    reserve_request=reserve_request,
                    sleep=_no_sleep,
                    clock=lambda: 0.0,
                )
                outcome = await run_discovery(
                    run_id, configuration, repository, second_client
                )

            assert outcome.status == "completed"
            assert outcome.request_attempts == 3
            assert resumed_calls == [
                ("/works", "saved-cursor"),
                ("/works", "*"),
                ("/works/W17", "single"),
            ]
            assert await repository.resume_points(run_id) == ()
            manifest_id = await repository.prepare_shortlist_manifest(
                run_id, version=1, per_query_limit=2
            )
            items = await repository.list_manifest_items(manifest_id)
            assert {item.openalex_id for item in items} == {"W123", "W456", "W17"}
            w123 = next(item for item in items if item.openalex_id == "W123")
            assert {origin["query"] for origin in w123.origins} == {
                "hybrid retrieval",
                "reranking",
            }
            w17 = next(item for item in items if item.openalex_id == "W17")
            assert w17.selection_signals["older_paper_exception"] is True
            with pytest.raises(ValueError, match="every decision"):
                await repository.approve_manifest(manifest_id, "reviewer")
            with pytest.raises(ValueError, match="approved manifest"):
                await PaperRepository(pool).import_approved_manifest(manifest_id)

            await repository.set_manifest_item(
                manifest_id,
                "W123",
                "include",
                "Directly evaluates hybrid against dense retrieval.",
                ("hybrid_dense", "reranking_latency"),
            )
            await repository.set_manifest_item(
                manifest_id,
                "W456",
                "include",
                "Tests citation links while retaining the source's missing title.",
                ("chunking_citation",),
            )
            await repository.set_manifest_item(
                manifest_id,
                "W17",
                "exclude",
                "The older work does not answer the selected coverage questions.",
            )
            with pytest.raises(ValueError, match="all three coverage"):
                await repository.approve_manifest(manifest_id, "reviewer")
            await repository.set_manifest_coverage(
                manifest_id,
                "hybrid_dense",
                "covered",
                "Reviewed candidate relevance and marked included evidence.",
            )
            await repository.set_manifest_coverage(
                manifest_id,
                "reranking_latency",
                "gap",
                "The current shortlist does not yet support both quality and latency.",
            )
            await repository.set_manifest_coverage(
                manifest_id,
                "chunking_citation",
                "gap",
                "No candidate in this fixture addresses chunking and citation support.",
            )
            await repository.approve_manifest(manifest_id, "integration-reviewer")
            header = await repository.manifest_header(manifest_id)
            assert header.status == "approved"
            coverage_reviews = await repository.list_manifest_coverage(manifest_id)
            assert len(coverage_reviews) == 3
            run_summary = await repository.run_summary_for_manifest(manifest_id)
            review_report = build_manifest_review_report(
                header,
                run_summary,
                await repository.list_manifest_items(manifest_id),
                coverage_reviews,
            )
            assert review_report["review_yield"]["reviewed"] == 3
            assert review_report["review_yield"][
                "reviewer_inclusion_share"
            ] == pytest.approx(2 / 3)
            assert review_report["discovery"]["request_limit"] == 8
            assert "does not estimate recall" in review_report["limitations"][0]

            paper_repository = PaperRepository(pool)
            imported = await paper_repository.import_approved_manifest(manifest_id)
            repeated_import = await paper_repository.import_approved_manifest(
                manifest_id
            )
            assert imported.new_papers == 2
            assert imported.imported_candidates == 2
            assert repeated_import.new_papers == 0
            assert repeated_import.imported_candidates == 0
            paper_rows = await pool.fetch(
                """
                SELECT openalex_id, title FROM papers
                WHERE openalex_id = ANY($1::text[])
                ORDER BY openalex_id
                """,
                ["W123", "W456"],
            )
            assert [(row["openalex_id"], row["title"]) for row in paper_rows] == [
                ("W123", "Research work W123"),
                ("W456", None),
            ]
            document_rows = await pool.fetch(
                """
                SELECT paper_id, version, version_kind, status
                FROM documents WHERE paper_id = 'W123'
                """
            )
            assert [
                (row["paper_id"], row["version"], row["version_kind"], row["status"])
                for row in document_rows
            ] == [("W123", "publishedVersion", "published", "metadata_only")]
            author_rows = await pool.fetch(
                """
                SELECT author.openalex_id, author.display_name, link.author_position
                FROM paper_authors AS link
                JOIN authors AS author ON author.id = link.author_id
                WHERE link.paper_id = 'W123'
                """
            )
            assert [
                (row["openalex_id"], row["display_name"], row["author_position"])
                for row in author_rows
            ] == [("A123", "Integration Author", 0)]
            resolved_edges = await pool.fetch(
                "SELECT citing_paper_id, cited_paper_id FROM citations ORDER BY 1, 2"
            )
            assert [
                (row["citing_paper_id"], row["cited_paper_id"])
                for row in resolved_edges
            ] == [("W123", "W456")]
            unresolved_rows = await pool.fetch(
                """
                SELECT target_identifier, resolved_paper_id
                FROM unresolved_citations ORDER BY target_identifier
                """
            )
            assert [
                (row["target_identifier"], row["resolved_paper_id"])
                for row in unresolved_rows
            ] == [
                ("W17", None),
                ("W999", None),
            ]

            def citation_metadata_response(
                request: httpx.Request,
            ) -> httpx.Response:
                if request.url.path.endswith("/W999"):
                    return httpx.Response(404)
                assert request.url.path.endswith("/W17")
                return httpx.Response(200, json=record("W17", 2015))

            async with httpx.AsyncClient(
                transport=httpx.MockTransport(citation_metadata_response)
            ) as http:
                metadata_client = OpenAlexClient(
                    configuration,
                    "test-secret",
                    http,
                    sleep=_no_sleep,
                    clock=lambda: 0.0,
                )
                metadata_outcome = await enrich_unresolved_citations(
                    CitationMetadataRepository(pool),
                    metadata_client,
                    limit=8,
                    code_revision="test-revision",
                )
            assert metadata_outcome.identifiers_checked == 2
            assert metadata_outcome.metadata_found == 1
            assert metadata_outcome.identifiers_not_found == 1
            assert metadata_outcome.request_attempts == 2
            enriched_rows = await pool.fetch(
                """
                SELECT target_identifier, lookup_status, configuration_id,
                       code_revision, metadata
                FROM unresolved_citation_metadata
                ORDER BY target_identifier
                """
            )
            assert [
                (
                    row["target_identifier"],
                    row["lookup_status"],
                    row["configuration_id"],
                    row["code_revision"],
                )
                for row in enriched_rows
            ] == [
                ("W17", "found", configuration.config_id, "test-revision"),
                ("W999", "not_found", configuration.config_id, "test-revision"),
            ]
            assert await CitationMetadataRepository(pool).pending_targets(8) == ()
            assert (
                await pool.fetchval(
                    "SELECT count(*) FROM papers WHERE openalex_id IN ('W17', 'W999')"
                )
                == 0
            )

            connection = await asyncpg.connect(TEST_DATABASE_URL)
            try:
                with pytest.raises(asyncpg.PostgresError, match="immutable"):
                    async with connection.transaction():
                        await connection.execute(
                            """
                            UPDATE discovery_manifest_items
                            SET reason = 'attempted mutation'
                            WHERE manifest_id = $1
                            """,
                            manifest_id,
                        )
            finally:
                await connection.close()
        finally:
            await pool.close()

    asyncio.run(exercise())


async def _byte_chunks(content: bytes):
    yield content


def test_artifact_permission_evidence_is_persisted_separately(
    tmp_path: Path,
) -> None:
    assert TEST_DATABASE_URL is not None

    async def exercise(tmp_path: Path) -> None:
        await apply_migrations(TEST_DATABASE_URL)
        pool = await asyncpg.create_pool(TEST_DATABASE_URL, min_size=1, max_size=2)
        assert pool is not None
        paper_id = f"artifact-test-{uuid4().hex}"
        try:
            async with pool.acquire() as connection:
                await connection.execute(
                    "INSERT INTO papers (id, title) VALUES ($1, 'Artifact test')",
                    paper_id,
                )
                document_id = await connection.fetchval(
                    """
                    INSERT INTO documents (paper_id, source_type, version, status)
                    VALUES ($1, 'openalex-content-api', 'published', 'metadata_only')
                    RETURNING id
                    """,
                    paper_id,
                )
            assert isinstance(document_id, UUID)
            content = b"%PDF-1.7\nartifact repository fixture\n%%EOF\n"
            artifact = await ArtifactStore(
                tmp_path / "artifacts",
                maximum_file_bytes=1024,
                maximum_store_bytes=2048,
            ).store_pdf(_byte_chunks(content))
            permission = PermissionEvidence(
                source_name="openalex-content-api",
                source_url=f"https://content.openalex.org/works/{paper_id}.pdf",
                license_id="cc-by",
                basis="The paper record and license page were manually reviewed.",
                terms_url="https://creativecommons.org/licenses/by/4.0/",
                checked_at=datetime.now(timezone.utc),
                reviewer="integration-test-reviewer",
                storage_permitted=True,
                indexing_permitted=True,
                passage_display_permitted=False,
            )
            repository = ArtifactRepository(pool)
            association_id = await repository.record_download(
                document_id, artifact, permission
            )
            assert (
                await pool.fetchval(
                    "SELECT status FROM documents WHERE id = $1", document_id
                )
                == "acquired"
            )
            orphan_sha256 = "f" * 64
            await pool.execute(
                """
                INSERT INTO artifacts (sha256, storage_path, byte_size, media_type)
                VALUES ($1, $2, 128, 'application/pdf')
                """,
                orphan_sha256,
                f"sha256/ff/{orphan_sha256}.pdf",
            )
            cleanup_candidates = await repository.preview_unreferenced(
                created_before=datetime.now(timezone.utc) + timedelta(seconds=1)
            )
            assert [candidate.sha256 for candidate in cleanup_candidates] == [
                orphan_sha256
            ]
            row = await pool.fetchrow(
                """
                SELECT source_name, source_url, permission_basis,
                       storage_permitted, indexing_permitted,
                       passage_display_permitted, metadata
                FROM document_artifacts WHERE id = $1
                """,
                association_id,
            )
            assert row is not None
            metadata = row["metadata"]
            if isinstance(metadata, str):
                metadata = json.loads(metadata)
            assert row["source_name"] == "openalex-content-api"
            assert row["source_url"] == permission.source_url
            assert row["permission_basis"] == permission.basis
            assert row["storage_permitted"] is True
            assert row["indexing_permitted"] is True
            assert row["passage_display_permitted"] is False
            assert metadata["license_id"] == "cc-by"
            assert metadata["reviewer"] == "integration-test-reviewer"
            evidence_id = await pool.fetchval(
                "SELECT permission_evidence_id FROM document_artifacts WHERE id = $1",
                association_id,
            )
            assert isinstance(evidence_id, UUID)
            with pytest.raises(asyncpg.PostgresError, match="immutable"):
                async with pool.acquire() as connection:
                    async with connection.transaction():
                        await connection.execute(
                            "UPDATE document_permission_evidence SET reviewer = 'changed' WHERE id = $1",
                            evidence_id,
                        )
        finally:
            await pool.close()

    asyncio.run(exercise(tmp_path))


class _CharacterOffsetTokenizer:
    def token_spans(self, text: str) -> tuple[TokenSpan, ...]:
        return tuple(TokenSpan(index, index + 1) for index in range(len(text)))


class _WordOffsetTokenizer:
    def token_spans(self, text: str) -> tuple[TokenSpan, ...]:
        return tuple(
            TokenSpan(match.start(), match.end()) for match in re.finditer(r"\S+", text)
        )


def test_artifact_cleanup_is_retryable_and_protects_referenced_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert TEST_DATABASE_URL is not None

    async def exercise() -> None:
        await apply_migrations(TEST_DATABASE_URL)
        pool = await asyncpg.create_pool(TEST_DATABASE_URL, min_size=1, max_size=3)
        assert pool is not None
        store = ArtifactStore(
            tmp_path / "cleanup-artifacts",
            maximum_file_bytes=1024,
            maximum_store_bytes=8192,
        )
        repository = ArtifactRepository(pool)
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=1)
        old_created_at = now - timedelta(days=3)
        first_bytes = b"%PDF-1.7\nfirst orphan\n%%EOF\n"
        second_bytes = b"%PDF-1.7\nsecond orphan\n%%EOF\n"
        linked_bytes = b"%PDF-1.7\nretained source\n%%EOF\n"
        unregistered_bytes = b"%PDF-1.7\nold unregistered\n%%EOF\n"
        recent_bytes = b"%PDF-1.7\nrecent unregistered\n%%EOF\n"
        try:
            first = await store.store_pdf(_byte_chunks(first_bytes))
            second = await store.store_pdf(_byte_chunks(second_bytes))
            linked = await store.store_pdf(_byte_chunks(linked_bytes))
            unregistered = await store.store_pdf(_byte_chunks(unregistered_bytes))
            recent = await store.store_pdf(_byte_chunks(recent_bytes))
            unregistered_path = store.root / unregistered.storage_path
            os.utime(unregistered_path, (old_created_at.timestamp(),) * 2)
            old_partial = store.root / ".partial-crashed"
            recent_partial = store.root / ".partial-recent"
            old_partial.write_bytes(b"old partial")
            recent_partial.write_bytes(b"recent partial")
            os.utime(old_partial, (old_created_at.timestamp(),) * 2)

            async with pool.acquire() as connection:
                paper_id = f"cleanup-test-{uuid4().hex}"
                await connection.execute(
                    "INSERT INTO papers (id, title) VALUES ($1, 'Cleanup test')",
                    paper_id,
                )
                document_id = await connection.fetchval(
                    """
                    INSERT INTO documents (paper_id, source_type, version, status)
                    VALUES ($1, 'integration-test', 'v1', 'acquired')
                    RETURNING id
                    """,
                    paper_id,
                )
                for artifact in (first, second):
                    await connection.execute(
                        """
                        INSERT INTO artifacts (sha256, storage_path, byte_size, media_type)
                        VALUES ($1, $2, $3, 'application/pdf')
                        """,
                        artifact.sha256,
                        artifact.storage_path,
                        artifact.byte_size,
                    )
                await connection.execute(
                    "UPDATE artifacts SET created_at = $1 WHERE sha256 = ANY($2::text[])",
                    old_created_at,
                    [first.sha256, second.sha256],
                )
            assert isinstance(document_id, UUID)
            permission = PermissionEvidence(
                source_name="integration-test",
                source_url=f"https://example.org/{document_id}.pdf",
                license_id="cc-by",
                basis="Synthetic retained artifact fixture.",
                terms_url="https://creativecommons.org/licenses/by/4.0/",
                checked_at=now,
                reviewer="integration-test-reviewer",
                storage_permitted=True,
                indexing_permitted=True,
            )
            await repository.record_download(document_id, linked, permission)
            await pool.execute(
                "UPDATE artifacts SET created_at = $1 WHERE sha256 = $2",
                old_created_at,
                linked.sha256,
            )

            job_repository = IngestionJobRepository(pool)
            job_id = await job_repository.create_job(
                configuration={"operation": "membership_acquisition"},
                configuration_id="sha256:" + "a" * 64,
                code_revision="cleanup-test",
                execution_profile="membership-acquisition",
            )
            owner_token = await job_repository.claim(job_id, lease_seconds=10)
            with pytest.raises(RuntimeError, match="while an ingestion job is running"):
                await repository.cleanup_unreferenced(
                    store, created_before=cutoff, limit=10
                )
            await job_repository.finish_job(job_id, owner_token, status="cancelled")

            original_remove = store.remove_content_addressed_pdf
            interrupted = False

            def remove_then_interrupt(**kwargs: object) -> int:
                nonlocal interrupted
                byte_count = original_remove(**kwargs)  # type: ignore[arg-type]
                if not interrupted:
                    interrupted = True
                    raise RuntimeError("simulated cleanup interruption")
                return byte_count

            monkeypatch.setattr(
                store, "remove_content_addressed_pdf", remove_then_interrupt
            )
            with pytest.raises(RuntimeError, match="cleanup interruption"):
                await repository.cleanup_unreferenced(
                    store, created_before=cutoff, limit=10
                )
            assert (
                await pool.fetchval(
                    "SELECT count(*) FROM artifacts WHERE sha256 = ANY($1::text[])",
                    [first.sha256, second.sha256],
                )
                == 2
            )
            assert (
                sum(
                    not (store.root / item.storage_path).exists()
                    for item in (first, second)
                )
                == 1
            )

            monkeypatch.setattr(store, "remove_content_addressed_pdf", original_remove)
            report = await repository.cleanup_unreferenced(
                store, created_before=cutoff, limit=10
            )
            assert set(report.removed_database_artifacts) == {
                first.sha256,
                second.sha256,
            }
            assert report.removed_unregistered_files == (unregistered.storage_path,)
            assert report.removed_partial_files == (".partial-crashed",)
            assert (
                await pool.fetchval(
                    "SELECT count(*) FROM artifacts WHERE sha256 = ANY($1::text[])",
                    [first.sha256, second.sha256],
                )
                == 0
            )
            assert (
                await pool.fetchval(
                    "SELECT count(*) FROM artifacts WHERE sha256 = $1", linked.sha256
                )
                == 1
            )
            assert (store.root / linked.storage_path).exists()
            assert not unregistered_path.exists()
            assert not old_partial.exists()
            assert (store.root / recent.storage_path).exists()
            assert recent_partial.exists()
            inspection = store.inspect()
            assert inspection.stored_bytes == linked.byte_size + recent.byte_size
            assert inspection.partial_file_count == 1
        finally:
            await pool.close()

    asyncio.run(exercise())


def test_extraction_evidence_persists_once_with_table_structure() -> None:
    assert TEST_DATABASE_URL is not None

    async def exercise() -> None:
        await apply_migrations(TEST_DATABASE_URL)
        pool = await asyncpg.create_pool(TEST_DATABASE_URL, min_size=1, max_size=2)
        assert pool is not None
        paper_id = f"evidence-test-{uuid4().hex}"
        try:
            async with pool.acquire() as connection:
                await connection.execute(
                    "INSERT INTO papers (id, title) VALUES ($1, 'Evidence test')",
                    paper_id,
                )
                document_id = await connection.fetchval(
                    """
                    INSERT INTO documents (paper_id, source_type, version)
                    VALUES ($1, 'integration-test', 'v1') RETURNING id
                    """,
                    paper_id,
                )
            assert isinstance(document_id, UUID)
            extraction_id = uuid4()
            location = SourceLocation(page_index_zero_based=2, printed_page_label="3")
            section = ExtractedSection(
                ordinal=0,
                heading_path=("3", "Results"),
                text="alpha beta gamma",
                source_location=location,
            )
            table = ExtractedTable(
                ordinal=0,
                caption="Latency results",
                units="milliseconds",
                footnotes=("Lower is better.",),
                header_rows=1,
                cells=(
                    TableCell(0, 0, "Method"),
                    TableCell(0, 1, "Latency"),
                    TableCell(1, 0, "A"),
                    TableCell(
                        1,
                        1,
                        "42.1",
                        row_header_cells=((1, 0),),
                        column_header_cells=((0, 1),),
                    ),
                ),
                source_location=location,
                section_ordinal=0,
            )
            config = ChunkingConfig(2, 0, 5)
            units = chunk_section(
                section,
                document_id=document_id,
                extraction_id=extraction_id,
                config=config,
                tokenizer=_WordOffsetTokenizer(),
            ) + chunk_table_rows(
                table,
                document_id=document_id,
                extraction_id=extraction_id,
                config=config,
            )
            result = ExtractionResult(
                document_id=document_id,
                extraction_id=extraction_id,
                extractor_name="synthetic",
                extractor_revision="fixture-1",
                configuration_id="sha256:" + "a" * 64,
                status="completed",
                sections=(section,),
                tables=(table,),
                configuration={"fixture": True},
            )
            repository = EvidenceRepository(pool)
            failed_result = ExtractionResult(
                document_id=document_id,
                extraction_id=extraction_id,
                extractor_name="synthetic",
                extractor_revision="fixture-1",
                configuration_id=result.configuration_id,
                status="failed",
                failure_category="synthetic-transient-failure",
                configuration={"fixture": True},
            )
            failed = await repository.persist(failed_result, ())
            first = await repository.persist(result, units)
            repeated = await repository.persist(result, units)
            assert failed.reused_existing is False
            assert first.reused_existing is False
            assert repeated.reused_existing is True
            assert first.evidence_unit_count == 3
            assert first.table_count == 1

            row = await pool.fetchrow(
                """
                SELECT table_data, footnotes, source_location
                FROM evidence_tables
                WHERE extraction_id = $1 AND ordinal = 0
                """,
                extraction_id,
            )
            assert row is not None
            table_data = row["table_data"]
            if isinstance(table_data, str):
                table_data = json.loads(table_data)
            assert table_data["cells"][3]["row_header_cells"] == [[1, 0]]
            assert table_data["cells"][3]["column_header_cells"] == [[0, 1]]
            assert (
                await pool.fetchval(
                    "SELECT count(*) FROM chunks WHERE extraction_id = $1",
                    extraction_id,
                )
                == 3
            )

            changed_section = ExtractedSection(
                ordinal=0,
                heading_path=("3", "Results"),
                text="alpha changed gamma",
                source_location=location,
            )
            changed_units = (
                chunk_section(
                    changed_section,
                    document_id=document_id,
                    extraction_id=extraction_id,
                    config=config,
                    tokenizer=_WordOffsetTokenizer(),
                )
                + units[2:]
            )
            changed_result = ExtractionResult(
                document_id=document_id,
                extraction_id=extraction_id,
                extractor_name="synthetic",
                extractor_revision="fixture-1",
                configuration_id=result.configuration_id,
                status="completed",
                sections=(changed_section,),
                tables=(table,),
                configuration={"fixture": True},
            )
            with pytest.raises(EvidenceConflict, match="different outputs"):
                await repository.persist(changed_result, changed_units)
        finally:
            # Permission evidence is intentionally immutable; the disposable test
            # database owns cleanup for this fixture.
            await pool.close()

    asyncio.run(exercise())


def test_chunks_with_new_configuration_reuse_persisted_extraction(
    tmp_path: Path,
) -> None:
    assert TEST_DATABASE_URL is not None

    async def exercise() -> None:
        await apply_migrations(TEST_DATABASE_URL)
        pool = await asyncpg.create_pool(TEST_DATABASE_URL, min_size=1, max_size=2)
        assert pool is not None
        paper_id = f"W{uuid4().int}"
        try:
            async with pool.acquire() as connection:
                await connection.execute(
                    "INSERT INTO papers (id, title) VALUES ($1, 'Rechunk persistence')",
                    paper_id,
                )
                document_id = await connection.fetchval(
                    """
                    INSERT INTO documents (paper_id, source_type, version, status)
                    VALUES ($1, 'integration-test', 'v1', 'metadata_only')
                    RETURNING id
                    """,
                    paper_id,
                )
            assert isinstance(document_id, UUID)
            content = b"%PDF-1.7\nrechunk fixture\n%%EOF\n"
            artifact = await ArtifactStore(
                tmp_path / "rechunk-artifacts",
                maximum_file_bytes=1024,
                maximum_store_bytes=2048,
            ).store_pdf(_byte_chunks(content))
            permission = PermissionEvidence(
                source_name="integration-test",
                source_url=f"https://example.org/{paper_id}.pdf",
                license_id="cc-by",
                basis="Synthetic integration fixture permission.",
                terms_url="https://creativecommons.org/licenses/by/4.0/",
                checked_at=datetime.now(timezone.utc),
                reviewer="integration-test-reviewer",
                storage_permitted=True,
                indexing_permitted=True,
            )
            association_id = await ArtifactRepository(pool).record_download(
                document_id, artifact, permission
            )
            snapshot_id = await pool.fetchval(
                """
                INSERT INTO snapshots (name, configuration_id, configuration, code_revision)
                VALUES ($1, $2, $3::jsonb, 'integration-test') RETURNING id
                """,
                f"rechunk-snapshot-{uuid4().hex}",
                "sha256:" + "2" * 64,
                json.dumps({"fixture": True}),
            )
            assert isinstance(snapshot_id, UUID)
            await pool.execute(
                """
                INSERT INTO snapshot_items
                    (snapshot_id, paper_id, document_id, selection_reason)
                VALUES ($1, $2, $3, 'synthetic rechunk fixture')
                """,
                snapshot_id,
                paper_id,
                document_id,
            )

            class CacheOnlyParser:
                def prepare(self) -> tuple[dict[str, object], str]:
                    return {"parser": "cache-fixture"}, "sha256:" + "1" * 64

                def extract(
                    self, *_args: object, **_kwargs: object
                ) -> ExtractionResult:
                    raise AssertionError("matching stored extraction should be reused")

            async def make_processor(
                chunking: ChunkingConfig,
                target_snapshot_id: UUID = snapshot_id,
            ) -> tuple[PdfEvidenceProcessor, PreparedPdfPipeline]:
                processor = PdfEvidenceProcessor(
                    pool,
                    snapshot_id=target_snapshot_id,
                    artifact_root=tmp_path / "rechunk-artifacts",
                    parser_config=DoclingPdfConfig(device="cpu"),
                    chunking_config=chunking,
                    tokenizer=_WordOffsetTokenizer(),  # type: ignore[arg-type]
                )
                processor._parser = CacheOnlyParser()  # type: ignore[assignment]
                return processor, await processor.prepare()

            first_config = ChunkingConfig(2, 0, 2)
            first_processor, first_prepared = await make_processor(first_config)
            extraction_id = uuid5(
                document_id, first_prepared.extraction_configuration_id
            )
            section = ExtractedSection(
                ordinal=0,
                heading_path=("Results",),
                text="alpha beta gamma delta epsilon",
            )
            extraction = ExtractionResult(
                document_id=document_id,
                extraction_id=extraction_id,
                extractor_name="synthetic",
                extractor_revision="fixture-1",
                configuration_id=first_prepared.extraction_configuration_id,
                status="completed",
                source_artifact_id=association_id,
                sections=(section,),
                configuration=dict(first_prepared.extraction_configuration),
            )
            repository = EvidenceRepository(pool)
            raw_result = await repository.persist(extraction, ())
            assert raw_result.evidence_unit_count == 0
            stored = await repository.load_for_correction(extraction_id)
            assert stored.result.sections == (section,)
            assert stored.source_pdf_sha256 == artifact.sha256

            async def run_stage(
                processor: PdfEvidenceProcessor, stage: str, configuration_id: str
            ) -> StageOutcome:
                return await processor.process(
                    StageContext(
                        job_id=uuid4(),
                        document_id=document_id,
                        stage=stage,
                        configuration_id=configuration_id,
                        input_fingerprint="sha256:" + artifact.sha256,
                        upstream_references={},
                        retry_reason=None,
                    )
                )

            reused_extraction = await run_stage(
                first_processor,
                "extraction",
                first_prepared.extraction_configuration_id,
            )
            assert reused_extraction.resource_measurements["reused_existing"] is True
            first_output = await run_stage(
                first_processor, "chunking", first_prepared.chunking_configuration_id
            )
            assert first_output.resource_measurements["chunks"] > 0

            await pool.execute(
                """
                UPDATE snapshots
                SET status = 'finalized', finalized_at = now(),
                    finalized_by = 'integration-test'
                WHERE id = $1
                """,
                snapshot_id,
            )
            variant_snapshot_id = await SnapshotRepository(pool).create_variant_draft(
                snapshot_id,
                name=f"rechunk-variant-{uuid4().hex}",
                configuration_id="sha256:" + "3" * 64,
                configuration={"fixture": True, "variant": "alternate-chunks"},
                code_revision="integration-test",
            )
            second_config = ChunkingConfig(3, 0, 2)
            second_processor, second_prepared = await make_processor(
                second_config, variant_snapshot_id
            )
            assert (
                second_prepared.extraction_configuration_id
                == first_prepared.extraction_configuration_id
            )
            assert (
                second_prepared.chunking_configuration_id
                != first_prepared.chunking_configuration_id
            )
            reused_for_new_settings = await run_stage(
                second_processor,
                "extraction",
                second_prepared.extraction_configuration_id,
            )
            assert (
                reused_for_new_settings.resource_measurements["reused_existing"] is True
            )
            second_output = await run_stage(
                second_processor, "chunking", second_prepared.chunking_configuration_id
            )
            repeated_output = await run_stage(
                second_processor, "chunking", second_prepared.chunking_configuration_id
            )
            assert second_output.resource_measurements["chunks"] > 0
            assert repeated_output.resource_measurements["reused_existing"] is True
            assert (
                await pool.fetchval(
                    "SELECT count(*) FROM chunks WHERE extraction_id = $1",
                    extraction_id,
                )
                == first_output.resource_measurements["chunks"]
                + second_output.resource_measurements["chunks"]
            )
            parent_chunking_id = await pool.fetchval(
                "SELECT chunking_configuration_id FROM snapshot_items WHERE snapshot_id = $1",
                snapshot_id,
            )
            variant_chunking_id = await pool.fetchval(
                "SELECT chunking_configuration_id FROM snapshot_items WHERE snapshot_id = $1",
                variant_snapshot_id,
            )
            assert parent_chunking_id == first_prepared.chunking_configuration_id
            assert variant_chunking_id == second_prepared.chunking_configuration_id
            parent_chunk_ids = set(
                await pool.fetchval(
                    "SELECT array_agg(chunk_id ORDER BY chunk_id) FROM snapshot_item_chunks WHERE snapshot_id = $1",
                    snapshot_id,
                )
            )
            variant_chunk_ids = set(
                await pool.fetchval(
                    "SELECT array_agg(chunk_id ORDER BY chunk_id) FROM snapshot_item_chunks WHERE snapshot_id = $1",
                    variant_snapshot_id,
                )
            )
            assert len(parent_chunk_ids) == first_output.resource_measurements["chunks"]
            assert (
                len(variant_chunk_ids) == second_output.resource_measurements["chunks"]
            )
            with pytest.raises(asyncpg.ForeignKeyViolationError):
                await pool.execute(
                    "DELETE FROM chunks WHERE id = $1",
                    next(iter(parent_chunk_ids)),
                )
            assert parent_chunk_ids != variant_chunk_ids
            added_variant_chunks = variant_chunk_ids - parent_chunk_ids
            assert added_variant_chunks
            variant_only_chunk_id = sorted(added_variant_chunks)[0]
            with pytest.raises(
                asyncpg.PostgresError,
                match="chunk selection in a finalized snapshot is immutable",
            ):
                await pool.execute(
                    """
                    INSERT INTO snapshot_item_chunks
                        (snapshot_id, paper_id, document_id, extraction_id, chunk_id)
                    SELECT $1, item.paper_id, chunk.document_id, chunk.extraction_id, chunk.id
                    FROM snapshot_items item
                    JOIN chunks chunk
                      ON chunk.document_id = item.document_id
                     AND chunk.extraction_id = item.extraction_id
                    WHERE item.snapshot_id = $1 AND chunk.id = $2
                    """,
                    snapshot_id,
                    variant_only_chunk_id,
                )
            lineage = await pool.fetchrow(
                """
                SELECT parent_snapshot_id, parent_chunk_selection_id
                FROM snapshot_variant_lineage WHERE snapshot_id = $1
                """,
                variant_snapshot_id,
            )
            assert lineage["parent_snapshot_id"] == snapshot_id
            assert lineage["parent_chunk_selection_id"].startswith("sha256:")
            parent_member = (
                await SnapshotRepository(pool).inspect_members(snapshot_id)
            )[0]
            variant_member = (
                await SnapshotRepository(pool).inspect_members(variant_snapshot_id)
            )[0]
            assert parent_member.document_id == variant_member.document_id
            assert parent_member.extraction_id == variant_member.extraction_id
            assert (
                parent_member.chunk_count
                == first_output.resource_measurements["chunks"]
            )
            assert (
                variant_member.chunk_count
                == second_output.resource_measurements["chunks"]
            )
            index_inputs = await IndexRepository(pool).load_snapshot_inputs(
                variant_snapshot_id,
                IndexConfiguration(
                    collection_name=f"phase1-{uuid4().hex}",
                    embedding_model="integration-fixture",
                    embedding_revision="v1",
                    preprocessing_revision="raw-text-v1",
                    vector_size=2,
                    distance="Cosine",
                    batch_size=1,
                    maximum_input_tokens=32,
                ),
            )
            assert len(index_inputs) == second_output.resource_measurements["chunks"]
            assert {item.evidence_id for item in index_inputs} == variant_chunk_ids

            parent_index_configuration = IndexConfiguration(
                collection_name=f"phase2-parent-{uuid4().hex}",
                embedding_model="integration-fixture",
                embedding_revision="v1",
                preprocessing_revision="raw-text-v1",
                vector_size=2,
                distance="Cosine",
                batch_size=2,
                maximum_input_tokens=32,
            )
            variant_index_configuration = IndexConfiguration(
                collection_name=f"phase2-variant-{uuid4().hex}",
                embedding_model="integration-fixture",
                embedding_revision="v1",
                preprocessing_revision="raw-text-v1",
                vector_size=2,
                distance="Cosine",
                batch_size=2,
                maximum_input_tokens=32,
            )
            async with httpx.AsyncClient(
                base_url=TEST_QDRANT_URL.rstrip("/"), timeout=10
            ) as qdrant_http:
                try:
                    parent_index = QdrantIndex(parent_index_configuration, qdrant_http)
                    variant_index = QdrantIndex(
                        variant_index_configuration, qdrant_http
                    )
                    await rebuild_snapshot_index(
                        IndexRepository(pool),
                        parent_index,
                        _IntegrationEmbedder(),
                        snapshot_id,
                    )
                    await rebuild_snapshot_index(
                        IndexRepository(pool),
                        variant_index,
                        _IntegrationEmbedder(),
                        variant_snapshot_id,
                    )
                    parent_selection = await IndexRepository(
                        pool
                    ).snapshot_selection_for(snapshot_id)
                    variant_selection = await IndexRepository(
                        pool
                    ).snapshot_selection_for(variant_snapshot_id)

                    def dense_profile(
                        selection: SnapshotSelection, config: IndexConfiguration
                    ) -> RetrievalProfile:
                        return RetrievalProfile(
                            snapshot=selection,
                            lexical_index=None,
                            dense_index=DenseIndexIdentity(
                                model=config.embedding_model,
                                revision=config.embedding_revision,
                                preprocessing_revision=config.preprocessing_revision,
                                dimensions=config.vector_size,
                                maximum_input_tokens=config.maximum_input_tokens,
                                index_configuration_id=config.configuration_id,
                            ),
                            candidate_limits=CandidateLimits(
                                lexical_top_k=None,
                                dense_top_k=10,
                                fused_top_k=None,
                                rerank_top_k=None,
                            ),
                        )

                    parent_results = await SnapshotDenseSearch(
                        IndexRepository(pool), parent_index
                    ).search(
                        dense_profile(parent_selection, parent_index_configuration),
                        (1.0, 0.0),
                        limit=10,
                    )
                    variant_results = await SnapshotDenseSearch(
                        IndexRepository(pool), variant_index
                    ).evaluate(
                        dense_profile(variant_selection, variant_index_configuration),
                        (1.0, 0.0),
                        limit=10,
                    )
                    assert {
                        hit.evidence_id for hit in parent_results.hits
                    } == parent_chunk_ids
                    assert {
                        hit.evidence_id for hit in variant_results.hits
                    } == variant_chunk_ids
                    assert (
                        parent_results.index_configuration_id
                        != variant_results.index_configuration_id
                    )
                finally:
                    for collection_name in (
                        parent_index_configuration.collection_name,
                        variant_index_configuration.collection_name,
                    ):
                        response = await qdrant_http.delete(
                            f"/collections/{collection_name}"
                        )
                        if response.status_code not in {200, 404}:
                            response.raise_for_status()
        finally:
            await pool.close()

    asyncio.run(exercise())


class _IntegrationEmbedder(VectorEmbedder):
    async def embed(
        self, texts: tuple[str, ...] | list[str], *, configuration: IndexConfiguration
    ) -> tuple[tuple[float, ...], ...]:
        return tuple((1.0, 0.0) for _text in texts)


def test_permitted_evidence_rebuilds_and_queries_a_snapshot_index(
    tmp_path: Path,
) -> None:
    assert TEST_DATABASE_URL is not None
    assert TEST_QDRANT_URL is not None

    async def exercise() -> None:
        await apply_migrations(TEST_DATABASE_URL)
        pool = await asyncpg.create_pool(TEST_DATABASE_URL, min_size=1, max_size=2)
        assert pool is not None
        paper_id = f"W{uuid4().int}"
        snapshot_id: UUID | None = None
        configuration = IndexConfiguration(
            collection_name=f"phase1-{uuid4().hex}",
            embedding_model="integration-fixture",
            embedding_revision="v1",
            preprocessing_revision="raw-text-v1",
            vector_size=2,
            distance="Cosine",
            batch_size=1,
            maximum_input_tokens=32,
        )
        try:
            async with pool.acquire() as connection:
                await connection.execute(
                    "INSERT INTO papers (id, title, publication_year) VALUES ($1, 'Index fixture', 2024)",
                    paper_id,
                )
                document_id = await connection.fetchval(
                    """
                    INSERT INTO documents
                        (paper_id, source_type, version, status)
                    VALUES ($1, 'integration-test', 'v1', 'acquired')
                    RETURNING id
                    """,
                    paper_id,
                )
            assert isinstance(document_id, UUID)
            content = b"%PDF-1.7\nindex integration fixture\n%%EOF\n"
            artifact = await ArtifactStore(
                tmp_path / "index-artifacts",
                maximum_file_bytes=1024,
                maximum_store_bytes=2048,
            ).store_pdf(_byte_chunks(content))
            permission = PermissionEvidence(
                source_name="integration-test",
                source_url=f"https://example.org/{paper_id}.pdf",
                license_id="cc-by",
                basis="Synthetic integration fixture permission.",
                terms_url="https://creativecommons.org/licenses/by/4.0/",
                checked_at=datetime.now(timezone.utc),
                reviewer="integration-test-reviewer",
                storage_permitted=True,
                indexing_permitted=True,
            )
            artifact_association_id = await ArtifactRepository(pool).record_download(
                document_id, artifact, permission
            )
            extraction_id = uuid4()
            section = ExtractedSection(
                ordinal=0,
                heading_path=("Results",),
                text="alpha beta gamma",
                source_location=SourceLocation(page_index_zero_based=1),
            )
            extraction = ExtractionResult(
                document_id=document_id,
                extraction_id=extraction_id,
                extractor_name="synthetic",
                extractor_revision="fixture-1",
                configuration_id="sha256:" + "c" * 64,
                status="completed",
                source_artifact_id=artifact_association_id,
                sections=(section,),
                configuration={"fixture": True},
            )
            units = chunk_section(
                section,
                document_id=document_id,
                extraction_id=extraction_id,
                config=ChunkingConfig(2, 0, 4),
                tokenizer=_WordOffsetTokenizer(),
            )
            evidence_repository = EvidenceRepository(pool)
            await evidence_repository.persist(extraction, units)
            stored_extraction = await evidence_repository.load_for_correction(
                extraction_id
            )
            assert stored_extraction.result.sections == (section,)
            assert stored_extraction.source_pdf_sha256 == artifact.sha256
            snapshot_id = await pool.fetchval(
                """
                INSERT INTO snapshots (name, configuration_id, configuration, code_revision)
                VALUES ($1, $2, $3::jsonb, 'integration-test') RETURNING id
                """,
                f"index-snapshot-{uuid4().hex}",
                "sha256:" + "d" * 64,
                json.dumps({"fixture": True}),
            )
            assert isinstance(snapshot_id, UUID)
            await pool.execute(
                """
                INSERT INTO snapshot_items
                    (snapshot_id, paper_id, document_id, extraction_id, selection_reason)
                VALUES ($1, $2, $3, $4, 'synthetic test membership')
                """,
                snapshot_id,
                paper_id,
                document_id,
                extraction_id,
            )
            await pool.executemany(
                """
                INSERT INTO snapshot_item_chunks
                    (snapshot_id, paper_id, document_id, extraction_id, chunk_id)
                VALUES ($1, $2, $3, $4, $5)
                """,
                [
                    (snapshot_id, paper_id, document_id, extraction_id, unit.id)
                    for unit in units
                ],
            )

            async with httpx.AsyncClient(
                base_url=TEST_QDRANT_URL.rstrip("/"), timeout=10
            ) as http:
                index = QdrantIndex(configuration, http)
                first = await rebuild_snapshot_index(
                    IndexRepository(pool), index, _IntegrationEmbedder(), snapshot_id
                )
                repository = IndexRepository(pool)
                repeated = await rebuild_snapshot_index(
                    repository, index, _IntegrationEmbedder(), snapshot_id
                )
                concurrent = await asyncio.gather(
                    rebuild_snapshot_index(
                        repository, index, _IntegrationEmbedder(), snapshot_id
                    ),
                    rebuild_snapshot_index(
                        repository, index, _IntegrationEmbedder(), snapshot_id
                    ),
                )
                assert first.expected_count == repeated.expected_count == 2
                assert first.indexed_count == repeated.indexed_count == 2
                assert all(report.indexed_count == 2 for report in concurrent)
                assert first.batch_count == 2
                assert await index.count_snapshot(snapshot_id) == 2
                evidence_ids = await index.scroll_snapshot_ids(snapshot_id)
                assert set(evidence_ids) == {unit.id for unit in units}
                selection = await repository.snapshot_selection_for(snapshot_id)
                profile = RetrievalProfile(
                    snapshot=selection,
                    lexical_index=None,
                    dense_index=DenseIndexIdentity(
                        model=configuration.embedding_model,
                        revision=configuration.embedding_revision,
                        preprocessing_revision=configuration.preprocessing_revision,
                        dimensions=configuration.vector_size,
                        maximum_input_tokens=configuration.maximum_input_tokens,
                        index_configuration_id=configuration.configuration_id,
                    ),
                    candidate_limits=CandidateLimits(
                        lexical_top_k=None,
                        dense_top_k=10,
                        fused_top_k=None,
                        rerank_top_k=None,
                    ),
                )
                search = SnapshotDenseSearch(repository, index)
                with pytest.raises(SnapshotAccessDenied, match="finalized snapshot"):
                    await search.search(profile, (1.0, 0.0), limit=5)
                evaluation_result = await search.evaluate(profile, (1.0, 0.0), limit=5)
                matches = evaluation_result.hits
                assert {match.evidence_id for match in matches} == {
                    unit.id for unit in units
                }
                assert all(
                    match.payload["index_configuration_id"]
                    == configuration.configuration_id
                    for match in matches
                )
                await pool.execute(
                    """
                    UPDATE snapshot_index_states
                    SET status = 'reconciliation_required'
                    WHERE snapshot_id = $1 AND configuration_id = $2
                    """,
                    snapshot_id,
                    configuration.configuration_id,
                )
                with pytest.raises(
                    SnapshotIndexNotReady, match="reconciliation_required"
                ):
                    await search.evaluate(profile, (1.0, 0.0), limit=5)
                await pool.execute(
                    """
                    UPDATE snapshot_index_states
                    SET status = 'ready'
                    WHERE snapshot_id = $1 AND configuration_id = $2
                    """,
                    snapshot_id,
                    configuration.configuration_id,
                )
                mismatched_selection = replace(
                    selection, chunk_selection_id="sha256:" + "f" * 64
                )
                with pytest.raises(SnapshotIndexMismatch, match="profile"):
                    await search.evaluate(
                        replace(profile, snapshot=mismatched_selection),
                        (1.0, 0.0),
                        limit=5,
                    )
                incompatible_configuration = IndexConfiguration(
                    collection_name=configuration.collection_name,
                    embedding_model="other-model",
                    embedding_revision="v1",
                    preprocessing_revision="raw-text-v1",
                    vector_size=3,
                    distance="Cosine",
                    batch_size=1,
                    maximum_input_tokens=32,
                )
                mismatch = QdrantIndex(incompatible_configuration, http)
                with pytest.raises(IndexConfigurationMismatch, match="dimensions"):
                    await mismatch.ensure_collection()
                with pytest.raises(IndexConfigurationMismatch, match="assigned"):
                    await IndexRepository(pool).set_index_state(
                        snapshot_id,
                        incompatible_configuration,
                        status="building",
                        expected_count=2,
                        indexed_count=0,
                        details={},
                    )
                state = await pool.fetchrow(
                    """
                    SELECT status, expected_count, indexed_count
                    FROM snapshot_index_states
                    WHERE snapshot_id = $1 AND configuration_id = $2
                    """,
                    snapshot_id,
                    configuration.configuration_id,
                )
                assert state is not None
                assert (
                    state["status"],
                    state["expected_count"],
                    state["indexed_count"],
                ) == (
                    "ready",
                    2,
                    2,
                )
        finally:
            async with httpx.AsyncClient(
                base_url=TEST_QDRANT_URL.rstrip("/"), timeout=5
            ) as http:
                response = await http.delete(
                    f"/collections/{configuration.collection_name}"
                )
                if response.status_code not in {200, 404}:
                    response.raise_for_status()
            if snapshot_id is not None:
                async with pool.acquire() as connection:
                    await connection.execute(
                        "DELETE FROM snapshot_index_states WHERE snapshot_id = $1",
                        snapshot_id,
                    )
                    await connection.execute(
                        "DELETE FROM snapshot_items WHERE snapshot_id = $1", snapshot_id
                    )
                    await connection.execute(
                        "DELETE FROM snapshots WHERE id = $1", snapshot_id
                    )
            # Permission evidence is intentionally immutable; the disposable test
            # database owns cleanup for this fixture.
            await pool.close()

    asyncio.run(exercise())


def test_job_leases_recover_and_stage_attempts_checkpoint() -> None:
    assert TEST_DATABASE_URL is not None

    async def exercise() -> None:
        await apply_migrations(TEST_DATABASE_URL)
        pool = await asyncpg.create_pool(TEST_DATABASE_URL, min_size=1, max_size=2)
        assert pool is not None
        repository = IngestionJobRepository(pool)
        paper_id = f"job-test-{uuid4().hex}"
        try:
            async with pool.acquire() as connection:
                await connection.execute(
                    "INSERT INTO papers (id, title) VALUES ($1, 'Job test')", paper_id
                )
                document_id = await connection.fetchval(
                    """
                    INSERT INTO documents (paper_id, source_type, version)
                    VALUES ($1, 'integration-test', 'v1') RETURNING id
                    """,
                    paper_id,
                )
            assert isinstance(document_id, UUID)
            first_job = await repository.create_job(
                configuration={"stage": "fixture"},
                configuration_id="sha256:" + "1" * 64,
                code_revision="integration-test",
                execution_profile="test",
                storage_limit_bytes=1024,
            )
            second_job = await repository.create_job(
                configuration={"stage": "fixture"},
                configuration_id="sha256:" + "2" * 64,
                code_revision="integration-test",
                execution_profile="test",
            )
            first_owner = await repository.claim(first_job, lease_seconds=60)
            with pytest.raises(JobStateError, match="another ingestion job"):
                await repository.claim(second_job, lease_seconds=60)
            attempt = await repository.start_attempt(
                first_job,
                first_owner,
                document_id=document_id,
                stage="extraction",
                configuration_id="sha256:" + "3" * 64,
                input_fingerprint="sha256:" + "4" * 64,
            )
            await repository.finish_attempt(
                attempt.id,
                first_owner,
                status="failed",
                failure_category="temporary-parser-error",
                error_message=(
                    "access token=hidden; parser context: RESTRICTED_PAPER_PASSAGE_9f14"
                ),
                retryable=True,
            )
            retry = await repository.start_attempt(
                first_job,
                first_owner,
                document_id=document_id,
                stage="extraction",
                configuration_id="sha256:" + "3" * 64,
                input_fingerprint="sha256:" + "4" * 64,
            )
            assert retry.attempt_number == 2
            await repository.finish_attempt(
                retry.id,
                first_owner,
                status="completed",
                output_references={"extraction_id": str(uuid4())},
                resource_measurements={"peak_rss_bytes": 1234},
            )
            failed_message = await pool.fetchval(
                "SELECT error_message FROM ingestion_stage_attempts WHERE id = $1",
                attempt.id,
            )
            assert failed_message == "details omitted; see failure_category"
            assert "hidden" not in failed_message
            assert "RESTRICTED_PAPER_PASSAGE_9f14" not in failed_message
            summary = await repository.get_summary(first_job)
            assert summary.status == "running"
            assert summary.completed_documents == 1
            assert summary.failed_attempts == 1
            assert summary.running_attempts == 0
            await repository.finish_job(first_job, first_owner, status="completed")
            with pytest.raises(JobStateError, match="completed"):
                await repository.claim(first_job)

            stale_owner = await repository.claim(second_job, lease_seconds=60)
            stale_attempt = await repository.start_attempt(
                second_job,
                stale_owner,
                document_id=document_id,
                stage="extraction",
                configuration_id="sha256:" + "3" * 64,
                input_fingerprint="sha256:" + "4" * 64,
            )
            await pool.execute(
                "UPDATE ingestion_jobs SET lease_expires_at = now() - interval '1 second' WHERE id = $1",
                second_job,
            )
            third_job = await repository.create_job(
                configuration={"stage": "fixture"},
                configuration_id="sha256:" + "5" * 64,
                code_revision="integration-test",
                execution_profile="test",
            )
            third_owner = await repository.claim(third_job, lease_seconds=60)
            with pytest.raises(JobStateError, match="current live job lease"):
                await repository.finish_attempt(
                    stale_attempt.id, stale_owner, status="completed"
                )
            assert (await repository.get_summary(second_job)).status == "pending"
            assert (await repository.get_summary(second_job)).failed_attempts == 1
            await repository.finish_job(third_job, third_owner, status="cancelled")
            recovered_owner = await repository.claim(second_job, lease_seconds=60)
            recovered_attempt = await repository.start_attempt(
                second_job,
                recovered_owner,
                document_id=document_id,
                stage="extraction",
                configuration_id="sha256:" + "3" * 64,
                input_fingerprint="sha256:" + "4" * 64,
            )
            assert recovered_attempt.attempt_number == 2
            with pytest.raises(JobStateError, match="running stage attempts"):
                await repository.finish_job(
                    second_job, recovered_owner, status="completed"
                )
            await repository.finish_attempt(
                recovered_attempt.id, recovered_owner, status="skipped"
            )
            await repository.finish_job(second_job, recovered_owner, status="cancelled")

            acquisition_jobs = [
                await repository.create_job(
                    configuration={"operation": "membership_acquisition"},
                    configuration_id="sha256:" + digit * 64,
                    code_revision="integration-test",
                    execution_profile="membership-acquisition",
                )
                for digit in ("6", "7")
            ]
            acquisition_owner = await repository.claim(
                acquisition_jobs[0], lease_seconds=60
            )
            content_requests_started = 0
            with pytest.raises(JobStateError, match="another ingestion job"):
                await repository.claim(acquisition_jobs[1], lease_seconds=60)
                content_requests_started += 1
            assert content_requests_started == 0
            await repository.finish_job(
                acquisition_jobs[0], acquisition_owner, status="cancelled"
            )
        finally:
            await pool.close()

    asyncio.run(exercise())


def test_snapshot_finalization_requires_100_indexed_permitted_papers() -> None:
    assert TEST_DATABASE_URL is not None

    async def exercise() -> None:
        await apply_migrations(TEST_DATABASE_URL)
        pool = await asyncpg.create_pool(TEST_DATABASE_URL, min_size=1, max_size=2)
        assert pool is not None
        repository = SnapshotRepository(pool)
        suffix = uuid4().hex
        paper_ids = [f"snapshot-{suffix}-{index}" for index in range(100)]
        document_ids = [uuid4() for _ in paper_ids]
        permission_ids = [uuid4() for _ in paper_ids]
        artifact_link_ids = [uuid4() for _ in paper_ids]
        extraction_ids = [uuid4() for _ in paper_ids]
        section_ids = [uuid4() for _ in paper_ids]
        artifact_id = uuid4()
        evidence_ids = [f"snapshot-evidence-{suffix}-{index}" for index in range(100)]
        evidence_ids_sha256 = hashlib.sha256(
            "\n".join(sorted(evidence_ids)).encode("utf-8")
        ).hexdigest()
        snapshot_id: UUID | None = None
        index_configuration = IndexConfiguration(
            collection_name=f"snapshot-{suffix[:20]}",
            embedding_model="fixture-model",
            embedding_revision="fixture-v1",
            preprocessing_revision="raw-v1",
            vector_size=2,
            distance="Cosine",
            batch_size=10,
            maximum_input_tokens=32,
        )
        try:
            async with pool.acquire() as connection:
                await connection.executemany(
                    "INSERT INTO papers (id, title, publication_year) VALUES ($1, $2, 2024)",
                    [
                        (paper_id, f"Paper {index}")
                        for index, paper_id in enumerate(paper_ids)
                    ],
                )
                await connection.executemany(
                    """
                    INSERT INTO documents (id, paper_id, source_type, version, status)
                    VALUES ($1, $2, 'integration-test', 'v1', 'acquired')
                    """,
                    list(zip(document_ids, paper_ids, strict=True)),
                )
                checksum = "a" * 64
                await connection.execute(
                    """
                    INSERT INTO artifacts (id, sha256, storage_path, byte_size, media_type)
                    VALUES ($1, $2, $3, 128, 'application/pdf')
                    """,
                    artifact_id,
                    checksum,
                    f"sha256/aa/{checksum}.pdf",
                )
                permission_rows = [
                    (
                        permission_id,
                        document_id,
                        f"https://example.org/{paper_id}.pdf",
                        datetime.now(timezone.utc),
                    )
                    for permission_id, document_id, paper_id in zip(
                        permission_ids, document_ids, paper_ids, strict=True
                    )
                ]
                await connection.executemany(
                    """
                    INSERT INTO document_permission_evidence
                        (id, document_id, source_name, source_url, license_id,
                         terms_url, permission_basis, reviewer, checked_at,
                         storage_permitted, indexing_permitted)
                    VALUES ($1, $2, 'integration-test', $3, 'cc-by', $4,
                            'Synthetic permission evidence', 'integration-reviewer',
                            $5, TRUE, TRUE)
                    """,
                    [
                        (
                            permission_id,
                            document_id,
                            source_url,
                            "https://creativecommons.org/licenses/by/4.0/",
                            checked_at,
                        )
                        for permission_id, document_id, source_url, checked_at in permission_rows
                    ],
                )
                await connection.executemany(
                    """
                    INSERT INTO document_artifacts
                        (id, document_id, artifact_id, role, source_name, source_url,
                         acquired_at, permission_basis, storage_permitted,
                         indexing_permitted, permission_evidence_id)
                    VALUES ($1, $2, $3, 'source_pdf', 'integration-test', $4,
                            now(), 'Synthetic permission evidence', TRUE, TRUE, $5)
                    """,
                    [
                        (link_id, document_id, artifact_id, source_url, permission_id)
                        for link_id, document_id, permission_id, source_url in zip(
                            artifact_link_ids,
                            document_ids,
                            permission_ids,
                            [row[2] for row in permission_rows],
                            strict=True,
                        )
                    ],
                )
                await connection.executemany(
                    """
                    INSERT INTO extractions
                        (id, document_id, source_artifact_id, extractor_name,
                         extractor_revision, configuration_id, configuration, status,
                         completed_at, output_sha256)
                    VALUES ($1, $2, $3, 'fixture', 'v1', $4, '{}'::jsonb,
                            'completed', now(), $5)
                    """,
                    [
                        (
                            extraction_id,
                            document_id,
                            artifact_link_id,
                            "sha256:" + "6" * 64,
                            "b" * 64,
                        )
                        for extraction_id, document_id, artifact_link_id in zip(
                            extraction_ids, document_ids, artifact_link_ids, strict=True
                        )
                    ],
                )
                await connection.executemany(
                    """
                    INSERT INTO sections (id, document_id, extraction_id, title, ordinal)
                    VALUES ($1, $2, $3, 'Results', 0)
                    """,
                    [
                        (section_id, document_id, extraction_id)
                        for section_id, document_id, extraction_id in zip(
                            section_ids, document_ids, extraction_ids, strict=True
                        )
                    ],
                )
                await connection.executemany(
                    """
                    INSERT INTO chunks
                        (id, document_id, section_id, text, start_offset, end_offset,
                         extraction_id, kind)
                    VALUES ($1, $2, $3, 'Synthetic evidence', 0, 18, $4, 'text')
                    """,
                    [
                        (
                            evidence_ids[index],
                            document_id,
                            section_id,
                            extraction_id,
                        )
                        for index, (
                            document_id,
                            section_id,
                            extraction_id,
                        ) in enumerate(
                            zip(document_ids, section_ids, extraction_ids, strict=True)
                        )
                    ],
                )
            snapshot_id = await repository.create_draft(
                name=f"snapshot-{suffix}",
                configuration_id="sha256:" + "7" * 64,
                configuration={
                    "index_configuration_id": index_configuration.configuration_id
                },
                code_revision="integration-test",
            )
            await pool.executemany(
                """
                INSERT INTO snapshot_items
                    (snapshot_id, paper_id, document_id, extraction_id, selection_reason)
                VALUES ($1, $2, $3, $4, 'Synthetic finalization fixture')
                """,
                [
                    (snapshot_id, paper_id, document_id, extraction_id)
                    for paper_id, document_id, extraction_id in zip(
                        paper_ids, document_ids, extraction_ids, strict=True
                    )
                ],
            )
            await pool.execute(
                "INSERT INTO index_configurations (configuration_id, configuration) VALUES ($1, $2::jsonb)",
                index_configuration.configuration_id,
                json.dumps(index_configuration.to_dict()),
            )
            await pool.execute(
                """
                INSERT INTO snapshot_index_states
                    (snapshot_id, configuration_id, collection_name, status,
                     expected_count, indexed_count, details)
                VALUES ($1, $2, $3, 'ready', 100, 100, $4::jsonb)
                """,
                snapshot_id,
                index_configuration.configuration_id,
                index_configuration.collection_name,
                json.dumps(
                    {
                        "evidence_ids_sha256": evidence_ids_sha256,
                        "qdrant_evidence_ids_sha256": evidence_ids_sha256,
                    }
                ),
            )

            report = await repository.validate(snapshot_id)
            assert report.valid is True
            assert report.member_count == 100
            assert report.expected_chunk_count == 100
            inspected_members = await repository.inspect_members(snapshot_id)
            assert len(inspected_members) == 100
            inspected_member = inspected_members[0]
            assert inspected_member.storage_permitted is True
            assert inspected_member.indexing_permitted is True
            assert inspected_member.source_artifact_id in artifact_link_ids
            assert inspected_member.chunk_count == 1
            assert inspected_member.table_count == 0
            assert not hasattr(inspected_member, "text")
            await pool.execute(
                "UPDATE snapshot_index_states SET details = '{}'::jsonb WHERE snapshot_id = $1",
                snapshot_id,
            )
            mismatch_report = await repository.validate(snapshot_id)
            assert "index_identity_mismatch" in {
                issue.code for issue in mismatch_report.issues
            }
            with pytest.raises(SnapshotValidationError):
                await repository.finalize(snapshot_id, reviewer="integration-reviewer")
            await pool.execute(
                """
                UPDATE snapshot_index_states SET details = $2::jsonb
                WHERE snapshot_id = $1
                """,
                snapshot_id,
                json.dumps(
                    {
                        "evidence_ids_sha256": evidence_ids_sha256,
                        "qdrant_evidence_ids_sha256": evidence_ids_sha256,
                    }
                ),
            )
            finalized = await repository.finalize(
                snapshot_id, reviewer="integration-reviewer"
            )
            assert finalized.member_count == 100
            assert finalized.finalized_by == "integration-reviewer"
            assert (await repository.require_finalized(snapshot_id)).id == snapshot_id
            with pytest.raises(ValueError, match="draft snapshots"):
                await repository.add_member(
                    snapshot_id,
                    paper_id=paper_ids[0],
                    document_id=document_ids[0],
                    extraction_id=extraction_ids[0],
                    selection_reason="attempted mutation",
                )
            with pytest.raises(asyncpg.PostgresError, match="immutable"):
                async with pool.acquire() as connection:
                    async with connection.transaction():
                        await connection.execute(
                            "UPDATE snapshots SET name = 'changed' WHERE id = $1",
                            snapshot_id,
                        )
        finally:
            # Permission evidence is immutable; the test database owns cleanup.
            await pool.close()

    asyncio.run(exercise())


class _RunnerFixtureStage:
    def __init__(self, *, fail_document: UUID | None = None) -> None:
        self.fail_document = fail_document
        self.failed_once = False
        self.calls: list[UUID] = []

    async def process(self, context: StageContext) -> StageOutcome:
        self.calls.append(context.document_id)
        if context.document_id == self.fail_document and not self.failed_once:
            self.failed_once = True
            raise DocumentStageFailure(
                "synthetic_document_failure",
                "temporary synthetic parser error",
                retryable=True,
            )
        output = hashlib.sha256(
            f"{context.stage}:{context.document_id}:{context.input_fingerprint}".encode()
        ).hexdigest()
        return StageOutcome(
            output_fingerprint=f"sha256:{output}",
            output_references={"stage_output": context.stage},
            resource_measurements={"peak_rss_bytes": 1000},
        )


def test_runner_continues_after_document_failure_and_retries_only_selected_stage() -> (
    None
):
    assert TEST_DATABASE_URL is not None

    async def exercise() -> None:
        await apply_migrations(TEST_DATABASE_URL)
        pool = await asyncpg.create_pool(TEST_DATABASE_URL, min_size=1, max_size=2)
        assert pool is not None
        repository = IngestionJobRepository(pool)
        paper_ids = [f"runner-test-{uuid4().hex}" for _ in range(2)]
        documents: list[IngestionDocument] = []
        try:
            async with pool.acquire() as connection:
                for paper_id in paper_ids:
                    await connection.execute(
                        "INSERT INTO papers (id, title) VALUES ($1, 'Runner test')",
                        paper_id,
                    )
                    document_id = await connection.fetchval(
                        """
                        INSERT INTO documents (paper_id, source_type, version)
                        VALUES ($1, 'integration-test', 'v1') RETURNING id
                        """,
                        paper_id,
                    )
                    assert isinstance(document_id, UUID)
                    documents.append(
                        IngestionDocument(
                            document_id=document_id,
                            input_fingerprint="sha256:" + "a" * 64,
                        )
                    )
            job_id = await repository.create_job(
                configuration={"fixture": True},
                configuration_id="sha256:" + "b" * 64,
                code_revision="integration-test",
                execution_profile="test",
            )
            metadata = _RunnerFixtureStage()
            extraction = _RunnerFixtureStage(fail_document=documents[0].document_id)
            stages = (
                PipelineStage("metadata", "sha256:" + "c" * 64, metadata),
                PipelineStage("extraction", "sha256:" + "d" * 64, extraction),
            )
            runner = IngestionRunner(repository, lease_seconds=10)
            first = await runner.run(job_id, documents, stages)
            assert first.status == "failed"
            assert first.documents_completed == 1
            assert first.documents_failed == 1
            assert first.stages_run == 3
            assert metadata.calls == [document.document_id for document in documents]
            assert extraction.calls == [
                documents[0].document_id,
                documents[1].document_id,
            ]

            retried = await runner.run(
                job_id,
                documents,
                stages,
                selected_document_ids=(documents[0].document_id,),
                from_stage="extraction",
                retry_reason="Transient parser failure on the first attempt.",
            )
            assert retried.status == "completed"
            assert retried.documents_completed == 1
            assert retried.documents_failed == 0
            assert retried.stages_reused == 1
            assert retried.stages_run == 1
            assert len(metadata.calls) == 2
            assert extraction.calls[-1] == documents[0].document_id
            attempts = await pool.fetch(
                """
                SELECT stage, attempt_number, status, retry_reason
                FROM ingestion_stage_attempts
                WHERE job_id = $1 AND document_id = $2
                ORDER BY stage, attempt_number
                """,
                job_id,
                documents[0].document_id,
            )
            assert [
                (
                    row["stage"],
                    row["attempt_number"],
                    row["status"],
                    row["retry_reason"],
                )
                for row in attempts
            ] == [
                ("extraction", 1, "failed", None),
                (
                    "extraction",
                    2,
                    "completed",
                    "Transient parser failure on the first attempt.",
                ),
                ("metadata", 1, "completed", None),
            ]
            summary = await repository.get_summary(job_id)
            assert summary.status == "completed"
            assert summary.completed_documents == 2
            assert summary.failed_documents == 0

            class RawTextFailureStage:
                async def process(self, _context: StageContext) -> StageOutcome:
                    raise RuntimeError("parser failed on RESTRICTED_PAPER_PASSAGE_9f14")

            failed_job_id = await repository.create_job(
                configuration={"fixture": "raw-error"},
                configuration_id="sha256:" + "e" * 64,
                code_revision="integration-test",
                execution_profile="test",
            )
            with pytest.raises(IngestionExecutionError) as execution_error:
                await runner.run(
                    failed_job_id,
                    (documents[0],),
                    (
                        PipelineStage(
                            "extraction", "sha256:" + "f" * 64, RawTextFailureStage()
                        ),
                    ),
                )
            assert execution_error.value.category == "runtime_error"
            assert "RESTRICTED_PAPER_PASSAGE_9f14" not in str(execution_error.value)
            stored_failure = await pool.fetchrow(
                """
                SELECT failure_category, error_message
                FROM ingestion_stage_attempts WHERE job_id = $1
                """,
                failed_job_id,
            )
            assert stored_failure is not None
            assert stored_failure["failure_category"] == "runtime_error"
            assert (
                stored_failure["error_message"]
                == "details omitted; see failure_category"
            )
        finally:
            await pool.close()

    asyncio.run(exercise())


def test_runner_persists_full_plan_across_shared_failure_targeted_retry_and_recovery() -> (
    None
):
    assert TEST_DATABASE_URL is not None

    async def exercise() -> None:
        await apply_migrations(TEST_DATABASE_URL)
        pool = await asyncpg.create_pool(TEST_DATABASE_URL, min_size=1, max_size=2)
        assert pool is not None
        repository = IngestionJobRepository(pool)
        runner = IngestionRunner(repository, lease_seconds=10)

        async def make_documents(label: str) -> list[IngestionDocument]:
            documents: list[IngestionDocument] = []
            async with pool.acquire() as connection:
                for _ in range(2):
                    paper_id = f"{label}-{uuid4().hex}"
                    await connection.execute(
                        "INSERT INTO papers (id, title) VALUES ($1, 'Plan recovery fixture')",
                        paper_id,
                    )
                    document_id = await connection.fetchval(
                        """
                        INSERT INTO documents (paper_id, source_type, version)
                        VALUES ($1, 'integration-test', 'v1') RETURNING id
                        """,
                        paper_id,
                    )
                    assert isinstance(document_id, UUID)
                    documents.append(
                        IngestionDocument(
                            document_id=document_id,
                            input_fingerprint="sha256:" + "a" * 64,
                        )
                    )
            return documents

        try:
            # A targeted retry may repair the first failure, but cannot hide the
            # second document that was never reached before the shared failure.
            documents = await make_documents("shared-stop")
            job_id = await repository.create_job(
                configuration={"fixture": "shared-stop"},
                configuration_id="sha256:" + "b" * 64,
                code_revision="integration-test",
                execution_profile="test",
            )

            class FailSharedOnce:
                def __init__(self) -> None:
                    self.failed = False
                    self.calls: list[UUID] = []

                async def process(self, context: StageContext) -> StageOutcome:
                    self.calls.append(context.document_id)
                    if (
                        context.document_id == documents[0].document_id
                        and not self.failed
                    ):
                        self.failed = True
                        raise SharedPipelineFailure(
                            "synthetic_shared_failure", "temporary shared failure"
                        )
                    return StageOutcome(
                        output_fingerprint="sha256:" + "f" * 64,
                    )

            interrupted_stage = FailSharedOnce()
            pipeline = (
                PipelineStage("extraction", "sha256:" + "c" * 64, interrupted_stage),
            )
            with pytest.raises(IngestionExecutionError):
                await runner.run(job_id, documents, pipeline)
            interrupted = await repository.get_summary(job_id)
            assert interrupted.document_count == 2
            assert interrupted.completed_documents == 0
            assert interrupted.failed_documents == 1

            targeted = await runner.run(
                job_id,
                documents,
                pipeline,
                selected_document_ids=(documents[0].document_id,),
                retry_reason="Repair the first document after shared outage.",
            )
            assert targeted.status == "failed"
            assert targeted.documents_completed == 1
            assert (await repository.get_summary(job_id)).document_count == 2

            resumed = await runner.run(job_id, documents, pipeline)
            assert resumed.status == "completed"
            assert interrupted_stage.calls == [
                documents[0].document_id,
                documents[0].document_id,
                documents[1].document_id,
            ]
            completed = await repository.get_summary(job_id)
            assert completed.document_count == completed.completed_documents == 2

            # Cancellation retains the unvisited document in the persisted plan.
            cancelled_documents = await make_documents("cancel-stop")
            cancelled_job = await repository.create_job(
                configuration={"fixture": "cancel-stop"},
                configuration_id="sha256:" + "d" * 64,
                code_revision="integration-test",
                execution_profile="test",
            )
            started = asyncio.Event()
            cancel_task = asyncio.create_task(
                runner.run(
                    cancelled_job,
                    cancelled_documents,
                    (
                        PipelineStage(
                            "extraction",
                            "sha256:" + "e" * 64,
                            _BlockingRunnerStage(started),
                        ),
                    ),
                )
            )
            await asyncio.wait_for(started.wait(), timeout=2)
            cancel_task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await cancel_task
            cancelled_summary = await repository.get_summary(cancelled_job)
            assert cancelled_summary.status == "cancelled"
            assert cancelled_summary.document_count == 2
            after_cancel = await runner.run(
                cancelled_job,
                cancelled_documents,
                (
                    PipelineStage(
                        "extraction",
                        "sha256:" + "e" * 64,
                        _RunnerFixtureStage(),
                    ),
                ),
            )
            assert after_cancel.status == "completed"
            assert (
                await repository.get_summary(cancelled_job)
            ).completed_documents == 2

            # Expiry marks only the in-flight attempt failed; the full plan survives.
            expired_documents = await make_documents("lease-expired")
            expired_job = await repository.create_job(
                configuration={"fixture": "lease-expired"},
                configuration_id="sha256:" + "1" * 64,
                code_revision="integration-test",
                execution_profile="test",
            )
            await repository.record_plan(
                expired_job,
                tuple(
                    (document.document_id, document.input_fingerprint)
                    for document in expired_documents
                ),
                terminal_stage="extraction",
                terminal_configuration_id="sha256:" + "2" * 64,
            )
            expired_owner = await repository.claim(expired_job, lease_seconds=10)
            await repository.start_attempt(
                expired_job,
                expired_owner,
                document_id=expired_documents[0].document_id,
                stage="extraction",
                configuration_id="sha256:" + "2" * 64,
                input_fingerprint=expired_documents[0].input_fingerprint,
            )
            await pool.execute(
                "UPDATE ingestion_jobs SET lease_expires_at = now() - interval '1 second' WHERE id = $1",
                expired_job,
            )
            probe_job = await repository.create_job(
                configuration={"fixture": "lease-probe"},
                configuration_id="sha256:" + "3" * 64,
                code_revision="integration-test",
                execution_profile="test",
            )
            probe_owner = await repository.claim(probe_job, lease_seconds=10)
            reclaimed = await repository.get_summary(expired_job)
            assert reclaimed.status == "pending"
            assert reclaimed.document_count == 2
            assert reclaimed.failed_attempts == 1
            await repository.finish_job(probe_job, probe_owner, status="cancelled")
            after_expiry = await runner.run(
                expired_job,
                expired_documents,
                (
                    PipelineStage(
                        "extraction",
                        "sha256:" + "2" * 64,
                        _RunnerFixtureStage(),
                    ),
                ),
            )
            assert after_expiry.status == "completed"
            assert (await repository.get_summary(expired_job)).completed_documents == 2
        finally:
            await pool.close()

    asyncio.run(exercise())


class _BlockingRunnerStage:
    def __init__(self, started: asyncio.Event) -> None:
        self.started = started

    async def process(self, _context: StageContext) -> StageOutcome:
        self.started.set()
        await asyncio.Event().wait()
        return StageOutcome(output_fingerprint="sha256:" + "9" * 64)


def test_runner_continues_after_unsearchable_table_to_next_document() -> None:
    assert TEST_DATABASE_URL is not None

    async def exercise() -> None:
        await apply_migrations(TEST_DATABASE_URL)
        pool = await asyncpg.create_pool(TEST_DATABASE_URL, min_size=1, max_size=2)
        assert pool is not None
        repository = IngestionJobRepository(pool)
        documents: list[IngestionDocument] = []
        try:
            async with pool.acquire() as connection:
                for _ in range(2):
                    paper_id = f"table-limit-{uuid4().hex}"
                    await connection.execute(
                        "INSERT INTO papers (id, title) VALUES ($1, 'Table limit fixture')",
                        paper_id,
                    )
                    document_id = await connection.fetchval(
                        """
                        INSERT INTO documents (paper_id, source_type, version)
                        VALUES ($1, 'integration-test', 'v1') RETURNING id
                        """,
                        paper_id,
                    )
                    assert isinstance(document_id, UUID)
                    documents.append(
                        IngestionDocument(
                            document_id=document_id,
                            input_fingerprint="sha256:" + "a" * 64,
                        )
                    )
            processor = PdfEvidenceProcessor(
                None,  # type: ignore[arg-type]
                snapshot_id=uuid4(),
                artifact_root=Path("."),
                parser_config=DoclingPdfConfig(device="cpu"),
                chunking_config=ChunkingConfig(8, 0, 2),
                tokenizer=_CharacterOffsetTokenizer(),  # type: ignore[arg-type]
            )

            class TableThenGoodStage:
                def __init__(self) -> None:
                    self.calls: list[UUID] = []

                async def process(self, context: StageContext) -> StageOutcome:
                    self.calls.append(context.document_id)
                    if context.document_id == documents[0].document_id:
                        table = ExtractedTable(
                            ordinal=0,
                            caption="Oversized table caption " * 20,
                            units=None,
                            footnotes=(),
                            header_rows=1,
                            cells=(
                                TableCell(0, 0, "Header"),
                                TableCell(1, 0, "Value"),
                            ),
                        )
                        processor._chunk(
                            ExtractionResult(
                                document_id=context.document_id,
                                extraction_id=uuid5(
                                    context.document_id, "table-limit-fixture"
                                ),
                                extractor_name="synthetic",
                                extractor_revision="fixture-1",
                                configuration_id="sha256:" + "b" * 64,
                                status="completed",
                                tables=(table,),
                            )
                        )
                    return StageOutcome(output_fingerprint="sha256:" + "c" * 64)

            stage = TableThenGoodStage()
            job_id = await repository.create_job(
                configuration={"fixture": "table-limit"},
                configuration_id="sha256:" + "d" * 64,
                code_revision="integration-test",
                execution_profile="test",
            )
            report = await IngestionRunner(repository, lease_seconds=10).run(
                job_id,
                documents,
                (PipelineStage("chunking", "sha256:" + "e" * 64, stage),),
            )
            assert report.status == "failed"
            assert report.documents_completed == 1
            assert report.documents_failed == 1
            assert report.failures[0].category == "table_chunk_limit_exceeded"
            assert stage.calls == [document.document_id for document in documents]
            summary = await repository.get_summary(job_id)
            assert summary.completed_documents == 1
            assert summary.failed_documents == 1
        finally:
            await pool.close()

    asyncio.run(exercise())


def test_runner_rechunks_without_repeating_matching_extraction_checkpoint() -> None:
    assert TEST_DATABASE_URL is not None

    async def exercise() -> None:
        await apply_migrations(TEST_DATABASE_URL)
        pool = await asyncpg.create_pool(TEST_DATABASE_URL, min_size=1, max_size=2)
        assert pool is not None
        repository = IngestionJobRepository(pool)
        runner = IngestionRunner(repository, lease_seconds=10)
        documents: list[IngestionDocument] = []
        try:
            async with pool.acquire() as connection:
                for _ in range(2):
                    paper_id = f"rechunk-test-{uuid4().hex}"
                    await connection.execute(
                        "INSERT INTO papers (id, title) VALUES ($1, 'Rechunk fixture')",
                        paper_id,
                    )
                    document_id = await connection.fetchval(
                        """
                        INSERT INTO documents (paper_id, source_type, version)
                        VALUES ($1, 'integration-test', 'v1') RETURNING id
                        """,
                        paper_id,
                    )
                    assert isinstance(document_id, UUID)
                    documents.append(
                        IngestionDocument(
                            document_id=document_id,
                            input_fingerprint="sha256:" + "a" * 64,
                        )
                    )
            job_id = await repository.create_job(
                configuration={"fixture": "rechunk"},
                configuration_id="sha256:" + "b" * 64,
                code_revision="docs-only-revision-one",
                execution_profile="test",
            )
            extraction = _RunnerFixtureStage()

            class ChunkStage:
                def __init__(self, *, fail_second_once: bool = False) -> None:
                    self.calls: list[UUID] = []
                    self.fail_second_once = fail_second_once

                async def process(self, context: StageContext) -> StageOutcome:
                    self.calls.append(context.document_id)
                    if (
                        self.fail_second_once
                        and context.document_id == documents[1].document_id
                    ):
                        self.fail_second_once = False
                        raise SharedPipelineFailure(
                            "synthetic_chunk_outage", "temporary chunk worker outage"
                        )
                    digest = hashlib.sha256(
                        f"{context.stage}:{context.document_id}:"
                        f"{context.configuration_id}".encode()
                    ).hexdigest()
                    return StageOutcome(output_fingerprint=f"sha256:{digest}")

            chunking_v1 = ChunkStage(fail_second_once=True)
            original_stages = (
                PipelineStage("extraction", "sha256:" + "c" * 64, extraction),
                PipelineStage("chunking", "sha256:" + "d" * 64, chunking_v1),
            )
            with pytest.raises(IngestionExecutionError):
                await runner.run(job_id, documents, original_stages)
            assert extraction.calls == [
                documents[0].document_id,
                documents[1].document_id,
            ]

            chunking_v2 = ChunkStage()
            updated_stages = (
                PipelineStage("extraction", "sha256:" + "c" * 64, extraction),
                PipelineStage("chunking", "sha256:" + "e" * 64, chunking_v2),
            )
            targeted = await runner.run(
                job_id,
                documents,
                updated_stages,
                selected_document_ids=(documents[1].document_id,),
                from_stage="chunking",
                retry_reason="Apply the updated chunking limits.",
            )
            assert targeted.status == "failed"
            assert extraction.calls == [
                documents[0].document_id,
                documents[1].document_id,
            ]
            assert chunking_v2.calls == [documents[1].document_id]

            resumed = await runner.run(job_id, documents, updated_stages)
            assert resumed.status == "completed"
            assert extraction.calls == [
                documents[0].document_id,
                documents[1].document_id,
            ]
            assert chunking_v2.calls == [
                documents[1].document_id,
                documents[0].document_id,
            ]
            summary = await repository.get_summary(job_id)
            assert summary.completed_documents == summary.document_count == 2
        finally:
            await pool.close()

    asyncio.run(exercise())


def test_runner_cancellation_closes_attempt_and_releases_job_lease() -> None:
    assert TEST_DATABASE_URL is not None

    async def exercise() -> None:
        await apply_migrations(TEST_DATABASE_URL)
        pool = await asyncpg.create_pool(TEST_DATABASE_URL, min_size=1, max_size=2)
        assert pool is not None
        paper_id = f"cancel-test-{uuid4().hex}"
        try:
            async with pool.acquire() as connection:
                await connection.execute(
                    "INSERT INTO papers (id, title) VALUES ($1, 'Cancel test')",
                    paper_id,
                )
                document_id = await connection.fetchval(
                    """
                    INSERT INTO documents (paper_id, source_type, version)
                    VALUES ($1, 'integration-test', 'v1') RETURNING id
                    """,
                    paper_id,
                )
            assert isinstance(document_id, UUID)
            repository = IngestionJobRepository(pool)
            job_id = await repository.create_job(
                configuration={"fixture": True},
                configuration_id="sha256:" + "1" * 64,
                code_revision="integration-test",
                execution_profile="test",
            )
            started = asyncio.Event()
            runner = IngestionRunner(repository, lease_seconds=10)
            task = asyncio.create_task(
                runner.run(
                    job_id,
                    (
                        IngestionDocument(
                            document_id=document_id,
                            input_fingerprint="sha256:" + "2" * 64,
                        ),
                    ),
                    (
                        PipelineStage(
                            "extraction",
                            "sha256:" + "3" * 64,
                            _BlockingRunnerStage(started),
                        ),
                    ),
                )
            )
            await asyncio.wait_for(started.wait(), timeout=2)
            task.cancel("RESTRICTED_PAPER_PASSAGE_9f14")
            with pytest.raises(asyncio.CancelledError) as cancellation:
                await task
            assert "RESTRICTED_PAPER_PASSAGE_9f14" not in str(cancellation.value)
            summary = await repository.get_summary(job_id)
            assert summary.status == "cancelled"
            assert summary.running_attempts == 0
            assert summary.failed_attempts == 1
            attempt = await pool.fetchrow(
                """
                SELECT status, failure_category, retryable
                FROM ingestion_stage_attempts WHERE job_id = $1
                """,
                job_id,
            )
            assert attempt is not None
            assert (
                attempt["status"],
                attempt["failure_category"],
                attempt["retryable"],
            ) == (
                "failed",
                "cancelled",
                True,
            )
        finally:
            await pool.close()

    asyncio.run(exercise())


def test_draft_snapshot_evidence_inspection_is_bounded_and_permission_gated(
    tmp_path: Path,
) -> None:
    assert TEST_DATABASE_URL is not None

    async def exercise() -> None:
        await apply_migrations(TEST_DATABASE_URL)
        pool = await asyncpg.create_pool(TEST_DATABASE_URL, min_size=1, max_size=2)
        assert pool is not None
        suffix = uuid4().hex
        permitted_paper_id = f"inspection-permitted-{suffix}"
        withheld_paper_id = f"inspection-withheld-{suffix}"
        snapshot_id: UUID | None = None
        try:
            async with pool.acquire() as connection:
                await connection.executemany(
                    "INSERT INTO papers (id, title) VALUES ($1, $2)",
                    [
                        (permitted_paper_id, "Permitted inspection fixture"),
                        (withheld_paper_id, "Withheld inspection fixture"),
                    ],
                )
                permitted_document_id = await connection.fetchval(
                    """
                    INSERT INTO documents (paper_id, source_type, version, status)
                    VALUES ($1, 'integration-test', 'v1', 'acquired') RETURNING id
                    """,
                    permitted_paper_id,
                )
                withheld_document_id = await connection.fetchval(
                    """
                    INSERT INTO documents (paper_id, source_type, version, status)
                    VALUES ($1, 'integration-test', 'v1', 'acquired') RETURNING id
                    """,
                    withheld_paper_id,
                )
            assert isinstance(permitted_document_id, UUID)
            assert isinstance(withheld_document_id, UUID)

            store = ArtifactStore(
                tmp_path / "inspection-artifacts",
                maximum_file_bytes=1024,
                maximum_store_bytes=2048,
            )
            artifact = await store.store_pdf(
                _byte_chunks(b"%PDF-1.7\ninspection fixture\n%%EOF\n")
            )
            permission = PermissionEvidence(
                source_name="integration-test",
                source_url=f"https://example.org/{permitted_paper_id}.pdf",
                license_id="cc-by",
                basis="Synthetic local inspection fixture.",
                terms_url="https://creativecommons.org/licenses/by/4.0/",
                checked_at=datetime.now(timezone.utc),
                reviewer="integration-test-reviewer",
                storage_permitted=True,
                indexing_permitted=True,
                passage_display_permitted=False,
            )
            source_artifact_id = await ArtifactRepository(pool).record_download(
                permitted_document_id, artifact, permission
            )

            location = SourceLocation(page_index_zero_based=3, printed_page_label="4")
            section = ExtractedSection(
                ordinal=0,
                heading_path=("Results",),
                text="verified sample " + "x" * 2100,
                source_location=location,
            )
            second_section = ExtractedSection(
                ordinal=1,
                heading_path=("Discussion",),
                text="second selected evidence unit",
                source_location=SourceLocation(page_index_zero_based=4),
            )
            cells = (TableCell(0, 0, "Value"),) + tuple(
                TableCell(row, 0, "x" * 600 if row == 1 else f"row-{row}")
                for row in range(1, 51)
            )
            table = ExtractedTable(
                ordinal=0,
                caption="Bounded preview fixture",
                units="count",
                footnotes=("Synthetic footnote.",),
                header_rows=1,
                cells=cells,
                source_location=location,
                section_ordinal=0,
            )
            second_table = ExtractedTable(
                ordinal=1,
                caption="Second bounded preview fixture",
                units=None,
                footnotes=(),
                header_rows=0,
                cells=(TableCell(0, 0, "Second table"),),
                source_location=location,
                section_ordinal=0,
            )
            permitted_extraction_id = uuid4()
            permitted_extraction = ExtractionResult(
                document_id=permitted_document_id,
                extraction_id=permitted_extraction_id,
                extractor_name="synthetic",
                extractor_revision="inspection-test-v1",
                configuration_id="sha256:" + "a" * 64,
                status="completed",
                source_artifact_id=source_artifact_id,
                sections=(section, second_section),
                tables=(table, second_table),
                configuration={"fixture": True},
            )
            await EvidenceRepository(pool).persist(permitted_extraction, ())

            withheld_extraction_id = uuid4()
            withheld_extraction = ExtractionResult(
                document_id=withheld_document_id,
                extraction_id=withheld_extraction_id,
                extractor_name="synthetic",
                extractor_revision="inspection-test-v1",
                configuration_id="sha256:" + "b" * 64,
                status="completed",
                sections=(
                    ExtractedSection(
                        ordinal=0,
                        heading_path=("Results",),
                        text="WITHHELD_SYNTHETIC_CONTENT",
                        source_location=location,
                    ),
                ),
                configuration={"fixture": True},
            )
            await EvidenceRepository(pool).persist(withheld_extraction, ())

            repository = SnapshotRepository(pool)
            snapshot_id = await repository.create_draft(
                name=f"inspection-{suffix}",
                configuration_id="sha256:" + "c" * 64,
                configuration={"fixture": True},
                code_revision="inspection-test",
            )
            await repository.add_member(
                snapshot_id,
                paper_id=permitted_paper_id,
                document_id=permitted_document_id,
                extraction_id=permitted_extraction_id,
                selection_reason="Synthetic permitted fixture",
            )
            await repository.add_member(
                snapshot_id,
                paper_id=withheld_paper_id,
                document_id=withheld_document_id,
                extraction_id=withheld_extraction_id,
                selection_reason="Synthetic unpermitted fixture",
            )

            with pytest.raises(ValueError, match="between 1 and 100"):
                await repository.inspect_draft_evidence(snapshot_id, limit=101)
            report = await repository.inspect_draft_evidence(snapshot_id, limit=1)
            assert report["withheld_document_count"] == 1
            assert report["evidence_unit_total"] == 2
            assert report["evidence_units_truncated"] is True
            evidence_units = report["evidence_units"]
            assert isinstance(evidence_units, list)
            assert len(evidence_units) == 1
            evidence = evidence_units[0]
            assert isinstance(evidence, dict)
            assert evidence["paper_id"] == permitted_paper_id
            assert evidence["content_truncated"] is True
            assert len(evidence["content_preview"]) == 2000
            assert "WITHHELD_SYNTHETIC_CONTENT" not in str(report)

            tables = report["tables"]
            assert isinstance(tables, list)
            assert report["table_total"] == 2
            assert report["tables_truncated"] is True
            assert len(tables) == 1
            table_preview = tables[0]
            assert isinstance(table_preview, dict)
            assert table_preview["caption"] == "Bounded preview fixture"
            assert table_preview["cells_total"] == 51
            assert table_preview["cells_truncated"] is True
            assert len(table_preview["cells_preview"]) == 50
            first_data_cell = table_preview["cells_preview"][1]
            assert first_data_cell["text_truncated"] is True
            assert len(first_data_cell["text"]) == 500

            await pool.execute(
                "UPDATE snapshots SET status = 'finalized', finalized_at = now(), "
                "finalized_by = 'inspection-test' WHERE id = $1",
                snapshot_id,
            )
            with pytest.raises(ValueError, match="draft snapshot"):
                await repository.inspect_draft_evidence(snapshot_id, limit=1)
        finally:
            await pool.close()

    asyncio.run(exercise())


def test_snapshot_evidence_cli_prints_a_draft_preview(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert TEST_DATABASE_URL is not None
    assert TEST_QDRANT_URL is not None

    async def create_snapshot() -> UUID:
        await apply_migrations(TEST_DATABASE_URL)
        pool = await asyncpg.create_pool(TEST_DATABASE_URL, min_size=1, max_size=1)
        assert pool is not None
        try:
            return await SnapshotRepository(pool).create_draft(
                name=f"cli-inspection-{uuid4().hex}",
                configuration_id="sha256:" + "d" * 64,
                configuration={"fixture": True},
                code_revision="cli-inspection-test",
            )
        finally:
            await pool.close()

    snapshot_id = asyncio.run(create_snapshot())
    monkeypatch.setenv("RESEARCH_PLATFORM_DATABASE_URL", TEST_DATABASE_URL)
    monkeypatch.setenv("RESEARCH_PLATFORM_QDRANT_URL", TEST_QDRANT_URL)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "research-ingest",
            "snapshots",
            "evidence",
            "--snapshot-id",
            str(snapshot_id),
            "--limit",
            "2",
        ],
    )
    try:
        ingestion_main()
        report = json.loads(capsys.readouterr().out)
        assert report["snapshot_id"] == str(snapshot_id)
        assert report["snapshot_status"] == "draft"
        assert report["limit_per_type"] == 2
        assert report["evidence_units"] == []
        assert report["tables"] == []
    finally:

        async def remove_snapshot() -> None:
            pool = await asyncpg.create_pool(TEST_DATABASE_URL, min_size=1, max_size=1)
            assert pool is not None
            try:
                await pool.execute("DELETE FROM snapshots WHERE id = $1", snapshot_id)
            finally:
                await pool.close()

        asyncio.run(remove_snapshot())
