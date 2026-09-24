-- Phase 1: provenance, extraction lineage, unresolved citations and snapshots.

CREATE TABLE paper_identifiers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    paper_id TEXT NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    namespace TEXT NOT NULL,
    identifier TEXT NOT NULL,
    normalized_identifier TEXT NOT NULL,
    verification_method TEXT NOT NULL,
    verified_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (namespace, normalized_identifier)
);

CREATE INDEX idx_paper_identifiers_paper_id ON paper_identifiers (paper_id);

CREATE TABLE unresolved_citations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    citing_paper_id TEXT NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    target_namespace TEXT NOT NULL,
    target_identifier TEXT NOT NULL,
    source TEXT NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (citing_paper_id, target_namespace, target_identifier, source)
);

ALTER TABLE documents
    ADD COLUMN version_kind TEXT NOT NULL DEFAULT 'unknown'
        CHECK (version_kind IN ('published', 'preprint', 'other', 'unknown')),
    ADD COLUMN published_at DATE,
    ADD COLUMN metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD CONSTRAINT documents_id_paper_id_key UNIQUE (id, paper_id);

CREATE TABLE artifacts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    sha256 TEXT NOT NULL UNIQUE CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    storage_path TEXT NOT NULL UNIQUE,
    byte_size BIGINT NOT NULL CHECK (byte_size >= 0),
    media_type TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE document_artifacts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    artifact_id UUID NOT NULL REFERENCES artifacts(id) ON DELETE RESTRICT,
    role TEXT NOT NULL,
    source_name TEXT NOT NULL,
    source_url TEXT NOT NULL,
    acquired_at TIMESTAMPTZ NOT NULL,
    permission_basis TEXT NOT NULL,
    storage_permitted BOOLEAN NOT NULL,
    indexing_permitted BOOLEAN NOT NULL,
    passage_display_permitted BOOLEAN NOT NULL DEFAULT FALSE,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (document_id, artifact_id, role, source_url)
);

CREATE INDEX idx_document_artifacts_artifact_id
    ON document_artifacts (artifact_id);

CREATE TABLE extractions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    extractor_name TEXT NOT NULL,
    extractor_revision TEXT NOT NULL,
    configuration_id TEXT NOT NULL,
    configuration JSONB NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN ('pending', 'running', 'completed', 'failed', 'partial')
    ),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ,
    UNIQUE (document_id, configuration_id),
    UNIQUE (document_id, id)
);

ALTER TABLE sections
    DROP CONSTRAINT IF EXISTS sections_document_id_ordinal_key,
    ADD COLUMN extraction_id UUID,
    ADD COLUMN source_location JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD CONSTRAINT sections_document_extraction_fk
        FOREIGN KEY (document_id, extraction_id)
        REFERENCES extractions (document_id, id) ON DELETE CASCADE,
    ADD CONSTRAINT sections_id_extraction_key UNIQUE (id, extraction_id),
    ADD CONSTRAINT sections_document_extraction_ordinal_key
        UNIQUE (document_id, extraction_id, ordinal);

ALTER TABLE chunks
    ADD COLUMN extraction_id UUID,
    ADD COLUMN kind TEXT NOT NULL DEFAULT 'text'
        CHECK (kind IN ('text', 'table', 'table_row_group', 'caption', 'figure', 'equation')),
    ADD COLUMN source_location JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD CONSTRAINT chunks_document_extraction_fk
        FOREIGN KEY (document_id, extraction_id)
        REFERENCES extractions (document_id, id) ON DELETE CASCADE,
    ADD CONSTRAINT chunks_section_extraction_fk
        FOREIGN KEY (section_id, extraction_id)
        REFERENCES sections (id, extraction_id) ON DELETE RESTRICT;

CREATE TABLE evidence_units (
    id TEXT PRIMARY KEY,
    extraction_id UUID NOT NULL REFERENCES extractions(id) ON DELETE CASCADE,
    section_id UUID,
    kind TEXT NOT NULL CHECK (
        kind IN ('text', 'table', 'table_row_group', 'caption', 'figure', 'equation')
    ),
    content TEXT NOT NULL,
    start_offset INTEGER,
    end_offset INTEGER,
    source_location JSONB NOT NULL DEFAULT '{}'::jsonb,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    CHECK (start_offset IS NULL OR start_offset >= 0),
    CHECK (end_offset IS NULL OR end_offset >= 0),
    CHECK (start_offset IS NULL OR end_offset IS NULL OR start_offset <= end_offset),
    FOREIGN KEY (section_id, extraction_id)
        REFERENCES sections (id, extraction_id) ON DELETE SET NULL
);

CREATE INDEX idx_evidence_units_extraction_id
    ON evidence_units (extraction_id);

CREATE TABLE evidence_tables (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    extraction_id UUID NOT NULL REFERENCES extractions(id) ON DELETE CASCADE,
    section_id UUID,
    ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
    caption TEXT,
    units TEXT,
    footnotes JSONB NOT NULL DEFAULT '[]'::jsonb
        CHECK (jsonb_typeof(footnotes) = 'array'),
    table_data JSONB NOT NULL CHECK (jsonb_typeof(table_data) = 'object'),
    source_location JSONB NOT NULL DEFAULT '{}'::jsonb,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    FOREIGN KEY (section_id, extraction_id)
        REFERENCES sections (id, extraction_id) ON DELETE SET NULL,
    UNIQUE (extraction_id, ordinal)
);

CREATE TABLE ingestion_stage_attempts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id UUID NOT NULL REFERENCES ingestion_jobs(id) ON DELETE CASCADE,
    document_id UUID REFERENCES documents(id) ON DELETE SET NULL,
    stage TEXT NOT NULL,
    attempt_number INTEGER NOT NULL CHECK (attempt_number > 0),
    status TEXT NOT NULL CHECK (
        status IN ('pending', 'running', 'completed', 'failed', 'skipped')
    ),
    configuration_id TEXT NOT NULL,
    input_fingerprint TEXT NOT NULL,
    output_references JSONB NOT NULL DEFAULT '{}'::jsonb,
    failure_category TEXT,
    error_message TEXT,
    retryable BOOLEAN,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    duration_ms BIGINT CHECK (duration_ms IS NULL OR duration_ms >= 0),
    resource_measurements JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (job_id, document_id, stage, attempt_number)
);

CREATE INDEX idx_ingestion_stage_attempts_job_stage
    ON ingestion_stage_attempts (job_id, stage, status);

ALTER TABLE ingestion_jobs
    ADD COLUMN configuration_id TEXT,
    ADD COLUMN code_revision TEXT,
    ADD COLUMN execution_profile TEXT,
    ADD COLUMN owner_token UUID,
    ADD COLUMN lease_expires_at TIMESTAMPTZ,
    ADD COLUMN storage_limit_bytes BIGINT
        CHECK (storage_limit_bytes IS NULL OR storage_limit_bytes > 0);

CREATE TABLE snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'finalized')),
    configuration_id TEXT NOT NULL,
    configuration JSONB NOT NULL,
    code_revision TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finalized_at TIMESTAMPTZ,
    CHECK ((status = 'finalized') = (finalized_at IS NOT NULL))
);

CREATE TABLE snapshot_items (
    snapshot_id UUID NOT NULL REFERENCES snapshots(id) ON DELETE RESTRICT,
    paper_id TEXT NOT NULL REFERENCES papers(id) ON DELETE RESTRICT,
    document_id UUID NOT NULL,
    extraction_id UUID,
    selection_reason TEXT NOT NULL,
    selected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (snapshot_id, paper_id),
    FOREIGN KEY (document_id, paper_id)
        REFERENCES documents (id, paper_id) ON DELETE RESTRICT,
    FOREIGN KEY (document_id, extraction_id)
        REFERENCES extractions (document_id, id) ON DELETE RESTRICT
);

CREATE FUNCTION prevent_finalized_snapshot_item_change() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    target_snapshot_id UUID;
    target_status TEXT;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        SELECT status INTO target_status
        FROM snapshots WHERE id = OLD.snapshot_id FOR UPDATE;
        IF target_status = 'finalized' THEN
            RAISE EXCEPTION 'items in a finalized snapshot are immutable';
        END IF;
    END IF;
    IF TG_OP <> 'DELETE' THEN
        target_snapshot_id := NEW.snapshot_id;
        SELECT status INTO target_status
        FROM snapshots WHERE id = target_snapshot_id FOR UPDATE;
        IF target_status = 'finalized' THEN
            RAISE EXCEPTION 'items in a finalized snapshot are immutable';
        END IF;
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER snapshot_items_immutable_after_finalize
    BEFORE INSERT OR UPDATE OR DELETE ON snapshot_items
    FOR EACH ROW EXECUTE FUNCTION prevent_finalized_snapshot_item_change();

CREATE FUNCTION prevent_finalized_snapshot_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.status = 'finalized' THEN
        RAISE EXCEPTION 'a finalized snapshot is immutable';
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER snapshots_immutable_after_finalize
    BEFORE UPDATE OR DELETE ON snapshots
    FOR EACH ROW EXECUTE FUNCTION prevent_finalized_snapshot_change();

CREATE TABLE index_configurations (
    configuration_id TEXT PRIMARY KEY,
    configuration JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE snapshot_index_states (
    snapshot_id UUID NOT NULL REFERENCES snapshots(id) ON DELETE RESTRICT,
    configuration_id TEXT NOT NULL REFERENCES index_configurations(configuration_id),
    collection_name TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN ('pending', 'building', 'ready', 'reconciliation_required', 'failed')
    ),
    expected_count INTEGER NOT NULL DEFAULT 0 CHECK (expected_count >= 0),
    indexed_count INTEGER NOT NULL DEFAULT 0 CHECK (indexed_count >= 0),
    reconciled_at TIMESTAMPTZ,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (snapshot_id, configuration_id)
);
