ALTER TABLE research_runs
    ADD COLUMN mode TEXT NOT NULL DEFAULT 'quick'
        CHECK (mode IN ('quick', 'deep_research')),
    ADD COLUMN snapshot_id UUID REFERENCES snapshots (id) ON DELETE RESTRICT,
    ADD COLUMN request JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN provenance JSONB,
    ADD COLUMN answer_outcome TEXT
        CHECK (answer_outcome IN ('answered', 'partially_supported', 'insufficient_evidence')),
    ADD COLUMN failure_category TEXT
        CHECK (failure_category IN ('model_unavailable', 'invalid_model_output',
            'budget_exhausted', 'timeout', 'retrieval_error', 'resume_exhausted',
            'configuration_changed', 'internal')),
    ADD COLUMN usage JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN resume_count INTEGER NOT NULL DEFAULT 0 CHECK (resume_count >= 0),
    ADD COLUMN active_seconds DOUBLE PRECISION NOT NULL DEFAULT 0
        CHECK (active_seconds >= 0),
    ADD COLUMN started_at TIMESTAMPTZ,
    ADD COLUMN updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    ADD CONSTRAINT research_runs_status_check
        CHECK (status IN ('queued', 'running', 'completed', 'failed'));
ALTER TABLE research_runs ALTER COLUMN mode DROP DEFAULT;
CREATE INDEX idx_research_runs_status_created ON research_runs (status, created_at);

ALTER TABLE tool_calls
    ADD COLUMN ordinal INTEGER NOT NULL DEFAULT 0 CHECK (ordinal >= 0),
    ADD COLUMN duration_ms DOUBLE PRECISION,
    ADD COLUMN error_category TEXT,
    ADD CONSTRAINT tool_calls_status_check
        CHECK (status IN ('succeeded', 'failed', 'rejected', 'cached')),
    ADD CONSTRAINT tool_calls_run_ordinal_key UNIQUE (run_id, ordinal);
ALTER TABLE tool_calls ALTER COLUMN ordinal DROP DEFAULT;

ALTER TABLE claims
    ADD COLUMN support TEXT NOT NULL DEFAULT 'supported'
        CHECK (support IN ('supported', 'partial', 'unsupported'));
ALTER TABLE claims ALTER COLUMN support DROP DEFAULT;

ALTER TABLE claim_evidence ADD COLUMN handle TEXT;

CREATE TABLE research_run_evidence (
    run_id UUID NOT NULL REFERENCES research_runs (id) ON DELETE CASCADE,
    handle TEXT NOT NULL CHECK (handle ~ '^E[1-9][0-9]*$'),
    chunk_id TEXT NOT NULL REFERENCES chunks (id) ON DELETE RESTRICT,
    paper_id TEXT NOT NULL,
    text TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, handle),
    UNIQUE (run_id, chunk_id)
);
