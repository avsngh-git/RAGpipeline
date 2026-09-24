-- Phase 1: retain immutable, reviewed rights evidence per source/version.

CREATE TABLE document_permission_evidence (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    source_name TEXT NOT NULL CHECK (length(btrim(source_name)) > 0),
    source_url TEXT NOT NULL CHECK (length(btrim(source_url)) > 0),
    license_id TEXT NOT NULL CHECK (length(btrim(license_id)) > 0),
    terms_url TEXT NOT NULL CHECK (length(btrim(terms_url)) > 0),
    permission_basis TEXT NOT NULL CHECK (length(btrim(permission_basis)) > 0),
    reviewer TEXT NOT NULL CHECK (length(btrim(reviewer)) > 0),
    checked_at TIMESTAMPTZ NOT NULL,
    storage_permitted BOOLEAN NOT NULL,
    indexing_permitted BOOLEAN NOT NULL,
    passage_display_permitted BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (document_id, id),
    UNIQUE (document_id, source_name, source_url, license_id, checked_at, reviewer),
    CHECK (NOT indexing_permitted OR storage_permitted),
    CHECK (NOT passage_display_permitted OR indexing_permitted)
);

ALTER TABLE document_artifacts
    ADD COLUMN permission_evidence_id UUID,
    ADD CONSTRAINT document_artifacts_permission_evidence_fk
        FOREIGN KEY (document_id, permission_evidence_id)
        REFERENCES document_permission_evidence (document_id, id)
        ON DELETE RESTRICT,
    ADD CONSTRAINT document_artifact_indexing_requires_storage
        CHECK (NOT indexing_permitted OR storage_permitted),
    ADD CONSTRAINT document_artifact_display_requires_indexing
        CHECK (NOT passage_display_permitted OR indexing_permitted),
    ADD CONSTRAINT document_artifact_permission_basis_nonempty
        CHECK (length(btrim(permission_basis)) > 0);

CREATE FUNCTION prevent_document_permission_evidence_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'document permission evidence is immutable';
END;
$$;

CREATE TRIGGER document_permission_evidence_immutable
    BEFORE UPDATE OR DELETE ON document_permission_evidence
    FOR EACH ROW EXECUTE FUNCTION prevent_document_permission_evidence_mutation();
