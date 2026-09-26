"""Terminal commands for bounded literature discovery and manifest review."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import sys
from collections.abc import Mapping
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from math import isfinite
from pathlib import Path
from typing import cast
from urllib.parse import urlsplit
from uuid import UUID

import asyncpg  # type: ignore[import-untyped]
import httpx

from research_platform.config import Settings
from research_platform.ingestion.acquisition import (
    OPENALEX_CONTENT_BASE,
    AcquisitionConfig,
    DirectSourcePdfAdapter,
    OpenAlexContentAdapter,
    OpenAlexContentAvailability,
    PermissionEvidence,
)
from research_platform.ingestion.artifact_repository import ArtifactRepository
from research_platform.ingestion.artifacts import ArtifactStore, resolve_registered_pdf
from research_platform.ingestion.citations import (
    CitationMetadataRepository,
    enrich_unresolved_citations,
)
from research_platform.ingestion.config import DiscoveryConfig
from research_platform.ingestion.discovery import run_discovery
from research_platform.ingestion.discovery_repository import (
    CoverageQuestion,
    DiscoveryRepository,
    ManifestCoverageEntry,
    ManifestCoverageReview,
    ManifestDecisionEntry,
    ManifestHeader,
    ManifestItem,
)
from research_platform.ingestion.embeddings import E5SmallV2Embedder
from research_platform.ingestion.evidence import ChunkingConfig
from research_platform.ingestion.evidence_repository import EvidenceRepository
from research_platform.ingestion.indexing import (
    IndexConfiguration,
    IndexRepository,
    QdrantIndex,
    rebuild_snapshot_index,
)
from research_platform.ingestion.manifest_report import build_manifest_review_report
from research_platform.ingestion.membership import MembershipDecision
from research_platform.ingestion.openalex import OpenAlexClient, OpenAlexWork
from research_platform.ingestion.papers import PaperRepository
from research_platform.ingestion.pdf_extraction import DoclingPdfConfig
from research_platform.ingestion.processing import PdfEvidenceProcessor
from research_platform.ingestion.provenance import code_revision
from research_platform.ingestion.reviewed_corrections import (
    ReviewedExtraction,
    create_reviewed_extraction,
)
from research_platform.ingestion.runner import (
    IngestionDocument,
    IngestionRunner,
    PipelineStage,
)
from research_platform.ingestion.snapshots import SnapshotRepository
from research_platform.ingestion.source_content_review import SourceContentReview
from research_platform.ingestion.stage_repository import IngestionJobRepository
from research_platform.persistence.migrations import apply_migrations

_COVERAGE_QUESTIONS: tuple[tuple[CoverageQuestion, str], ...] = (
    ("hybrid_dense", "When does hybrid retrieval outperform dense-only retrieval?"),
    (
        "reranking_latency",
        "How much does cross-encoder reranking improve retrieval quality, and at what latency cost?",
    ),
    (
        "chunking_citation",
        "How do chunking choices affect evidence retrieval and citation support?",
    ),
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="research-ingest")
    commands = parser.add_subparsers(dest="command", required=True)

    discovery = commands.add_parser("discover", help="run or resume OpenAlex discovery")
    discovery.add_argument("--config", type=Path, required=True)
    discovery.add_argument("--resume", type=UUID)

    manifest = commands.add_parser("manifest", help="prepare and review a shortlist")
    manifest_commands = manifest.add_subparsers(dest="manifest_command", required=True)

    prepare = manifest_commands.add_parser("prepare", help="create a draft shortlist")
    prepare.add_argument("--run-id", type=UUID, required=True)
    prepare.add_argument("--version", type=int, required=True)
    prepare.add_argument("--per-query-limit", type=int, default=50)

    export = manifest_commands.add_parser(
        "export", help="export a reviewable JSON file"
    )
    export.add_argument("--manifest-id", type=UUID, required=True)
    export.add_argument("--output", type=Path, required=True)
    export.add_argument("--overwrite", action="store_true")

    report_manifest = manifest_commands.add_parser(
        "report", help="summarize reviewer yield, coverage and shortlist limits"
    )
    report_manifest.add_argument("--manifest-id", type=UUID, required=True)
    report_manifest.add_argument("--output", type=Path, required=True)
    report_manifest.add_argument("--overwrite", action="store_true")

    import_review = manifest_commands.add_parser(
        "import", help="save decisions and coverage notes from a reviewed JSON file"
    )
    import_review.add_argument("--manifest-id", type=UUID, required=True)
    import_review.add_argument("--input", type=Path, required=True)

    approve = manifest_commands.add_parser(
        "approve", help="approve the complete human-reviewed manifest"
    )
    approve.add_argument("--manifest-id", type=UUID, required=True)
    approve.add_argument("--reviewer", required=True)

    membership = commands.add_parser(
        "membership", help="import an explicitly approved 100-paper selection"
    )
    membership_commands = membership.add_subparsers(
        dest="membership_command", required=True
    )
    import_membership = membership_commands.add_parser(
        "import", help="refresh OpenAlex metadata and persist selected paper identities"
    )
    import_membership.add_argument("--decision", type=Path, required=True)
    import_membership.add_argument("--config", type=Path, required=True)
    import_membership.add_argument(
        "--metadata-cache",
        type=Path,
        default=Path("local-reference/phase1-100/openalex-metadata.json"),
    )
    import_membership.add_argument(
        "--document-map",
        type=Path,
        default=Path("local-reference/phase1-100/selected-document-ids.json"),
    )
    import_membership.add_argument(
        "--source-route-review",
        type=Path,
        default=Path("local-reference/phase1-100/source-route-review.json"),
    )
    acquire_membership = membership_commands.add_parser(
        "acquire", help="download reviewed 100-paper PDFs within free and local caps"
    )
    acquire_membership.add_argument("--decision", type=Path, required=True)
    acquire_membership.add_argument("--document-map", type=Path, required=True)
    acquire_membership.add_argument("--source-route-review", type=Path, required=True)
    acquire_membership.add_argument(
        "--metadata-cache",
        type=Path,
        default=Path("local-reference/phase1-100/openalex-metadata.json"),
    )
    acquire_membership.add_argument(
        "--artifact-root", type=Path, default=Path("data/artifacts")
    )

    snapshots = commands.add_parser(
        "snapshots", help="manage draft and finalized evidence snapshots"
    )
    snapshot_commands = snapshots.add_subparsers(dest="snapshot_command", required=True)
    create_snapshot = snapshot_commands.add_parser(
        "create", help="create a draft from versioned configuration JSON"
    )
    create_snapshot.add_argument("--name", required=True)
    create_snapshot.add_argument("--configuration", type=Path, required=True)

    inspect_snapshot = snapshot_commands.add_parser(
        "inspect", help="list member versions, stage outcomes and rights"
    )
    inspect_snapshot.add_argument("--snapshot-id", type=UUID, required=True)

    inspect_evidence = snapshot_commands.add_parser(
        "evidence", help="show a bounded preview of evidence in a draft snapshot"
    )
    inspect_evidence.add_argument("--snapshot-id", type=UUID, required=True)
    inspect_evidence.add_argument("--limit", type=int, default=20)

    add_snapshot_item = snapshot_commands.add_parser(
        "add", help="add one paper/document/extraction to a draft"
    )
    add_snapshot_item.add_argument("--snapshot-id", type=UUID, required=True)
    add_snapshot_item.add_argument("--paper-id", required=True)
    add_snapshot_item.add_argument("--document-id", type=UUID, required=True)
    add_snapshot_item.add_argument("--extraction-id", type=UUID)
    add_snapshot_item.add_argument("--selection-reason", required=True)

    add_reviewed_membership = snapshot_commands.add_parser(
        "add-membership",
        help="add the exact assistant-approved 100-paper selection to a bound draft",
    )
    add_reviewed_membership.add_argument("--snapshot-id", type=UUID, required=True)
    add_reviewed_membership.add_argument("--decision", type=Path, required=True)
    add_reviewed_membership.add_argument("--document-map", type=Path, required=True)

    remove_snapshot_item = snapshot_commands.add_parser(
        "remove", help="remove one paper from a draft"
    )
    remove_snapshot_item.add_argument("--snapshot-id", type=UUID, required=True)
    remove_snapshot_item.add_argument("--paper-id", required=True)

    validate_snapshot = snapshot_commands.add_parser(
        "validate", help="check evidence, rights and Qdrant reconciliation"
    )
    validate_snapshot.add_argument("--snapshot-id", type=UUID, required=True)
    validate_snapshot.add_argument("--minimum-papers", type=int, default=100)

    finalize_snapshot = snapshot_commands.add_parser(
        "finalize", help="validate and freeze a snapshot"
    )
    finalize_snapshot.add_argument("--snapshot-id", type=UUID, required=True)
    finalize_snapshot.add_argument("--reviewer", required=True)
    finalize_snapshot.add_argument("--minimum-papers", type=int, default=100)

    review_table = snapshot_commands.add_parser(
        "review-table", help="record review of a flagged table against its PDF"
    )
    review_table.add_argument("--snapshot-id", type=UUID, required=True)
    review_table.add_argument("--extraction-id", type=UUID, required=True)
    review_table.add_argument("--table-ordinal", type=int, required=True)
    review_table.add_argument("--reviewer", required=True)

    apply_corrections = snapshot_commands.add_parser(
        "apply-corrections",
        help="store reviewed corrections as new source-linked extraction versions",
    )
    apply_corrections.add_argument("--snapshot-id", type=UUID, required=True)
    apply_corrections.add_argument("--corrections", type=Path, required=True)

    index_commands = commands.add_parser(
        "index", help="inspect a snapshot's rebuildable Qdrant index"
    )
    index_subcommands = index_commands.add_subparsers(
        dest="index_command", required=True
    )
    inspect_index = index_subcommands.add_parser(
        "inspect", help="show point counts and a sample of stored evidence IDs"
    )
    inspect_index.add_argument("--snapshot-id", type=UUID, required=True)
    inspect_index.add_argument("--configuration", type=Path, required=True)

    rebuild_index = index_subcommands.add_parser(
        "rebuild", help="embed permitted snapshot evidence and reconcile Qdrant"
    )
    rebuild_index.add_argument("--snapshot-id", type=UUID, required=True)
    rebuild_index.add_argument("--configuration", type=Path, required=True)
    rebuild_index.add_argument(
        "--device", choices=("auto", "cpu", "cuda"), default="auto"
    )

    query_index = index_subcommands.add_parser(
        "query", help="search one snapshot with its configured local embedding model"
    )
    query_index.add_argument("--snapshot-id", type=UUID, required=True)
    query_index.add_argument("--configuration", type=Path, required=True)
    query_index.add_argument("--query", required=True)
    query_index.add_argument("--limit", type=int, default=10)
    query_index.add_argument(
        "--device", choices=("auto", "cpu", "cuda"), default="auto"
    )

    jobs = commands.add_parser("jobs", help="run and inspect ingestion jobs")
    job_commands = jobs.add_subparsers(dest="job_command", required=True)
    job_start = job_commands.add_parser(
        "start", help="create and run extraction/chunking for a draft snapshot"
    )
    job_start.add_argument("--snapshot-id", type=UUID, required=True)
    job_start.add_argument("--chunking-configuration", type=Path, required=True)
    job_start.add_argument("--artifact-root", type=Path, default=Path("data/artifacts"))
    job_start.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    job_start.add_argument(
        "--membership-decision",
        type=Path,
        help="required for a 100-paper job; binds it to the approved membership record",
    )
    job_start.add_argument(
        "--source-route-review",
        type=Path,
        default=Path("local-reference/phase1-100/source-route-review.json"),
        help="verified canonical source routes and license evidence for the 100-paper job",
    )
    job_start.add_argument(
        "--source-content-review",
        type=Path,
        default=Path("local-reference/phase1-100/source-content-review.json"),
        help="checksum-bound page exclusions for reviewed third-party source content",
    )

    job_resume = job_commands.add_parser(
        "resume", help="resume completed checkpoints in a pending or failed job"
    )
    job_resume.add_argument("--job-id", type=UUID, required=True)
    job_resume.add_argument(
        "--artifact-root", type=Path, default=Path("data/artifacts")
    )
    job_resume.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")

    job_retry = job_commands.add_parser(
        "retry", help="retry one document from a named stage"
    )
    job_retry.add_argument("--job-id", type=UUID, required=True)
    job_retry.add_argument("--document-id", type=UUID, required=True)
    job_retry.add_argument("--from-stage", choices=("extraction",), required=True)
    job_retry.add_argument("--reason", required=True)
    job_retry.add_argument("--artifact-root", type=Path, default=Path("data/artifacts"))
    job_retry.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")

    job_status = job_commands.add_parser("status", help="show checkpoint counts")
    job_status.add_argument("--job-id", type=UUID, required=True)

    storage = commands.add_parser("storage", help="inspect artifact storage")
    storage_commands = storage.add_subparsers(dest="storage_command", required=True)
    for storage_command, help_text in (
        ("inspect", "show byte limits and local disk capacity"),
        ("cleanup-preview", "list old unreferenced artifacts without deleting them"),
        ("cleanup", "preview or explicitly remove old unreferenced artifacts"),
    ):
        storage_parser = storage_commands.add_parser(storage_command, help=help_text)
        storage_parser.add_argument("--root", type=Path, default=Path("data/artifacts"))
        storage_parser.add_argument(
            "--maximum-file-bytes",
            type=int,
            default=AcquisitionConfig().maximum_file_bytes,
        )
        storage_parser.add_argument(
            "--maximum-store-bytes",
            type=int,
            default=AcquisitionConfig().maximum_store_bytes,
        )
        if storage_command in {"cleanup-preview", "cleanup"}:
            storage_parser.add_argument(
                "--older-than-hours",
                type=int,
                default=168 if storage_command == "cleanup-preview" else None,
                required=storage_command == "cleanup",
            )
            storage_parser.add_argument("--limit", type=int, default=100)
        if storage_command == "cleanup":
            storage_parser.add_argument(
                "--apply", action="store_true", help="perform the listed cleanup"
            )

    citations = commands.add_parser(
        "citations", help="enrich unresolved external citation identifiers"
    )
    citation_commands = citations.add_subparsers(dest="citation_command", required=True)
    enrich = citation_commands.add_parser(
        "enrich", help="fetch bounded metadata for unresolved OpenAlex works"
    )
    enrich.add_argument("--config", type=Path, required=True)
    enrich.add_argument("--limit", type=int)

    return parser


def _load_local_environment() -> None:
    """Load simple KEY=value entries from .env without replacing shell values."""
    environment_file = Path.cwd() / ".env"
    if not environment_file.is_file():
        return
    for line in environment_file.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, value = stripped.split("=", maxsplit=1)
        name = name.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if name:
            os.environ.setdefault(name, value)


def _load_discovery_config(path: Path) -> DiscoveryConfig:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, Mapping):
        raise ValueError("discovery config file must contain a JSON object")
    return DiscoveryConfig.from_dict(cast(Mapping[str, object], raw))


def _abstract_text(metadata: Mapping[str, object]) -> str | None:
    inverted_index = metadata.get("abstract_inverted_index")
    if not isinstance(inverted_index, Mapping):
        return None
    words: dict[int, str] = {}
    for word, positions in inverted_index.items():
        if not isinstance(word, str) or not isinstance(positions, list):
            continue
        for position in positions:
            if (
                isinstance(position, int)
                and not isinstance(position, bool)
                and position >= 0
            ):
                words[position] = word
    if not words:
        return None
    return " ".join(words[position] for position in sorted(words))


def _review_manifest_payload(
    manifest_header: ManifestHeader,
    manifest_items: tuple[ManifestItem, ...],
    manifest_coverage: tuple[ManifestCoverageReview, ...],
) -> dict[str, object]:
    exported_items: list[dict[str, object]] = []
    for item in manifest_items:
        metadata = item.metadata
        exported_items.append(
            {
                "openalex_id": item.openalex_id,
                "title": item.title,
                "publication_year": item.publication_year,
                "language": item.language,
                "work_type": item.work_type,
                "doi": metadata.get("doi"),
                "cited_by_count": metadata.get("cited_by_count"),
                "abstract": _abstract_text(metadata),
                "primary_location": metadata.get("primary_location"),
                "authorships": metadata.get("authorships"),
                "referenced_works": metadata.get("referenced_works"),
                "selection_signals": dict(item.selection_signals),
                "query_origins": [dict(origin) for origin in item.origins],
                "decision": item.decision,
                "reason": item.reason,
                "coverage_questions": list(item.coverage_questions),
            }
        )
    return {
        "schema_version": 1,
        "manifest_id": str(manifest_header.id),
        "discovery_run_id": str(manifest_header.run_id),
        "version": manifest_header.version,
        "status": manifest_header.status,
        "discovery_configuration_id": manifest_header.configuration_id,
        "code_revision": manifest_header.code_revision,
        "review_instructions": (
            "For each candidate, choose include or exclude and give a specific reason. "
            "Assign any applicable coverage question keys. Review each of the three "
            "coverage questions as covered or gap and add a note. Do not edit metadata."
        ),
        "coverage_question_definitions": [
            {"key": key, "question": question} for key, question in _COVERAGE_QUESTIONS
        ],
        "coverage_reviews": [
            {
                "question_key": item.question,
                "status": item.status,
                "reviewer_note": item.reviewer_note,
            }
            for item in manifest_coverage
        ]
        or [
            {"question_key": key, "status": "needs_review", "reviewer_note": ""}
            for key, _question in _COVERAGE_QUESTIONS
        ],
        "items": exported_items,
    }


async def _execute(args: argparse.Namespace) -> None:
    if args.command == "storage" and args.storage_command == "inspect":
        await _execute_storage_inspect(args)
        return
    if args.command == "index" and args.index_command == "inspect":
        await _execute_index_inspect(args, Settings())
        return
    settings = Settings()
    await apply_migrations(settings.database_url)
    pool = await asyncpg.create_pool(settings.database_url, min_size=1, max_size=2)
    if pool is None:
        raise RuntimeError("could not create a PostgreSQL connection pool")
    try:
        repository = DiscoveryRepository(pool)
        if args.command == "discover":
            await _execute_discovery(args, settings, repository)
        elif args.command == "membership":
            if args.membership_command == "import":
                await _execute_membership_import(args, settings, pool)
            elif args.membership_command == "acquire":
                await _execute_membership_acquisition(args, settings, pool)
        elif args.command == "manifest":
            await _execute_manifest(args, repository)
        elif args.command == "citations":
            await _execute_citation_enrichment(args, settings, pool)
        elif (
            args.command == "snapshots" and args.snapshot_command == "apply-corrections"
        ):
            await _execute_reviewed_corrections(args, pool)
        elif args.command == "snapshots":
            await _execute_snapshots(args, SnapshotRepository(pool))
        elif args.command == "jobs":
            await _execute_jobs(args, settings, pool)
        elif args.command == "index":
            await _execute_index_operation(args, settings, pool)
        elif args.command == "storage" and args.storage_command == "cleanup":
            await _execute_storage_cleanup(args, ArtifactRepository(pool))
        elif args.command == "storage":
            await _execute_cleanup_preview(args, ArtifactRepository(pool))
    finally:
        await pool.close()


async def _execute_index_inspect(args: argparse.Namespace, settings: Settings) -> None:
    configuration = _load_index_configuration(args.configuration)
    async with httpx.AsyncClient(
        base_url=settings.qdrant_url.rstrip("/"), timeout=5
    ) as http:
        index = QdrantIndex(configuration, http)
        if await index.collection_exists():
            await index.ensure_collection()
            count = await index.count_snapshot(args.snapshot_id)
            evidence_ids = await index.scroll_snapshot_ids(
                args.snapshot_id, page_size=100
            )
        else:
            count = 0
            evidence_ids = ()
    if len(evidence_ids) != count:
        raise RuntimeError(
            f"Qdrant exact count is {count}, but scroll returned {len(evidence_ids)} IDs"
        )
    print(
        json.dumps(
            {
                "snapshot_id": str(args.snapshot_id),
                "configuration_id": configuration.configuration_id,
                "collection_name": configuration.collection_name,
                "point_count": count,
                "evidence_ids_sample": list(evidence_ids[:20]),
            },
            indent=2,
        )
    )


def _load_index_configuration(path: Path) -> IndexConfiguration:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return IndexConfiguration.from_dict(_mapping(raw, "index configuration"))


def _load_chunking_configuration(path: Path) -> ChunkingConfig:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return ChunkingConfig.from_dict(_mapping(raw, "chunking configuration"))


async def _execute_index_operation(
    args: argparse.Namespace,
    settings: Settings,
    pool: asyncpg.Pool,
) -> None:
    configuration = _load_index_configuration(args.configuration)
    embedder = E5SmallV2Embedder(device=args.device)
    async with httpx.AsyncClient(
        base_url=settings.qdrant_url.rstrip("/"), timeout=30
    ) as http:
        index = QdrantIndex(configuration, http)
        if args.index_command == "rebuild":
            report = await rebuild_snapshot_index(
                IndexRepository(pool), index, embedder, args.snapshot_id
            )
            print(json.dumps(asdict(report), indent=2, default=str))
            return
        if args.index_command == "query":
            if args.limit <= 0:
                raise ValueError("query limit must be positive")
            query_vector = await embedder.embed_query(
                args.query, configuration=configuration
            )
            matches = await index.query_snapshot(
                query_vector, args.snapshot_id, limit=args.limit
            )
            print(
                json.dumps(
                    {
                        "snapshot_id": str(args.snapshot_id),
                        "configuration_id": configuration.configuration_id,
                        "matches": [asdict(match) for match in matches],
                    },
                    indent=2,
                    default=str,
                )
            )
            return
        raise ValueError("unsupported index operation")


async def _execute_jobs(
    args: argparse.Namespace,
    settings: Settings,
    pool: asyncpg.Pool,
) -> None:
    del settings  # the extraction stage uses local files and persisted records only
    jobs = IngestionJobRepository(pool)
    snapshots = SnapshotRepository(pool)
    artifacts = ArtifactRepository(pool)
    if args.job_command == "status":
        await _execute_job_status(args, jobs)
        return

    if args.job_command == "start":
        snapshot_id = args.snapshot_id
        chunking = _load_chunking_configuration(args.chunking_configuration)
        document_ids = await snapshots.document_ids_for_processing(snapshot_id)
        snapshot_configuration = await snapshots.configuration_for(snapshot_id)
        membership_digest: str | None = None
        membership: MembershipDecision | None = None
        document_ids_by_paper: dict[str, UUID] = {}
        execution_profile = "10-paper-comparison"
        if len(document_ids) > 10:
            if len(document_ids) != 100 or args.membership_decision is None:
                raise ValueError(
                    "a 100-paper job requires exactly 100 snapshot members and "
                    "--membership-decision"
                )
            membership = MembershipDecision.load(
                args.membership_decision
            ).with_source_route_review(args.source_route_review)
            if (
                snapshot_configuration.get("membership_decision_sha256")
                != membership.identity
                or snapshot_configuration.get("membership_target_count") != 100
            ):
                raise ValueError(
                    "snapshot configuration is not bound to this 100-paper decision"
                )
            members = await snapshots.inspect_members(snapshot_id)
            document_ids_by_paper = {
                member.paper_id: member.document_id for member in members
            }
            if {member.paper_id for member in members} != set(
                membership.selected_openalex_ids
            ):
                raise ValueError(
                    "snapshot membership does not match the approved 100-paper decision"
                )
            membership_digest = membership.identity
            execution_profile = "100-paper-pilot"
        elif args.membership_decision is not None:
            raise ValueError(
                "--membership-decision is reserved for an exact 100-paper pilot"
            )
        document_inputs: list[dict[str, str]] = []
        documents: list[IngestionDocument] = []
        input_fingerprints_by_document: dict[UUID, str] = {}
        for document_id in document_ids:
            artifact = await artifacts.permitted_source_pdf(
                document_id, require_indexing=True
            )
            await asyncio.to_thread(
                resolve_registered_pdf,
                args.artifact_root,
                artifact.storage_path,
                sha256=artifact.sha256,
                byte_size=artifact.byte_size,
            )
            fingerprint = "sha256:" + artifact.sha256
            document_inputs.append(
                {"document_id": str(document_id), "input_fingerprint": fingerprint}
            )
            input_fingerprints_by_document[document_id] = fingerprint
            documents.append(IngestionDocument(document_id, fingerprint))
        source_review: SourceContentReview | None = None
        if membership is not None:
            source_review = SourceContentReview.load(
                args.source_content_review,
                membership_decision_id=membership.identity,
                source_route_review_id=cast(
                    str, membership.source_route_review_identity
                ),
                document_ids_by_paper=document_ids_by_paper,
                input_fingerprints_by_document=input_fingerprints_by_document,
            )
        excluded_source_pages = (
            source_review.excluded_source_pages_by_document if source_review else {}
        )
        source_review_identity = source_review.identity if source_review else None
        processor = PdfEvidenceProcessor(
            pool,
            snapshot_id=snapshot_id,
            artifact_root=args.artifact_root,
            parser_config=DoclingPdfConfig(),
            chunking_config=chunking,
            tokenizer=E5SmallV2Embedder(device=args.device),
            excluded_source_pages_by_document=excluded_source_pages,
            source_content_review_identity=source_review_identity,
        )
        prepared = await processor.prepare()
        configuration: dict[str, object] = {
            "schema_version": 1,
            "operation": "pdf_extraction_and_chunking",
            "snapshot_id": str(snapshot_id),
            "document_inputs": document_inputs,
            "parser_configuration": DoclingPdfConfig().to_dict(),
            "chunking_configuration": chunking.to_dict(),
            "pipeline_configuration_id": prepared.configuration_id,
            "execution_profile": execution_profile,
            "membership_decision_sha256": membership_digest,
            "source_content_review_sha256": source_review_identity,
            "excluded_source_pages_by_document": {
                str(document_id): sorted(page_numbers)
                for document_id, page_numbers in excluded_source_pages.items()
            },
        }
        job_configuration_id = _configuration_identity(configuration)
        job_id = await jobs.create_job(
            configuration=configuration,
            configuration_id=job_configuration_id,
            code_revision=code_revision(),
            execution_profile=execution_profile,
        )
        print(json.dumps({"job_id": str(job_id), "status": "pending"}), flush=True)
        await _run_pdf_job(
            args,
            jobs,
            processor,
            prepared.configuration_id,
            job_id,
            documents,
        )
        return

    if args.job_command not in {"resume", "retry"}:
        raise ValueError("unsupported job operation")
    job_id = args.job_id
    job_configuration = await jobs.get_configuration(job_id)
    if (
        job_configuration.get("schema_version") != 1
        or job_configuration.get("operation") != "pdf_extraction_and_chunking"
    ):
        raise ValueError("job does not contain a supported PDF-processing plan")
    snapshot_id = _required_uuid(job_configuration.get("snapshot_id"), "snapshot_id")
    stored_inputs = job_configuration.get("document_inputs")
    stored_execution_profile = job_configuration.get("execution_profile")
    stored_membership_digest = job_configuration.get("membership_decision_sha256")
    if not isinstance(stored_inputs, list) or not stored_inputs:
        raise ValueError("job document inputs are missing")
    if stored_execution_profile == "10-paper-comparison":
        if len(stored_inputs) > 10 or stored_membership_digest is not None:
            raise ValueError("10-paper job configuration exceeds its approved profile")
    elif stored_execution_profile == "100-paper-pilot":
        if len(stored_inputs) != 100 or not isinstance(stored_membership_digest, str):
            raise ValueError("100-paper job configuration is incomplete")
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", stored_membership_digest):
            raise ValueError("100-paper membership decision identity is invalid")
        snapshot_configuration = await snapshots.configuration_for(snapshot_id)
        if (
            snapshot_configuration.get("membership_decision_sha256")
            != stored_membership_digest
            or snapshot_configuration.get("membership_target_count") != 100
        ):
            raise ValueError("snapshot no longer matches the 100-paper job decision")
    else:
        raise ValueError("job execution profile is unsupported")
    expected_documents: list[IngestionDocument] = []
    for item in stored_inputs:
        raw_item = _mapping(item, "job document input")
        document_id = _required_uuid(raw_item.get("document_id"), "document_id")
        input_fingerprint = raw_item.get("input_fingerprint")
        if not isinstance(input_fingerprint, str):
            raise ValueError("job input fingerprint is invalid")
        expected_documents.append(IngestionDocument(document_id, input_fingerprint))
    current_document_ids = await snapshots.document_ids_for_processing(snapshot_id)
    if set(current_document_ids) != {item.document_id for item in expected_documents}:
        raise ValueError("draft snapshot membership changed; create a new job")
    for document in expected_documents:
        artifact = await artifacts.permitted_source_pdf(
            document.document_id, require_indexing=True
        )
        if document.input_fingerprint != "sha256:" + artifact.sha256:
            raise ValueError("job source artifact changed; create a new job")
        await asyncio.to_thread(
            resolve_registered_pdf,
            args.artifact_root,
            artifact.storage_path,
            sha256=artifact.sha256,
            byte_size=artifact.byte_size,
        )
    raw_source_review_identity = job_configuration.get("source_content_review_sha256")
    if raw_source_review_identity is not None and not isinstance(
        raw_source_review_identity, str
    ):
        raise ValueError("job source content review identity is invalid")
    source_review_identity = raw_source_review_identity
    raw_source_page_exclusions = job_configuration.get(
        "excluded_source_pages_by_document", {}
    )
    excluded_source_pages = _load_job_source_page_exclusions(
        raw_source_page_exclusions,
        source_review_identity,
        expected_documents,
        stored_execution_profile,
    )
    raw_chunking = job_configuration.get("chunking_configuration")
    chunking = ChunkingConfig.from_dict(
        _mapping(raw_chunking, "chunking configuration")
    )
    raw_parser = _mapping(
        job_configuration.get("parser_configuration"), "parser configuration"
    )
    if raw_parser != DoclingPdfConfig().to_dict():
        raise ValueError("job parser configuration is not supported by this CLI")
    processor = PdfEvidenceProcessor(
        pool,
        snapshot_id=snapshot_id,
        artifact_root=args.artifact_root,
        parser_config=DoclingPdfConfig(),
        chunking_config=chunking,
        tokenizer=E5SmallV2Embedder(device=args.device),
        excluded_source_pages_by_document=excluded_source_pages,
        source_content_review_identity=source_review_identity,
    )
    prepared = await processor.prepare()
    expected_pipeline_id = job_configuration.get("pipeline_configuration_id")
    if expected_pipeline_id != prepared.configuration_id:
        raise ValueError("effective parser or tokenizer changed; create a new job")
    if args.job_command == "resume":
        await _run_pdf_job(
            args,
            jobs,
            processor,
            prepared.configuration_id,
            job_id,
            expected_documents,
        )
        return
    await _run_pdf_job(
        args,
        jobs,
        processor,
        prepared.configuration_id,
        job_id,
        expected_documents,
        selected_document_ids=(args.document_id,),
        from_stage=args.from_stage,
        retry_reason=args.reason,
    )


async def _run_pdf_job(
    args: argparse.Namespace,
    repository: IngestionJobRepository,
    processor: PdfEvidenceProcessor,
    configuration_id: str,
    job_id: UUID,
    documents: list[IngestionDocument],
    *,
    selected_document_ids: tuple[UUID, ...] | None = None,
    from_stage: str | None = None,
    retry_reason: str | None = None,
) -> None:
    stage = PipelineStage(
        name="extraction",
        configuration_id=configuration_id,
        processor=processor,
    )
    report = await IngestionRunner(repository).run(
        job_id,
        documents,
        (stage,),
        selected_document_ids=selected_document_ids,
        from_stage=from_stage,
        retry_reason=retry_reason,
    )
    print(json.dumps(asdict(report), indent=2, default=str))


def _configuration_identity(configuration: Mapping[str, object]) -> str:
    canonical = json.dumps(
        dict(configuration), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _load_job_source_page_exclusions(
    value: object,
    review_identity: object,
    documents: list[IngestionDocument],
    execution_profile: object,
) -> dict[UUID, frozenset[int]]:
    if not isinstance(value, Mapping):
        raise ValueError("job source-page exclusions must be a JSON object")
    if execution_profile == "10-paper-comparison":
        if value or review_identity is not None:
            raise ValueError("10-paper jobs cannot carry source-page exclusions")
        return {}
    if execution_profile != "100-paper-pilot":
        raise ValueError("source-page exclusions have an unsupported job profile")
    if (
        not isinstance(review_identity, str)
        or not re.fullmatch(r"sha256:[0-9a-f]{64}", review_identity)
        or len(documents) != 100
    ):
        raise ValueError("100-paper source content review binding is incomplete")
    known_document_ids = {document.document_id for document in documents}
    exclusions: dict[UUID, frozenset[int]] = {}
    for raw_document_id, raw_pages in value.items():
        try:
            document_id = UUID(str(raw_document_id))
        except (ValueError, TypeError) as error:
            raise ValueError(
                "job source-page exclusion has an invalid document ID"
            ) from error
        if document_id not in known_document_ids or not isinstance(raw_pages, list):
            raise ValueError("job source-page exclusion names an unknown document")
        if any(
            isinstance(page, bool) or not isinstance(page, int) or page < 1
            for page in raw_pages
        ):
            raise ValueError("job source-page exclusion has invalid page numbers")
        if raw_pages != list(range(21, 36)):
            raise ValueError("job source-page exclusion is not the reviewed page set")
        exclusions[document_id] = frozenset(raw_pages)
    if len(exclusions) != 1:
        raise ValueError("100-paper job requires the reviewed source-page exclusion")
    return exclusions


def _load_selected_document_ids(
    path: Path, membership: MembershipDecision
) -> dict[str, UUID]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("selected document map cannot be read") from error
    data = _mapping(payload, "selected document map")
    if data.get("schema_version") != 1 or isinstance(data.get("schema_version"), bool):
        raise ValueError("unsupported selected document map schema")
    if data.get("membership_decision_id") != membership.identity:
        raise ValueError("selected document map belongs to another membership decision")
    raw_ids = _mapping(data.get("selected_document_ids"), "selected_document_ids")
    if set(raw_ids) != set(membership.selected_openalex_ids):
        raise ValueError("selected document map does not cover the approved membership")
    return {
        openalex_id: _required_uuid(raw_document_id, "document_id")
        for openalex_id, raw_document_id in raw_ids.items()
    }


def _required_uuid(value: object, name: str) -> UUID:
    if not isinstance(value, str):
        raise ValueError(f"job {name} is invalid")
    try:
        return UUID(value)
    except ValueError:
        raise ValueError(f"{name} must be a valid UUID") from None


async def _execute_storage_inspect(args: argparse.Namespace) -> None:
    store = ArtifactStore(
        args.root,
        maximum_file_bytes=args.maximum_file_bytes,
        maximum_store_bytes=args.maximum_store_bytes,
    )
    print(json.dumps(asdict(store.inspect()), indent=2))


async def _execute_cleanup_preview(
    args: argparse.Namespace, repository: ArtifactRepository
) -> None:
    if args.older_than_hours <= 0 or args.limit <= 0:
        raise ValueError("cleanup preview age and limit must be positive")
    store = ArtifactStore(
        args.root,
        maximum_file_bytes=args.maximum_file_bytes,
        maximum_store_bytes=args.maximum_store_bytes,
    )
    created_before = datetime.now(timezone.utc) - timedelta(hours=args.older_than_hours)
    candidates = await repository.preview_unreferenced(
        created_before=created_before, limit=args.limit
    )
    unknown_files = store.unregistered_files(await repository.known_storage_paths())
    partial_files = store.stale_partial_files(created_before=created_before)
    print(
        json.dumps(
            {
                "created_before": created_before.isoformat(),
                "unreferenced_database_artifacts": [
                    asdict(item) for item in candidates
                ],
                "unregistered_local_files": list(unknown_files),
                "stale_partial_files": [asdict(item) for item in partial_files],
                "deleted": False,
            },
            indent=2,
            default=str,
        )
    )


async def _execute_storage_cleanup(
    args: argparse.Namespace, repository: ArtifactRepository
) -> None:
    if args.older_than_hours <= 0 or args.limit <= 0:
        raise ValueError("cleanup age and limit must be positive")
    store = ArtifactStore(
        args.root,
        maximum_file_bytes=args.maximum_file_bytes,
        maximum_store_bytes=args.maximum_store_bytes,
    )
    created_before = datetime.now(timezone.utc) - timedelta(hours=args.older_than_hours)
    if args.apply:
        report = await repository.cleanup_unreferenced(
            store, created_before=created_before, limit=args.limit
        )
        print(
            json.dumps(
                {
                    "mode": "applied",
                    "created_before": created_before.isoformat(),
                    **asdict(report),
                },
                indent=2,
            )
        )
        return

    candidates = await repository.preview_unreferenced(
        created_before=created_before, limit=args.limit
    )
    known_paths = await repository.known_storage_paths()
    unregistered = store.stale_unregistered_files(
        known_paths, created_before=created_before
    )[: args.limit]
    partials = store.stale_partial_files(created_before=created_before)[: args.limit]
    print(
        json.dumps(
            {
                "mode": "preview",
                "created_before": created_before.isoformat(),
                "database_artifacts": [asdict(item) for item in candidates],
                "unregistered_files": [asdict(item) for item in unregistered],
                "partial_files": [asdict(item) for item in partials],
                "deleted": False,
            },
            indent=2,
            default=str,
        )
    )


async def _execute_reviewed_corrections(
    args: argparse.Namespace, pool: asyncpg.Pool
) -> None:
    correction_bytes = args.corrections.read_bytes()
    payload = _mapping(json.loads(correction_bytes), "correction manifest")
    if set(payload) != {"schema_version", "reviewer", "extractions"}:
        raise ValueError("correction manifest fields are incomplete or unknown")
    if payload["schema_version"] != 1 or isinstance(payload["schema_version"], bool):
        raise ValueError("unsupported correction manifest schema version")
    reviewer = payload["reviewer"]
    if not isinstance(reviewer, str) or not reviewer.strip():
        raise ValueError("correction reviewer must be a non-empty string")
    raw_cases = payload["extractions"]
    if not isinstance(raw_cases, list) or not raw_cases:
        raise ValueError("correction manifest must contain extraction corrections")

    snapshot_repository = SnapshotRepository(pool)
    members = await snapshot_repository.draft_member_extractions(args.snapshot_id)
    correction_hash = hashlib.sha256(correction_bytes).hexdigest()
    embedder = E5SmallV2Embedder(device="cpu")
    try:
        await asyncio.to_thread(embedder.token_spans, "")
    except RuntimeError as error:
        raise ValueError(
            "the pinned local E5 tokenizer is required to rebuild corrected chunks"
        ) from error

    prepared: list[tuple[UUID, UUID, ReviewedExtraction]] = []
    seen_extractions: set[UUID] = set()
    evidence_repository = EvidenceRepository(pool)
    for raw_case in raw_cases:
        case = _mapping(raw_case, "extraction correction")
        source_extraction_id = _required_uuid(
            case.get("original_extraction_id"), "original_extraction_id"
        )
        if source_extraction_id in seen_extractions:
            raise ValueError("correction manifest repeats a source extraction")
        seen_extractions.add(source_extraction_id)
        stored = await evidence_repository.load_for_correction(source_extraction_id)
        source = stored.result
        if source.status != "completed":
            raise ValueError("only completed extractions can receive corrections")
        if members.get(source.document_id) != source.extraction_id:
            raise ValueError("source extraction is not the current draft member")
        chunking_data = source.configuration.get("chunking")
        chunking = ChunkingConfig.from_dict(
            _mapping(chunking_data, "chunking configuration")
        )
        reviewed = await asyncio.to_thread(
            create_reviewed_extraction,
            source,
            case,
            reviewer=reviewer,
            corrections_sha256=correction_hash,
            source_pdf_sha256=stored.source_pdf_sha256,
            chunking=chunking,
            tokenizer=embedder,
        )
        current_extraction_id = members.get(source.document_id)
        if current_extraction_id not in {
            source.extraction_id,
            reviewed.result.extraction_id,
        }:
            raise ValueError(
                "draft member changed since the correction source was inspected"
            )
        prepared.append((source.document_id, source.extraction_id, reviewed))

    results: list[dict[str, object]] = []
    for document_id, source_extraction_id, reviewed in prepared:
        persisted = await evidence_repository.persist(
            reviewed.result, reviewed.evidence_units
        )
        if members[document_id] == source_extraction_id:
            await snapshot_repository.replace_extraction(
                args.snapshot_id,
                document_id,
                source_extraction_id,
                reviewed.result.extraction_id,
            )
        results.append(
            {
                "document_id": str(document_id),
                "source_extraction_id": str(source_extraction_id),
                "extraction_id": str(persisted.extraction_id),
                "configuration_id": reviewed.result.configuration_id,
                "section_count": persisted.section_count,
                "table_count": persisted.table_count,
                "evidence_unit_count": persisted.evidence_unit_count,
                "corrected_table_ordinals": list(reviewed.corrected_table_ordinals),
                "reclassified_table_ordinals": list(
                    reviewed.reclassified_table_ordinals
                ),
                "reused_existing": persisted.reused_existing,
            }
        )
    print(
        json.dumps(
            {
                "snapshot_id": str(args.snapshot_id),
                "corrections_sha256": correction_hash,
                "reviewer": reviewer.strip(),
                "results": results,
                "index_rebuild_required": True,
            },
            indent=2,
        )
    )


async def _execute_snapshots(
    args: argparse.Namespace, repository: SnapshotRepository
) -> None:
    if args.snapshot_command == "inspect":
        members = await repository.inspect_members(args.snapshot_id)
        print(json.dumps([asdict(member) for member in members], indent=2, default=str))
        return
    if args.snapshot_command == "evidence":
        evidence_report = await repository.inspect_draft_evidence(
            args.snapshot_id, limit=args.limit
        )
        print(json.dumps(evidence_report, indent=2, default=str))
        return
    if args.snapshot_command == "create":
        configuration = _mapping(
            json.loads(args.configuration.read_text(encoding="utf-8")),
            "snapshot configuration",
        )
        canonical = json.dumps(
            dict(configuration),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        configuration_id = (
            "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        )
        snapshot_id = await repository.create_draft(
            name=args.name,
            configuration_id=configuration_id,
            configuration=configuration,
            code_revision=code_revision(),
        )
        print(str(snapshot_id))
        return
    if args.snapshot_command == "add":
        await repository.add_member(
            args.snapshot_id,
            paper_id=args.paper_id,
            document_id=args.document_id,
            extraction_id=args.extraction_id,
            selection_reason=args.selection_reason,
        )
        print(f"Added {args.paper_id} to draft {args.snapshot_id}")
        return
    if args.snapshot_command == "add-membership":
        membership = MembershipDecision.load(args.decision)
        document_ids = _load_selected_document_ids(args.document_map, membership)
        await repository.add_reviewed_membership(
            args.snapshot_id, membership, document_ids
        )
        print(f"Added the 100-paper membership to draft {args.snapshot_id}")
        return
    if args.snapshot_command == "remove":
        await repository.remove_member(args.snapshot_id, args.paper_id)
        print(f"Removed {args.paper_id} from draft {args.snapshot_id}")
        return
    if args.snapshot_command == "validate":
        validation_report = await repository.validate(
            args.snapshot_id, minimum_papers=args.minimum_papers
        )
        print(json.dumps(asdict(validation_report), indent=2, default=str))
        if not validation_report.valid:
            raise ValueError("snapshot validation failed; review the listed issues")
        return
    if args.snapshot_command == "review-table":
        await repository.review_flagged_table(
            args.snapshot_id,
            args.extraction_id,
            args.table_ordinal,
            reviewer=args.reviewer,
        )
        print("Recorded flagged-table review")
        return
    if args.snapshot_command == "finalize":
        finalized = await repository.finalize(
            args.snapshot_id,
            reviewer=args.reviewer,
            minimum_papers=args.minimum_papers,
        )
        print(json.dumps(asdict(finalized), indent=2, default=str))


async def _execute_job_status(
    args: argparse.Namespace, repository: IngestionJobRepository
) -> None:
    summary = await repository.get_summary(args.job_id)
    print(json.dumps(asdict(summary), indent=2, default=str))


async def _execute_citation_enrichment(
    args: argparse.Namespace,
    settings: Settings,
    pool: asyncpg.Pool,
) -> None:
    configuration = _load_discovery_config(args.config)
    if not settings.openalex_api_key:
        raise ValueError("set OPENALEX_API_KEY in the environment or project .env file")
    limit = (
        args.limit
        if args.limit is not None
        else min(configuration.limits.max_total_requests, 100)
    )
    if limit <= 0:
        raise ValueError("citation enrichment --limit must be positive")
    repository = CitationMetadataRepository(pool)
    async with httpx.AsyncClient(follow_redirects=False) as http:
        client = OpenAlexClient(
            configuration,
            settings.openalex_api_key,
            http,
        )
        outcome = await enrich_unresolved_citations(
            repository,
            client,
            limit=limit,
            code_revision=code_revision(),
        )
    print(
        json.dumps(
            {
                "identifiers_checked": outcome.identifiers_checked,
                "metadata_found": outcome.metadata_found,
                "identifiers_not_found": outcome.identifiers_not_found,
                "request_attempts": outcome.request_attempts,
                "configuration_id": configuration.config_id,
            },
            indent=2,
        )
    )


async def _execute_membership_import(
    args: argparse.Namespace,
    settings: Settings,
    pool: asyncpg.Pool,
) -> None:
    membership = MembershipDecision.load(args.decision).with_source_route_review(
        args.source_route_review
    )
    if not settings.openalex_api_key:
        raise ValueError("set OPENALEX_API_KEY in the environment or project .env file")
    discovery_config = _load_discovery_config(args.config)
    request_config = replace(
        discovery_config,
        limits=replace(
            discovery_config.limits,
            max_total_requests=125,
            max_retries=min(discovery_config.limits.max_retries, 2),
        ),
    )
    cache_path: Path = args.metadata_cache
    cached_metadata = _load_membership_metadata_cache(
        cache_path, membership.selected_openalex_ids
    )
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    client: OpenAlexClient | None = None
    async with httpx.AsyncClient(follow_redirects=False) as http:
        client = OpenAlexClient(request_config, settings.openalex_api_key, http)
        for openalex_id in sorted(membership.selected_openalex_ids):
            if openalex_id in cached_metadata:
                continue
            work = await client.get_work_metadata(openalex_id)
            _validate_membership_metadata(work, membership)
            metadata = dict(work.metadata)
            metadata.pop("abstract_inverted_index", None)
            cached_metadata[openalex_id] = metadata
            _write_membership_metadata_cache(cache_path, cached_metadata)
    if client is None:
        raise RuntimeError("OpenAlex metadata client was not created")

    metadata_by_id: dict[str, Mapping[str, object]] = {}
    cache_pdf_count = 0
    permitted_cache_count = 0
    for openalex_id in sorted(membership.selected_openalex_ids):
        value = cached_metadata[openalex_id]
        if not isinstance(value, Mapping):
            raise ValueError("OpenAlex metadata cache contains a non-object work")
        work = OpenAlexWork.from_payload(value)
        _validate_membership_metadata(work, membership)
        metadata_by_id[openalex_id] = value
        availability = OpenAlexContentAvailability.from_work_metadata(
            openalex_id, work.metadata
        )
        route = membership.selected_sources[openalex_id]
        if route.pool != "approved_v1_reference_sample":
            route_host = urlsplit(route.source_url).hostname
            if route_host == "content.openalex.org":
                best_location = work.metadata.get("best_oa_location")
                best_version = (
                    best_location.get("version")
                    if isinstance(best_location, Mapping)
                    else None
                )
                if (
                    not availability.pdf_available
                    or availability.license_id != route.license_id
                    or route.version != best_version
                    or route.source_url
                    != f"{OPENALEX_CONTENT_BASE}/works/{openalex_id}.pdf"
                    or route.terms_url is None
                ):
                    raise ValueError(
                        f"OpenAlex route, exact version, and CC license do not agree for {openalex_id}"
                    )
            elif route_host != "arxiv.org":
                raise ValueError(
                    f"selected source host is unsupported for {openalex_id}"
                )
        if availability.pdf_available:
            cache_pdf_count += 1
            if availability.license_id in AcquisitionConfig().permitted_licenses:
                permitted_cache_count += 1

    outcome = await PaperRepository(pool).import_reviewed_membership(
        membership, metadata_by_id
    )
    document_map: dict[str, object] = {
        "schema_version": 1,
        "membership_decision_id": membership.identity,
        "source_route_review_id": membership.source_route_review_identity,
        "selected_document_ids": {
            openalex_id: str(document_id)
            for openalex_id, document_id in outcome.selected_document_ids.items()
        },
    }
    _write_json_atomically(args.document_map, document_map)
    print(
        json.dumps(
            {
                "membership_decision_id": outcome.membership_decision_id,
                "collection_id": str(outcome.collection_id),
                "papers_imported": outcome.imported_papers,
                "new_papers": outcome.new_papers,
                "metadata_requests": client.requests_used,
                "cached_pdf_available": cache_pdf_count,
                "cached_pdf_with_allowed_license": permitted_cache_count,
                "metadata_cache": str(cache_path),
                "document_map": str(args.document_map),
            },
            indent=2,
        )
    )


async def _execute_membership_acquisition(
    args: argparse.Namespace,
    settings: Settings,
    pool: asyncpg.Pool,
) -> None:
    membership = MembershipDecision.load(args.decision).with_source_route_review(
        args.source_route_review
    )
    api_key = settings.openalex_api_key
    if not api_key:
        raise ValueError("set OPENALEX_API_KEY in the environment or project .env file")
    document_ids = _load_selected_document_ids(args.document_map, membership)
    metadata_cache = _load_membership_metadata_cache(
        args.metadata_cache, membership.selected_openalex_ids
    )
    if set(metadata_cache) != set(membership.selected_openalex_ids):
        raise ValueError(
            "complete OpenAlex metadata cache is required before acquisition"
        )

    acquisition_config = AcquisitionConfig(
        maximum_documents=90,
        maximum_requests=87,
        maximum_retries=0,
    )
    store = ArtifactStore(
        args.artifact_root,
        maximum_file_bytes=acquisition_config.maximum_file_bytes,
        maximum_store_bytes=acquisition_config.maximum_store_bytes,
    )
    store_status = store.inspect()
    if store_status.remaining_store_bytes <= 0:
        raise ValueError("artifact store has reached its configured 2 GiB ceiling")

    artifact_repository = ArtifactRepository(pool)
    openalex_todo: list[
        tuple[str, UUID, OpenAlexContentAvailability, PermissionEvidence]
    ] = []
    direct_todo: list[tuple[str, UUID, PermissionEvidence]] = []
    already_registered = 0
    new_route_count = 0
    for openalex_id in sorted(membership.selected_openalex_ids):
        route = membership.selected_sources[openalex_id]
        if route.pool == "approved_v1_reference_sample":
            continue
        new_route_count += 1
        if route.license_id not in acquisition_config.permitted_licenses:
            raise ValueError(
                f"selected source license is not allowed for {openalex_id}"
            )
        if not route.terms_url:
            raise ValueError(f"selected source terms URL is missing for {openalex_id}")
        metadata = metadata_cache[openalex_id]
        work = OpenAlexWork.from_payload(metadata)
        availability = OpenAlexContentAvailability.from_work_metadata(
            openalex_id, work.metadata
        )
        route_host = urlsplit(route.source_url).hostname
        checked_at = datetime.now(timezone.utc)
        if route_host == "content.openalex.org":
            best_location = work.metadata.get("best_oa_location")
            if not isinstance(best_location, Mapping):
                raise ValueError(
                    f"OpenAlex best OA location is missing for {openalex_id}"
                )
            if (
                not availability.pdf_available
                or availability.license_id != route.license_id
                or best_location.get("version") != route.version
                or route.source_url
                != f"{OPENALEX_CONTENT_BASE}/works/{openalex_id}.pdf"
            ):
                raise ValueError(
                    f"OpenAlex source, version, and license metadata disagree for {openalex_id}"
                )
            permission = PermissionEvidence(
                source_name="openalex-content-api",
                source_url=route.source_url,
                license_id=route.license_id,
                basis=(
                    f"OpenAlex best_oa_location records {route.version} under "
                    f"{route.license_id}; source terms are recorded at {route.terms_url}. "
                    "OpenAlex cache delivery grants no additional rights."
                ),
                terms_url=route.terms_url,
                checked_at=checked_at,
                reviewer="assistant acting under explicit user delegation",
                storage_permitted=True,
                indexing_permitted=True,
                passage_display_permitted=False,
            )
            existing = await artifact_repository.matching_permissioned_pdf(
                document_ids[openalex_id],
                source_name=permission.source_name,
                source_url=permission.source_url,
                license_id=permission.license_id,
            )
            if existing is not None:
                resolve_registered_pdf(
                    args.artifact_root,
                    existing.storage_path,
                    sha256=existing.sha256,
                    byte_size=existing.byte_size,
                )
                already_registered += 1
                continue
            openalex_todo.append(
                (openalex_id, document_ids[openalex_id], availability, permission)
            )
        elif route_host == "arxiv.org":
            if not route.source_url.endswith(route.version):
                raise ValueError(f"arXiv route is not pinned to {route.version}")
            permission = PermissionEvidence(
                source_name="arxiv",
                source_url=route.source_url,
                license_id=route.license_id,
                basis=(
                    f"The exact versioned arXiv record {route.terms_url} links to "
                    "the CC BY 4.0 license; the route review verifies this pinned version."
                ),
                terms_url=route.terms_url,
                checked_at=checked_at,
                reviewer="assistant acting under explicit user delegation",
                storage_permitted=True,
                indexing_permitted=True,
                passage_display_permitted=False,
            )
            existing = await artifact_repository.matching_permissioned_pdf(
                document_ids[openalex_id],
                source_name=permission.source_name,
                source_url=permission.source_url,
                license_id=permission.license_id,
            )
            if existing is not None:
                resolve_registered_pdf(
                    args.artifact_root,
                    existing.storage_path,
                    sha256=existing.sha256,
                    byte_size=existing.byte_size,
                )
                already_registered += 1
                continue
            direct_todo.append((openalex_id, document_ids[openalex_id], permission))
        else:
            raise ValueError(f"selected source host is unsupported for {openalex_id}")

    if new_route_count != 90:
        raise ValueError("approved membership must contain 90 new acquisition routes")
    if len(openalex_todo) > acquisition_config.maximum_requests:
        raise ValueError("OpenAlex acquisition exceeds the hard 87-request ceiling")
    if len(direct_todo) > 3:
        raise ValueError("direct-source acquisition exceeds the three-paper route set")

    async with httpx.AsyncClient(follow_redirects=False) as http:
        preflight_budget: dict[str, float] | None = None
        remaining_openalex_reservations = len(openalex_todo)
        latest_budget: dict[str, float] | None = None
        if openalex_todo:
            preflight_budget = await _read_openalex_free_budget(http, api_key)
            content_cost_usd = preflight_budget["content_cost_usd"]
            required_usd = len(openalex_todo) * content_cost_usd
            if preflight_budget["daily_remaining_usd"] + 1e-9 < required_usd:
                raise ValueError(
                    "OpenAlex free daily allowance is below the full remaining "
                    "batch cost; no PDFs were requested"
                )

        async def reserve_openalex_request() -> None:
            nonlocal remaining_openalex_reservations, latest_budget
            latest_budget = await _read_openalex_free_budget(http, api_key)
            required = (
                remaining_openalex_reservations * latest_budget["content_cost_usd"]
            )
            if latest_budget["daily_remaining_usd"] + 1e-9 < required:
                raise ValueError(
                    "OpenAlex free daily allowance no longer covers the remaining "
                    "batch; no further PDF was requested"
                )
            remaining_openalex_reservations -= 1

        openalex_adapter = (
            OpenAlexContentAdapter(
                AcquisitionConfig(
                    maximum_documents=len(openalex_todo),
                    maximum_requests=len(openalex_todo),
                    maximum_retries=0,
                    permitted_licenses=("cc-by", "public-domain"),
                ),
                api_key,
                http,
                store,
                reserve_request=reserve_openalex_request,
            )
            if openalex_todo
            else None
        )
        direct_adapter = (
            DirectSourcePdfAdapter(
                AcquisitionConfig(
                    maximum_documents=len(direct_todo),
                    maximum_requests=len(direct_todo),
                    maximum_retries=0,
                    permitted_licenses=("cc-by", "public-domain"),
                ),
                http,
                store,
            )
            if direct_todo
            else None
        )
        downloaded_openalex = 0
        downloaded_direct = 0
        bytes_downloaded = 0
        for openalex_id, document_id, availability, permission in openalex_todo:
            if openalex_adapter is None:
                raise RuntimeError("OpenAlex adapter was not initialized")
            stored = await openalex_adapter.download_pdf(availability, permission)
            await artifact_repository.record_download(document_id, stored, permission)
            downloaded_openalex += 1
            bytes_downloaded += stored.byte_size
        for openalex_id, document_id, permission in direct_todo:
            if direct_adapter is None:
                raise RuntimeError("direct-source adapter was not initialized")
            stored = await direct_adapter.download_pdf(permission)
            await artifact_repository.record_download(document_id, stored, permission)
            downloaded_direct += 1
            bytes_downloaded += stored.byte_size

    final_budget = latest_budget or preflight_budget
    print(
        json.dumps(
            {
                "membership_decision_id": membership.identity,
                "source_route_review_id": membership.source_route_review_identity,
                "registered_existing": already_registered,
                "openalex_pdfs_downloaded": downloaded_openalex,
                "direct_source_pdfs_downloaded": downloaded_direct,
                "openalex_requests_used": (
                    openalex_adapter.requests_used if openalex_adapter else 0
                ),
                "direct_source_requests_used": (
                    direct_adapter.requests_used if direct_adapter else 0
                ),
                "estimated_openalex_content_cost_usd": round(
                    (openalex_adapter.requests_used if openalex_adapter else 0)
                    * (
                        preflight_budget["content_cost_usd"]
                        if preflight_budget
                        else 0.0
                    ),
                    2,
                ),
                "free_daily_remaining_usd_before_batch": (
                    preflight_budget["daily_remaining_usd"]
                    if preflight_budget
                    else None
                ),
                "free_daily_remaining_usd_after_last_preflight": (
                    final_budget["daily_remaining_usd"] if final_budget else None
                ),
                "bytes_downloaded": bytes_downloaded,
                "artifact_store": asdict(store.inspect()),
            },
            indent=2,
        ),
        flush=True,
    )


async def _read_openalex_free_budget(
    http: httpx.AsyncClient, api_key: str
) -> dict[str, float]:
    response = await http.get(
        "https://api.openalex.org/rate-limit", params={"api_key": api_key}
    )
    response.raise_for_status()
    payload = _mapping(response.json(), "OpenAlex rate-limit response")
    rate_limit_value = payload.get("rate_limit")
    rate_limit = rate_limit_value if isinstance(rate_limit_value, Mapping) else payload

    def number(name: str, nested_name: str | None = None) -> float:
        value = rate_limit.get(name)
        if value is None:
            value = payload.get(name)
        if value is None and nested_name is not None:
            container_value = rate_limit.get(nested_name)
            if container_value is None:
                container_value = payload.get(nested_name)
            if isinstance(container_value, Mapping):
                value = container_value.get("content")
                if value is None:
                    value = container_value.get("remaining_usd")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("OpenAlex rate-limit response is missing budget fields")
        result = float(value)
        if result < 0 or not isfinite(result):
            raise ValueError("OpenAlex rate-limit response has invalid budget values")
        return result

    return {
        "daily_remaining_usd": number("daily_remaining_usd"),
        "prepaid_remaining_usd": number("prepaid_remaining_usd"),
        "content_cost_usd": number("content_cost_usd", "endpoint_costs_usd"),
    }


def _load_membership_metadata_cache(
    path: Path, selected_ids: frozenset[str]
) -> dict[str, Mapping[str, object]]:
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("membership metadata cache cannot be read") from error
    if not isinstance(raw, Mapping):
        raise ValueError("membership metadata cache must be a JSON object")
    if not set(raw).issubset(selected_ids):
        raise ValueError("membership metadata cache includes unselected works")
    cache: dict[str, Mapping[str, object]] = {}
    for openalex_id, value in raw.items():
        cache[openalex_id] = _mapping(value, "cached OpenAlex work")
    return cache


def _validate_membership_metadata(
    work: OpenAlexWork, membership: MembershipDecision
) -> None:
    openalex_id = work.openalex_id
    if openalex_id not in membership.selected_openalex_ids:
        raise ValueError("OpenAlex returned a work outside the approved selection")
    if (
        work.title != membership.selected_titles[openalex_id]
        or work.publication_year != membership.publication_years[openalex_id]
        or work.language != "en"
    ):
        raise ValueError(
            f"current title, year, or language changed for reviewed work {openalex_id}"
        )


def _write_json_atomically(path: Path, value: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(path.name + ".tmp")
    temporary_path.write_text(
        json.dumps(dict(value), sort_keys=True, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(path)


def _write_membership_metadata_cache(
    path: Path, metadata: Mapping[str, Mapping[str, object]]
) -> None:
    temporary_path = path.with_name(path.name + ".tmp")
    temporary_path.write_text(
        json.dumps(metadata, sort_keys=True, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(path)


async def _execute_discovery(
    args: argparse.Namespace,
    settings: Settings,
    repository: DiscoveryRepository,
) -> None:
    configuration = _load_discovery_config(args.config)
    if not settings.openalex_api_key:
        raise ValueError("set OPENALEX_API_KEY in the environment or project .env file")
    run_id = args.resume or await repository.create_run(configuration, code_revision())

    async def reserve_request() -> None:
        await repository.reserve_request(
            run_id, configuration.limits.max_total_requests
        )

    async with httpx.AsyncClient(follow_redirects=False) as http:
        client = OpenAlexClient(
            configuration,
            settings.openalex_api_key,
            http,
            reserve_request=reserve_request,
        )
        outcome = await run_discovery(run_id, configuration, repository, client)
    print(
        json.dumps(
            {
                "run_id": str(outcome.run_id),
                "status": outcome.status,
                "pages_saved_this_invocation": outcome.pages_saved,
                "request_attempts_this_invocation": outcome.request_attempts,
                "configuration_id": configuration.config_id,
            },
            indent=2,
        )
    )


async def _execute_manifest(
    args: argparse.Namespace,
    repository: DiscoveryRepository,
) -> None:
    if args.manifest_command == "prepare":
        manifest_id = await repository.prepare_shortlist_manifest(
            args.run_id, args.version, args.per_query_limit
        )
        print(str(manifest_id))
        return

    if args.manifest_command == "export":
        header = await repository.manifest_header(args.manifest_id)
        items = await repository.list_manifest_items(args.manifest_id)
        coverage = await repository.list_manifest_coverage(args.manifest_id)
        payload = _review_manifest_payload(header, items, coverage)
        mode = "w" if args.overwrite else "x"
        with args.output.open(mode, encoding="utf-8") as output_file:
            json.dump(payload, output_file, indent=2, ensure_ascii=False)
            output_file.write("\n")
        print(f"Wrote {len(items)} candidates to {args.output}")
        return

    if args.manifest_command == "report":
        header = await repository.manifest_header(args.manifest_id)
        items = await repository.list_manifest_items(args.manifest_id)
        coverage = await repository.list_manifest_coverage(args.manifest_id)
        run = await repository.run_summary_for_manifest(args.manifest_id)
        report = build_manifest_review_report(header, run, items, coverage)
        mode = "w" if args.overwrite else "x"
        with args.output.open(mode, encoding="utf-8") as output_file:
            json.dump(report, output_file, indent=2, ensure_ascii=False)
            output_file.write("\n")
        print(f"Wrote review report to {args.output}")
        return

    if args.manifest_command == "import":
        await _import_manifest_review(args.manifest_id, args.input, repository)
        print(f"Saved review decisions for manifest {args.manifest_id}")
        return

    if args.manifest_command == "approve":
        await repository.approve_manifest(args.manifest_id, args.reviewer)
        print(f"Approved manifest {args.manifest_id}")


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be a JSON object")
    return cast(Mapping[str, object], value)


async def _import_manifest_review(
    manifest_id: UUID,
    input_path: Path,
    repository: DiscoveryRepository,
) -> None:
    raw = json.loads(input_path.read_text(encoding="utf-8"))
    payload = _mapping(raw, "manifest review")
    if payload.get("manifest_id") != str(manifest_id):
        raise ValueError(
            "review file manifest_id does not match the requested manifest"
        )
    items_value = payload.get("items")
    if not isinstance(items_value, list):
        raise ValueError("manifest review items must be a list")

    existing_ids = {
        item.openalex_id for item in await repository.list_manifest_items(manifest_id)
    }
    decisions: list[ManifestDecisionEntry] = []
    for item_value in items_value:
        item = _mapping(item_value, "manifest item")
        openalex_id = item.get("openalex_id")
        decision = item.get("decision")
        reason = item.get("reason")
        coverage_value = item.get("coverage_questions")
        if not isinstance(openalex_id, str):
            raise ValueError("manifest item openalex_id must be a string")
        if decision not in {"include", "exclude"}:
            raise ValueError(f"manifest item {openalex_id} needs include or exclude")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError(f"manifest item {openalex_id} needs a decision reason")
        if not isinstance(coverage_value, list) or not all(
            isinstance(question, str) for question in coverage_value
        ):
            raise ValueError(
                f"manifest item {openalex_id} coverage_questions must be a list"
            )
        decisions.append(
            ManifestDecisionEntry(
                openalex_id=openalex_id,
                decision=decision,
                reason=reason,
                coverage_questions=tuple(coverage_value),
            )
        )
    reviewed_ids = {entry.openalex_id for entry in decisions}
    if reviewed_ids != existing_ids or len(reviewed_ids) != len(decisions):
        missing = sorted(existing_ids - reviewed_ids)
        unknown = sorted(reviewed_ids - existing_ids)
        raise ValueError(f"manifest items differ; missing={missing}, unknown={unknown}")

    coverage_value = payload.get("coverage_reviews")
    if not isinstance(coverage_value, list):
        raise ValueError("coverage_reviews must contain all three reviewed questions")
    expected_questions = {question for question, _label in _COVERAGE_QUESTIONS}
    coverage_reviews: list[ManifestCoverageEntry] = []
    for review_value in coverage_value:
        review = _mapping(review_value, "coverage review")
        question = review.get("question_key")
        status = review.get("status")
        note = review.get("reviewer_note")
        if not isinstance(question, str) or question not in expected_questions:
            raise ValueError("coverage review contains an unknown question key")
        if status not in {"covered", "gap"}:
            raise ValueError(f"coverage review {question} needs covered or gap")
        if not isinstance(note, str) or not note.strip():
            raise ValueError(f"coverage review {question} needs a reviewer note")
        coverage_reviews.append(
            ManifestCoverageEntry(
                question=question,
                status=status,
                reviewer_note=note,
            )
        )
    if {review.question for review in coverage_reviews} != expected_questions or len(
        coverage_reviews
    ) != len(expected_questions):
        raise ValueError("review file must assess all three coverage questions")

    await repository.apply_manifest_review(
        manifest_id,
        tuple(decisions),
        tuple(coverage_reviews),
    )


def main() -> None:
    _load_local_environment()
    parser = build_parser()
    args = parser.parse_args()
    try:
        asyncio.run(_execute(args))
    except (OSError, ValueError, RuntimeError, asyncpg.PostgresError) as error:
        print(f"error: {type(error).__name__}: {error}", file=sys.stderr)
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
