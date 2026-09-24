-- Phase 1: retain the operator's reason when a specific stage is retried.

ALTER TABLE ingestion_stage_attempts
    ADD COLUMN retry_reason TEXT
        CHECK (retry_reason IS NULL OR length(btrim(retry_reason)) > 0);
