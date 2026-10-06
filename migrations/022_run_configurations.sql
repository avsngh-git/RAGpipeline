-- Phase 4: content-addressed effective run configurations (ADR-0026).
CREATE TABLE run_configurations (
    configuration_id TEXT PRIMARY KEY
        CHECK (configuration_id ~ '^sha256:[0-9a-f]{64}$'),
    provenance_version INTEGER NOT NULL CHECK (provenance_version >= 1),
    configuration JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
