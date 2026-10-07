-- Phase 4: one row per evaluation run (ADR-0028).
CREATE TABLE experiments (
    experiment_id UUID PRIMARY KEY,
    suite TEXT NOT NULL CHECK (suite ~ '^[a-z][a-z0-9-]{1,62}$'),
    status TEXT NOT NULL CHECK (status IN ('running', 'completed', 'failed')),
    dataset_name TEXT NOT NULL,
    dataset_version TEXT NOT NULL,
    dataset_sha256 TEXT NOT NULL CHECK (dataset_sha256 ~ '^[0-9a-f]{64}$'),
    code_revision TEXT NOT NULL,
    configuration_id TEXT,
    configuration JSONB NOT NULL DEFAULT '{}'::jsonb,
    versions JSONB NOT NULL DEFAULT '{}'::jsonb,
    random_seed BIGINT,
    hardware JSONB NOT NULL DEFAULT '{}'::jsonb,
    metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
    failures JSONB NOT NULL DEFAULT '{}'::jsonb,
    items_path TEXT NOT NULL,
    item_count INTEGER NOT NULL DEFAULT 0 CHECK (item_count >= 0),
    notes TEXT,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ,
    CHECK ((status = 'running') = (completed_at IS NULL))
);
CREATE INDEX idx_experiments_suite ON experiments (suite, started_at DESC);
