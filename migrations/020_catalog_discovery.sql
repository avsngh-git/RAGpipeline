CREATE TABLE paper_metadata_revisions (
    paper_id TEXT NOT NULL REFERENCES papers (id) ON DELETE RESTRICT,
    revision INTEGER NOT NULL CHECK (revision >= 1),
    source TEXT NOT NULL CHECK (source = 'openalex'),
    metadata JSONB NOT NULL,
    metadata_sha256 TEXT NOT NULL CHECK (metadata_sha256 ~ '^[0-9a-f]{64}$'),
    retrieved_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (paper_id, revision)
);

CREATE TABLE discovery_spend (
    id BIGSERIAL PRIMARY KEY,
    spend_date DATE NOT NULL DEFAULT current_date,
    run_id UUID REFERENCES research_runs (id) ON DELETE SET NULL,
    kind TEXT NOT NULL CHECK (kind IN ('search_request', 'content_download')),
    cost_usd NUMERIC(8, 4) NOT NULL CHECK (cost_usd >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_discovery_spend_date ON discovery_spend (spend_date);
CREATE INDEX idx_discovery_spend_run ON discovery_spend (run_id, kind);

ALTER TABLE research_run_evidence
    DROP CONSTRAINT research_run_evidence_chunk_id_fkey,
    ADD COLUMN evidence_kind TEXT NOT NULL DEFAULT 'chunk'
        CHECK (evidence_kind IN ('chunk', 'abstract')),
    ADD CONSTRAINT research_run_evidence_abstract_id_check
        CHECK ((evidence_kind = 'abstract') = (chunk_id LIKE 'abstract:%'));

ALTER TABLE claim_evidence DROP CONSTRAINT claim_evidence_chunk_id_fkey;

CREATE FUNCTION require_known_run_evidence_chunk()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.evidence_kind = 'chunk'
       AND NOT EXISTS (SELECT 1 FROM chunks WHERE id = NEW.chunk_id) THEN
        RAISE EXCEPTION 'research run evidence chunk does not exist'
            USING ERRCODE = 'foreign_key_violation';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER research_run_evidence_chunk_exists
    BEFORE INSERT OR UPDATE OF chunk_id, evidence_kind ON research_run_evidence
    FOR EACH ROW EXECUTE FUNCTION require_known_run_evidence_chunk();

CREATE FUNCTION require_known_claim_evidence_source()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF EXISTS (SELECT 1 FROM chunks WHERE id = NEW.chunk_id) THEN
        RETURN NEW;
    END IF;

    IF NEW.chunk_id LIKE 'abstract:%' AND EXISTS (
        SELECT 1
        FROM claims AS claim
        JOIN research_run_evidence AS evidence ON evidence.run_id = claim.run_id
        WHERE claim.id = NEW.claim_id
          AND evidence.chunk_id = NEW.chunk_id
          AND evidence.evidence_kind = 'abstract'
    ) THEN
        RETURN NEW;
    END IF;

    RAISE EXCEPTION 'claim evidence must reference a chunk or run-local abstract'
        USING ERRCODE = 'foreign_key_violation';
END;
$$;

CREATE TRIGGER claim_evidence_source_exists
    BEFORE INSERT OR UPDATE OF claim_id, chunk_id ON claim_evidence
    FOR EACH ROW EXECUTE FUNCTION require_known_claim_evidence_source();
