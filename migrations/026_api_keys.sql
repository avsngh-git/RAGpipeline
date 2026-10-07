-- Phase 4: hashed API keys with scopes, and the principal that owns each run (ADR-0027).
CREATE TABLE api_keys (
    key_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    principal TEXT NOT NULL CHECK (principal ~ '^[a-z0-9][a-z0-9_.-]{0,62}$'),
    key_prefix TEXT NOT NULL UNIQUE CHECK (key_prefix ~ '^[A-Za-z0-9_-]{8}$'),
    key_sha256 TEXT NOT NULL UNIQUE CHECK (key_sha256 ~ '^[0-9a-f]{64}$'),
    scopes TEXT[] NOT NULL CHECK (
        cardinality(scopes) >= 1
        AND scopes <@ ARRAY['read', 'research', 'ingest', 'admin']::text[]
    ),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    revoked_at TIMESTAMPTZ
);
ALTER TABLE research_runs ADD COLUMN principal TEXT NOT NULL DEFAULT 'legacy-local';
CREATE INDEX idx_research_runs_principal ON research_runs (principal, status);
