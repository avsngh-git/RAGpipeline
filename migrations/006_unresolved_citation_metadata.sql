-- Phase 1: add bounded metadata without inventing local paper records.

CREATE TABLE unresolved_citation_metadata (
    target_namespace TEXT NOT NULL,
    target_identifier TEXT NOT NULL,
    provider TEXT NOT NULL CHECK (length(btrim(provider)) > 0),
    lookup_status TEXT NOT NULL CHECK (lookup_status IN ('found', 'not_found')),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(metadata) = 'object'),
    retrieved_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    configuration_id TEXT NOT NULL,
    code_revision TEXT NOT NULL,
    PRIMARY KEY (target_namespace, target_identifier, provider),
    CHECK (
        (lookup_status = 'found' AND metadata <> '{}'::jsonb)
        OR (lookup_status = 'not_found' AND metadata = '{}'::jsonb)
    )
);
