# Database migrations

Migration files are applied in lexical filename order by `scripts/migrate.py`.
Each successful migration is recorded in the `schema_migrations` table. The
initial migration creates the metadata, ingestion, run, citation, and evidence
tables required by the Phase 0 foundation.
