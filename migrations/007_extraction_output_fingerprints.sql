-- Phase 1: make deterministic extraction retries detect changed outputs.

ALTER TABLE extractions
    ADD COLUMN output_sha256 TEXT
        CHECK (output_sha256 IS NULL OR output_sha256 ~ '^[0-9a-f]{64}$');
