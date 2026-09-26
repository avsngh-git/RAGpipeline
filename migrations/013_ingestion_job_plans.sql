-- Persist the immutable document membership and required terminal stage of each job.

CREATE TABLE ingestion_job_plan (
    job_id UUID NOT NULL REFERENCES ingestion_jobs(id) ON DELETE CASCADE,
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    input_fingerprint TEXT NOT NULL
        CHECK (input_fingerprint ~ '^sha256:[0-9a-f]{64}$'),
    terminal_stage TEXT NOT NULL
        CHECK (terminal_stage ~ '^[a-z][a-z0-9_]{0,63}$'),
    terminal_configuration_id TEXT NOT NULL
        CHECK (terminal_configuration_id ~ '^sha256:[0-9a-f]{64}$'),
    PRIMARY KEY (job_id, document_id)
);
