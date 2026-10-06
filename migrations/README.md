# Database migrations

Migration files are applied in lexical filename order by `scripts/migrate.py`.
The runner takes a PostgreSQL advisory lock so concurrent invocations cannot
apply the same migration. Each migration and its `schema_migrations` row commit
in one transaction; a failed migration leaves neither schema changes nor a
success record. Keep an applied migration unchanged and add a new numbered SQL
file for schema evolution.

`001_initial.sql` is the Phase 0 foundation. `002_ingestion_evidence.sql` adds
Phase 1 identity and permission provenance, artifact and extraction lineage,
unresolved citations, structured evidence, stage attempts, immutable finalized
snapshots, and Qdrant reconciliation state. `003_openalex_discovery.sql` adds
bounded, resumable discovery checkpoints, retained candidate origins, and human
review manifests. `004_identity_and_manifest_imports.sql` imports only included
members of approved manifests, normalizes verified IDs, and preserves unresolved
citation endpoints without placeholder papers or titles. `005_artifact_permission_checks.sql`
keeps storage, indexing and passage-display decisions distinct and consistent.
`006_unresolved_citation_metadata.sql` stores bounded OpenAlex lookup results by
external identifier without creating placeholder paper rows. `007_extraction_output_fingerprints.sql`
checks extraction retries against a stable output fingerprint. `008_evidence_section_cascade.sql`
keeps dependent evidence rows consistent when their source section is removed.
`009_extraction_source_artifacts.sql` links each extraction to the exact reviewed
source artifact. `010_job_leases_and_snapshot_review.sql` enforces a single leased
ingestion owner and records who finalized a snapshot.
`011_unique_index_collection_identity.sql` prevents incompatible embedding
configurations from sharing a Qdrant collection.
`012_targeted_retry_reasons.sql` records why an operator repeated a stage. PostgreSQL owns
metadata and state; Qdrant remains a derived, rebuildable store.
013_ingestion_job_plans.sql persists immutable document membership and terminal
stage identity for resumable jobs.
014_snapshot_chunking_configuration.sql records the selected chunk configuration per
snapshot member.
015_snapshot_variant_lineage.sql backfills and freezes each snapshot's exact chunk
membership and records the finalized parent selection inherited by experimental variants.
016_phase3_research_runs.sql adds research runs, their collected evidence, tool calls,
claims with support labels, and LangGraph checkpoints.
017_claim_quotes.sql stores the passage quote each claim was verified against
(ADR-0025); claims from earlier runs keep a NULL quote.
018_index_generations.sql registers index generations of a collection with their build
state and one published pointer per index configuration, and records the generation a
research run reads.
019_lexical_vocabulary.sql adds the append-only term IDs used by scientific BM25
sparse vectors. 020_catalog_discovery.sql records OpenAlex metadata revisions and
discovery spend, and permits run-local abstract evidence while retaining database
checks that chunk evidence refers to indexed chunks.
021_ingestion_requests.sql adds the transactional ingestion outbox, per-paper policy
decisions, and the waiting-for-ingestion research-run state.
022_run_configurations.sql stores each effective research-run configuration once, keyed by
its SHA-256 configuration ID (ADR-0026).
