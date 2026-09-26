"""Static checks for the initial schema contract."""

from pathlib import Path


def test_initial_migration_contains_required_entities() -> None:
    migration = (
        Path(__file__).parents[1] / "migrations" / "001_initial.sql"
    ).read_text(encoding="utf-8")

    for table in (
        "collections",
        "papers",
        "authors",
        "paper_authors",
        "citations",
        "documents",
        "sections",
        "chunks",
        "ingestion_jobs",
        "research_runs",
        "tool_calls",
        "claims",
        "claim_evidence",
    ):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in migration


def test_ingestion_migration_contains_lineage_and_snapshot_entities() -> None:
    migration = (
        Path(__file__).parents[1] / "migrations" / "002_ingestion_evidence.sql"
    ).read_text(encoding="utf-8")

    for table in (
        "paper_identifiers",
        "unresolved_citations",
        "artifacts",
        "document_artifacts",
        "extractions",
        "evidence_units",
        "evidence_tables",
        "ingestion_stage_attempts",
        "snapshots",
        "snapshot_items",
        "index_configurations",
        "snapshot_index_states",
    ):
        assert f"CREATE TABLE {table}" in migration

    assert "prevent_finalized_snapshot_item_change" in migration
    assert "prevent_finalized_snapshot_change" in migration


def test_discovery_migration_contains_resumable_review_tables() -> None:
    migration = (
        Path(__file__).parents[1] / "migrations" / "003_openalex_discovery.sql"
    ).read_text(encoding="utf-8")

    for table in (
        "discovery_runs",
        "discovery_queries",
        "discovery_pages",
        "discovery_candidates",
        "discovery_candidate_origins",
        "discovery_manifests",
        "discovery_manifest_items",
        "discovery_manifest_coverage",
    ):
        assert f"CREATE TABLE {table}" in migration

    assert "prevent_approved_manifest_change" in migration
    assert "manifest approval requires every decision" in migration


def test_identity_import_migration_keeps_paper_titles_optional() -> None:
    migration = (
        Path(__file__).parents[1]
        / "migrations"
        / "004_identity_and_manifest_imports.sql"
    ).read_text(encoding="utf-8")

    assert "ALTER COLUMN title DROP NOT NULL" in migration
    assert "manifest_paper_imports" in migration
    assert "require_approved_manifest_inclusion_for_import" in migration


def test_artifact_permission_migration_enforces_separate_rights() -> None:
    migration = (
        Path(__file__).parents[1] / "migrations" / "005_artifact_permission_checks.sql"
    ).read_text(encoding="utf-8")

    assert "document_artifact_indexing_requires_storage" in migration
    assert "document_artifact_display_requires_indexing" in migration
    assert "document_artifact_permission_basis_nonempty" in migration
    assert "document_permission_evidence" in migration
    assert "document_permission_evidence_immutable" in migration


def test_citation_metadata_migration_does_not_require_local_paper_rows() -> None:
    migration = (
        Path(__file__).parents[1]
        / "migrations"
        / "006_unresolved_citation_metadata.sql"
    ).read_text(encoding="utf-8")

    assert "CREATE TABLE unresolved_citation_metadata" in migration
    assert "target_namespace, target_identifier, provider" in migration
    assert "lookup_status IN ('found', 'not_found')" in migration


def test_extraction_fingerprint_migration_adds_output_hash() -> None:
    migration = (
        Path(__file__).parents[1]
        / "migrations"
        / "007_extraction_output_fingerprints.sql"
    ).read_text(encoding="utf-8")

    assert "ALTER TABLE extractions" in migration
    assert "output_sha256" in migration


def test_ingestion_job_plan_migration_persists_terminal_membership() -> None:
    migration = (
        Path(__file__).parents[1] / "migrations" / "013_ingestion_job_plans.sql"
    ).read_text(encoding="utf-8")

    assert "CREATE TABLE ingestion_job_plan" in migration
    assert "input_fingerprint" in migration
    assert "terminal_stage" in migration
    assert "terminal_configuration_id" in migration


def test_snapshot_chunk_configuration_migration_tracks_active_chunk_set() -> None:
    migration = (
        Path(__file__).parents[1]
        / "migrations"
        / "014_snapshot_chunking_configuration.sql"
    ).read_text(encoding="utf-8")

    assert "ALTER TABLE snapshot_items" in migration
    assert "chunking_configuration_id" in migration
    assert "sha256:[0-9a-f]{64}" in migration


def test_snapshot_variant_migration_freezes_exact_chunk_selection() -> None:
    migration = (
        Path(__file__).parents[1] / "migrations" / "015_snapshot_variant_lineage.sql"
    ).read_text(encoding="utf-8")

    assert "CREATE TABLE snapshot_item_chunks" in migration
    assert "snapshot_variant_lineage" in migration
    assert "parent_chunk_selection_id" in migration
    assert "INSERT INTO snapshot_item_chunks" in migration
    assert "prevent_finalized_snapshot_chunk_selection_change" in migration
    assert "ON DELETE RESTRICT" in migration
