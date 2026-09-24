-- Phase 1: replayable discovery, explainable candidates and reviewed manifests.

CREATE TABLE discovery_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    configuration_id TEXT NOT NULL,
    configuration JSONB NOT NULL,
    code_revision TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN ('pending', 'running', 'paused', 'completed', 'failed')
    ),
    request_count INTEGER NOT NULL DEFAULT 0 CHECK (request_count >= 0),
    result_count INTEGER NOT NULL DEFAULT 0 CHECK (result_count >= 0),
    api_cost_usd NUMERIC(12, 8) NOT NULL DEFAULT 0 CHECK (api_cost_usd >= 0),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    error_message TEXT
);

CREATE TABLE discovery_queries (
    run_id UUID NOT NULL REFERENCES discovery_runs(id) ON DELETE CASCADE,
    query_index INTEGER NOT NULL CHECK (query_index >= 0),
    query_text TEXT NOT NULL,
    source_kind TEXT NOT NULL DEFAULT 'search'
        CHECK (source_kind IN ('search', 'exception')),
    exception_openalex_id TEXT,
    next_cursor TEXT NOT NULL DEFAULT '*',
    page_count INTEGER NOT NULL DEFAULT 0 CHECK (page_count >= 0),
    completed BOOLEAN NOT NULL DEFAULT FALSE,
    truncated BOOLEAN NOT NULL DEFAULT FALSE,
    result_count INTEGER NOT NULL DEFAULT 0 CHECK (result_count >= 0),
    PRIMARY KEY (run_id, query_index),
    CHECK (
        (source_kind = 'search' AND exception_openalex_id IS NULL)
        OR (source_kind = 'exception' AND exception_openalex_id IS NOT NULL)
    )
);

CREATE TABLE discovery_pages (
    run_id UUID NOT NULL,
    query_index INTEGER NOT NULL,
    page_number INTEGER NOT NULL CHECK (page_number > 0),
    cursor_used TEXT NOT NULL,
    next_cursor TEXT,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    result_count INTEGER NOT NULL CHECK (result_count >= 0),
    api_cost_usd NUMERIC(12, 8) NOT NULL DEFAULT 0 CHECK (api_cost_usd >= 0),
    source_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (run_id, query_index, page_number),
    FOREIGN KEY (run_id, query_index)
        REFERENCES discovery_queries (run_id, query_index) ON DELETE CASCADE
);

CREATE TABLE discovery_candidates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id UUID NOT NULL REFERENCES discovery_runs(id) ON DELETE CASCADE,
    openalex_id TEXT NOT NULL,
    title TEXT,
    publication_year INTEGER,
    language TEXT,
    work_type TEXT,
    doi TEXT,
    cited_by_count INTEGER CHECK (cited_by_count IS NULL OR cited_by_count >= 0),
    metadata JSONB NOT NULL,
    selection_signals JSONB NOT NULL DEFAULT '{}'::jsonb,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (run_id, openalex_id),
    UNIQUE (run_id, id)
);

CREATE TABLE discovery_candidate_origins (
    run_id UUID NOT NULL,
    candidate_id UUID NOT NULL,
    query_index INTEGER NOT NULL,
    rank INTEGER CHECK (rank IS NULL OR rank > 0),
    relevance_score DOUBLE PRECISION,
    source_page INTEGER NOT NULL CHECK (source_page > 0),
    PRIMARY KEY (candidate_id, query_index),
    FOREIGN KEY (run_id, candidate_id)
        REFERENCES discovery_candidates (run_id, id) ON DELETE CASCADE,
    FOREIGN KEY (run_id, query_index)
        REFERENCES discovery_queries (run_id, query_index) ON DELETE CASCADE
);

CREATE TABLE discovery_manifests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id UUID NOT NULL REFERENCES discovery_runs(id) ON DELETE RESTRICT,
    version INTEGER NOT NULL CHECK (version > 0),
    status TEXT NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'approved')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    approved_at TIMESTAMPTZ,
    approved_by TEXT,
    UNIQUE (run_id, version),
    UNIQUE (run_id, id),
    CHECK ((status = 'approved') = (approved_at IS NOT NULL AND approved_by IS NOT NULL))
);

CREATE TABLE discovery_manifest_items (
    manifest_id UUID NOT NULL,
    run_id UUID NOT NULL,
    candidate_id UUID NOT NULL,
    decision TEXT NOT NULL DEFAULT 'undecided'
        CHECK (decision IN ('undecided', 'include', 'exclude')),
    reason TEXT,
    coverage_questions TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    reviewed_at TIMESTAMPTZ,
    CHECK (
        (decision = 'undecided' AND reason IS NULL AND reviewed_at IS NULL)
        OR (decision IN ('include', 'exclude') AND reason IS NOT NULL
            AND length(trim(reason)) > 0 AND reviewed_at IS NOT NULL)
    ),
    PRIMARY KEY (manifest_id, candidate_id),
    CHECK (
        coverage_questions <@ ARRAY[
            'hybrid_dense', 'reranking_latency', 'chunking_citation'
        ]::TEXT[]
    ),
    FOREIGN KEY (run_id, manifest_id)
        REFERENCES discovery_manifests (run_id, id) ON DELETE CASCADE,
    FOREIGN KEY (run_id, candidate_id)
        REFERENCES discovery_candidates (run_id, id) ON DELETE RESTRICT
);

CREATE TABLE discovery_manifest_coverage (
    manifest_id UUID NOT NULL REFERENCES discovery_manifests(id) ON DELETE CASCADE,
    question_key TEXT NOT NULL CHECK (
        question_key IN ('hybrid_dense', 'reranking_latency', 'chunking_citation')
    ),
    status TEXT NOT NULL CHECK (status IN ('covered', 'gap')),
    reviewer_note TEXT NOT NULL CHECK (length(trim(reviewer_note)) > 0),
    reviewed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (manifest_id, question_key)
);

CREATE FUNCTION prevent_approved_manifest_change() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    target_manifest_id UUID;
    target_status TEXT;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        SELECT status INTO target_status
        FROM discovery_manifests WHERE id = OLD.manifest_id FOR UPDATE;
        IF target_status = 'approved' THEN
            RAISE EXCEPTION 'items in an approved manifest are immutable';
        END IF;
    END IF;
    IF TG_OP <> 'DELETE' THEN
        target_manifest_id := NEW.manifest_id;
        SELECT status INTO target_status
        FROM discovery_manifests WHERE id = target_manifest_id FOR UPDATE;
        IF target_status = 'approved' THEN
            RAISE EXCEPTION 'items in an approved manifest are immutable';
        END IF;
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER discovery_manifest_items_immutable_after_approval
    BEFORE INSERT OR UPDATE OR DELETE ON discovery_manifest_items
    FOR EACH ROW EXECUTE FUNCTION prevent_approved_manifest_change();

CREATE TRIGGER discovery_manifest_coverage_immutable_after_approval
    BEFORE INSERT OR UPDATE OR DELETE ON discovery_manifest_coverage
    FOR EACH ROW EXECUTE FUNCTION prevent_approved_manifest_change();

CREATE FUNCTION prevent_approved_manifest_change_on_manifest() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.status = 'approved' THEN
        RAISE EXCEPTION 'an approved manifest is immutable';
    END IF;
    IF TG_OP = 'UPDATE' AND NEW.status = 'approved' THEN
        IF EXISTS (
            SELECT 1 FROM discovery_manifest_items
            WHERE manifest_id = OLD.id AND decision = 'undecided'
        ) OR NOT EXISTS (
            SELECT 1 FROM discovery_manifest_items
            WHERE manifest_id = OLD.id AND decision = 'include'
        ) OR (
            SELECT count(*) FROM discovery_manifest_coverage
            WHERE manifest_id = OLD.id
        ) <> 3 THEN
            RAISE EXCEPTION
                'manifest approval requires every decision and at least one inclusion';
        END IF;
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER discovery_manifests_immutable_after_approval
    BEFORE UPDATE OR DELETE ON discovery_manifests
    FOR EACH ROW EXECUTE FUNCTION prevent_approved_manifest_change_on_manifest();

CREATE INDEX idx_discovery_candidates_run_year
    ON discovery_candidates (run_id, publication_year);
CREATE INDEX idx_discovery_candidates_openalex_id
    ON discovery_candidates (openalex_id);
