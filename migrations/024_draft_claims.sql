-- Phase 4: every drafted claim with its verification verdict (ADR-0026).
CREATE TABLE draft_claims (
    run_id UUID NOT NULL REFERENCES research_runs (id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL CHECK (ordinal >= 1),
    handle TEXT NOT NULL,
    quote TEXT NOT NULL,
    claim_text TEXT NOT NULL,
    verdict TEXT NOT NULL
        CHECK (verdict IN ('kept', 'unknown_handle', 'not_shown', 'failed_checks')),
    failed_checks TEXT[] NOT NULL DEFAULT '{}',
    chunk_id TEXT,
    paper_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, ordinal)
);
ALTER TABLE research_runs ADD COLUMN synthesis JSONB;
