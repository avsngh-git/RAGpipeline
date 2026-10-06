-- Phase 4: one row per model call, and its text only at trace content "full" (ADR-0026).
CREATE TABLE llm_calls (
    run_id UUID NOT NULL REFERENCES research_runs (id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL CHECK (ordinal >= 1),
    kind TEXT NOT NULL
        CHECK (kind IN ('plan', 'evaluate', 'synthesize', 'judge', 'probe')),
    status TEXT NOT NULL CHECK (status IN ('succeeded', 'failed')),
    error_type TEXT,
    model_name TEXT NOT NULL,
    think BOOLEAN NOT NULL,
    options JSONB NOT NULL DEFAULT '{}'::jsonb,
    prompt_version TEXT,
    prompt_fingerprint TEXT,
    attempts INTEGER NOT NULL CHECK (attempts >= 0),
    prompt_tokens INTEGER CHECK (prompt_tokens IS NULL OR prompt_tokens >= 0),
    output_tokens INTEGER CHECK (output_tokens IS NULL OR output_tokens >= 0),
    thinking_chars INTEGER CHECK (thinking_chars IS NULL OR thinking_chars >= 0),
    duration_ms DOUBLE PRECISION NOT NULL CHECK (duration_ms >= 0),
    trace_id TEXT,
    span_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, ordinal),
    CHECK ((status = 'failed') = (error_type IS NOT NULL))
);

CREATE TABLE llm_call_payloads (
    run_id UUID NOT NULL,
    ordinal INTEGER NOT NULL,
    messages JSONB NOT NULL,
    output TEXT,
    thinking TEXT,
    error_preview TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, ordinal),
    FOREIGN KEY (run_id, ordinal)
        REFERENCES llm_calls (run_id, ordinal) ON DELETE CASCADE
);
CREATE INDEX idx_llm_call_payloads_created_at ON llm_call_payloads (created_at);
