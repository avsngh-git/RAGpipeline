"""Tests for Phase 1 operator command parsing."""

from pathlib import Path
from uuid import UUID

import pytest

from research_platform.ingestion.cli import build_parser


def test_snapshot_and_job_commands_parse_explicit_ids_and_gates() -> None:
    snapshot_id = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
    document_id = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
    extraction_id = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")
    parser = build_parser()

    create = parser.parse_args(
        ["snapshots", "create", "--name", "pilot", "--configuration", "config.json"]
    )
    add = parser.parse_args(
        [
            "snapshots",
            "add",
            "--snapshot-id",
            str(snapshot_id),
            "--paper-id",
            "W123",
            "--document-id",
            str(document_id),
            "--extraction-id",
            str(extraction_id),
            "--selection-reason",
            "reviewed selection",
        ]
    )
    finalize = parser.parse_args(
        [
            "snapshots",
            "finalize",
            "--snapshot-id",
            str(snapshot_id),
            "--reviewer",
            "human-reviewer",
        ]
    )
    status = parser.parse_args(["jobs", "status", "--job-id", str(snapshot_id)])

    assert create.configuration == Path("config.json")
    assert add.snapshot_id == snapshot_id
    assert add.document_id == document_id
    assert add.extraction_id == extraction_id
    assert finalize.minimum_papers == 100
    assert status.job_id == snapshot_id


def test_manifest_report_requires_a_reviewable_output_path() -> None:
    manifest_id = UUID("ffffffff-ffff-4fff-8fff-ffffffffffff")
    args = build_parser().parse_args(
        [
            "manifest",
            "report",
            "--manifest-id",
            str(manifest_id),
            "--output",
            "report.json",
        ]
    )

    assert args.manifest_id == manifest_id
    assert args.output == Path("report.json")
    assert args.overwrite is False


def test_storage_commands_have_inspection_defaults() -> None:
    parser = build_parser()

    inspect = parser.parse_args(["storage", "inspect"])
    cleanup = parser.parse_args(["storage", "cleanup-preview"])

    assert inspect.root == Path("data/artifacts")
    assert cleanup.older_than_hours == 168
    assert cleanup.limit == 100


def test_storage_cleanup_requires_an_explicit_age_and_defaults_to_preview() -> None:
    parser = build_parser()
    args = parser.parse_args(["storage", "cleanup", "--older-than-hours", "72"])

    assert args.older_than_hours == 72
    assert args.apply is False
    with pytest.raises(SystemExit):
        parser.parse_args(["storage", "cleanup"])


def test_index_inspection_requires_snapshot_and_versioned_configuration() -> None:
    snapshot_id = UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd")
    args = build_parser().parse_args(
        [
            "index",
            "inspect",
            "--snapshot-id",
            str(snapshot_id),
            "--configuration",
            "index.json",
        ]
    )

    assert args.snapshot_id == snapshot_id
    assert args.configuration == Path("index.json")


def test_snapshot_inspection_command_requires_snapshot_id() -> None:
    snapshot_id = UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee")
    args = build_parser().parse_args(
        ["snapshots", "inspect", "--snapshot-id", str(snapshot_id)]
    )

    assert args.snapshot_id == snapshot_id


def test_snapshot_evidence_inspection_is_bounded() -> None:
    snapshot_id = UUID("abababab-abab-4bab-8bab-abababababab")
    parser = build_parser()

    default = parser.parse_args(
        ["snapshots", "evidence", "--snapshot-id", str(snapshot_id)]
    )
    limited = parser.parse_args(
        [
            "snapshots",
            "evidence",
            "--snapshot-id",
            str(snapshot_id),
            "--limit",
            "3",
        ]
    )

    assert default.limit == 20
    assert limited.snapshot_id == snapshot_id
    assert limited.limit == 3


def test_pdf_job_index_and_flagged_table_commands_parse_review_gates() -> None:
    snapshot_id = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
    job_id = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
    document_id = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")
    extraction_id = UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd")
    parser = build_parser()

    start = parser.parse_args(
        [
            "jobs",
            "start",
            "--snapshot-id",
            str(snapshot_id),
            "--chunking-configuration",
            "chunking.json",
        ]
    )
    retry = parser.parse_args(
        [
            "jobs",
            "retry",
            "--job-id",
            str(job_id),
            "--document-id",
            str(document_id),
            "--from-stage",
            "extraction",
            "--reason",
            "verified local file repair",
        ]
    )
    rebuild = parser.parse_args(
        [
            "index",
            "rebuild",
            "--snapshot-id",
            str(snapshot_id),
            "--configuration",
            "index.json",
        ]
    )
    query = parser.parse_args(
        [
            "index",
            "query",
            "--snapshot-id",
            str(snapshot_id),
            "--configuration",
            "index.json",
            "--query",
            "hybrid retrieval performance",
        ]
    )
    review = parser.parse_args(
        [
            "snapshots",
            "review-table",
            "--snapshot-id",
            str(snapshot_id),
            "--extraction-id",
            str(extraction_id),
            "--table-ordinal",
            "4",
            "--reviewer",
            "human-reviewer",
        ]
    )

    assert start.job_command == "start"
    assert start.artifact_root == Path("data/artifacts")
    assert retry.from_stage == "extraction"
    assert retry.reason == "verified local file repair"
    assert rebuild.index_command == "rebuild"
    assert query.limit == 10
    assert review.table_ordinal == 4
