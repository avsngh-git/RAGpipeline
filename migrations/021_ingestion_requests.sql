CREATE TABLE ingestion_requests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    collection_id UUID NOT NULL REFERENCES collections (id) ON DELETE RESTRICT,
    run_id UUID REFERENCES research_runs (id) ON DELETE SET NULL,
    requested_by TEXT NOT NULL CHECK (requested_by IN ('run', 'api', 'terminal')),
    paper_ids TEXT[] NOT NULL CHECK (cardinality(paper_ids) BETWEEN 1 AND 20),
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'claimed', 'succeeded', 'partially_succeeded', 'failed')),
    claimed_by TEXT,
    lease_expires_at TIMESTAMPTZ,
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    result JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK ((status = 'claimed') = (claimed_by IS NOT NULL AND lease_expires_at IS NOT NULL))
);
CREATE INDEX idx_ingestion_requests_status
    ON ingestion_requests (status, created_at);

CREATE TABLE ingestion_decisions (
    id BIGSERIAL PRIMARY KEY,
    request_id UUID REFERENCES ingestion_requests (id) ON DELETE CASCADE,
    run_id UUID REFERENCES research_runs (id) ON DELETE SET NULL,
    paper_id TEXT NOT NULL,
    decision TEXT NOT NULL CHECK (decision IN ('accepted', 'refused')),
    reason TEXT NOT NULL,
    policy_revision TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE research_runs DROP CONSTRAINT research_runs_status_check;
ALTER TABLE research_runs ADD CONSTRAINT research_runs_status_check
    CHECK (status IN (
        'queued', 'running', 'waiting_for_ingestion', 'completed', 'failed'
    ));
