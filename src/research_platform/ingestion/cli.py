"""Terminal commands for bounded literature discovery and manifest review."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
from collections.abc import Mapping
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import cast
from uuid import UUID

import asyncpg  # type: ignore[import-untyped]
import httpx

from research_platform.config import Settings
from research_platform.ingestion.acquisition import AcquisitionConfig
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
from research_platform.ingestion.indexing import (
    IndexConfiguration,
    IndexRepository,
    QdrantIndex,
    rebuild_snapshot_index,
)
from research_platform.ingestion.manifest_report import build_manifest_review_report
from research_platform.ingestion.openalex import OpenAlexClient
from research_platform.ingestion.pdf_extraction import DoclingPdfConfig
from research_platform.ingestion.processing import PdfEvidenceProcessor
from research_platform.ingestion.provenance import code_revision
from research_platform.ingestion.runner import (
    IngestionDocument,
    IngestionRunner,
    PipelineStage,
)
from research_platform.ingestion.snapshots import SnapshotRepository
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
        elif args.command == "manifest":
            await _execute_manifest(args, repository)
        elif args.command == "citations":
            await _execute_citation_enrichment(args, settings, pool)
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
        if len(document_ids) > 10:
            raise ValueError(
                "this command is capped at the ten-paper approved reference set; "
                "the 100-paper run requires its separate approval gate"
            )
        document_inputs: list[dict[str, str]] = []
        documents: list[IngestionDocument] = []
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
            documents.append(IngestionDocument(document_id, fingerprint))
        processor = PdfEvidenceProcessor(
            pool,
            snapshot_id=snapshot_id,
            artifact_root=args.artifact_root,
            parser_config=DoclingPdfConfig(),
            chunking_config=chunking,
            tokenizer=E5SmallV2Embedder(device=args.device),
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
        }
        job_configuration_id = _configuration_identity(configuration)
        job_id = await jobs.create_job(
            configuration=configuration,
            configuration_id=job_configuration_id,
            code_revision=code_revision(),
            execution_profile="10-paper-comparison",
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
    if (
        not isinstance(stored_inputs, list)
        or not stored_inputs
        or len(stored_inputs) > 10
    ):
        raise ValueError("job document inputs are missing or exceed the ten-paper gate")
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


def _required_uuid(value: object, name: str) -> UUID:
    if not isinstance(value, str):
        raise ValueError(f"job {name} is invalid")
    try:
        return UUID(value)
    except ValueError:
        raise ValueError(f"job {name} is invalid") from None


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
