-- Phase 1: enforce one recoverable ingestion owner and record final approval.

ALTER TABLE ingestion_jobs
    ADD CONSTRAINT ingestion_jobs_status_check
        CHECK (status IN ('pending', 'running', 'completed', 'failed', 'cancelled')),
    ADD CONSTRAINT ingestion_jobs_lease_pair_check
        CHECK ((owner_token IS NULL) = (lease_expires_at IS NULL)),
    ADD CONSTRAINT ingestion_jobs_running_lease_check
        CHECK ((status = 'running') = (owner_token IS NOT NULL));

CREATE UNIQUE INDEX ingestion_jobs_single_running
    ON ingestion_jobs (status) WHERE status = 'running';

ALTER TABLE snapshots
    ADD COLUMN finalized_by TEXT,
    ADD CONSTRAINT snapshots_finalized_by_check
        CHECK ((status = 'finalized') = (finalized_by IS NOT NULL));
