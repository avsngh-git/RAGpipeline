ALTER TABLE research_runs
    ADD COLUMN ingestion_permitted BOOLEAN NOT NULL DEFAULT TRUE;

COMMENT ON COLUMN research_runs.ingestion_permitted IS
    'False when the API key that started the run lacked the ingest scope (ADR-0030).';
