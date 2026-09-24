-- Phase 1: import only approved manifest members into logical paper records.

ALTER TABLE papers
    ALTER COLUMN title DROP NOT NULL;

ALTER TABLE unresolved_citations
    ADD COLUMN resolved_paper_id TEXT REFERENCES papers(id) ON DELETE RESTRICT,
    ADD COLUMN resolved_at TIMESTAMPTZ,
    ADD CONSTRAINT unresolved_citations_resolution_pair_check
        CHECK (
            (resolved_paper_id IS NULL AND resolved_at IS NULL)
            OR (resolved_paper_id IS NOT NULL AND resolved_at IS NOT NULL)
        );

ALTER TABLE collections
    ADD COLUMN discovery_manifest_id UUID UNIQUE
        REFERENCES discovery_manifests(id) ON DELETE RESTRICT,
    ADD CONSTRAINT collections_id_manifest_key
        UNIQUE (id, discovery_manifest_id);

ALTER TABLE snapshots
    ADD COLUMN discovery_manifest_id UUID
        REFERENCES discovery_manifests(id) ON DELETE RESTRICT;

CREATE TABLE manifest_paper_imports (
    manifest_id UUID NOT NULL,
    candidate_id UUID NOT NULL,
    paper_id TEXT NOT NULL REFERENCES papers(id) ON DELETE RESTRICT,
    collection_id UUID NOT NULL,
    imported_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (manifest_id, candidate_id),
    UNIQUE (manifest_id, paper_id),
    FOREIGN KEY (manifest_id, candidate_id)
        REFERENCES discovery_manifest_items (manifest_id, candidate_id)
        ON DELETE RESTRICT,
    FOREIGN KEY (collection_id, manifest_id)
        REFERENCES collections (id, discovery_manifest_id) ON DELETE RESTRICT
);

CREATE FUNCTION require_approved_manifest_inclusion_for_import()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    manifest_status TEXT;
    manifest_decision TEXT;
BEGIN
    SELECT manifest.status, item.decision
    INTO manifest_status, manifest_decision
    FROM discovery_manifests AS manifest
    JOIN discovery_manifest_items AS item
      ON item.manifest_id = manifest.id
    WHERE manifest.id = NEW.manifest_id
      AND item.candidate_id = NEW.candidate_id
    FOR UPDATE OF manifest;

    IF manifest_status IS DISTINCT FROM 'approved'
       OR manifest_decision IS DISTINCT FROM 'include' THEN
        RAISE EXCEPTION 'only approved included manifest candidates can be imported';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER manifest_paper_import_requires_approval
    BEFORE INSERT OR UPDATE ON manifest_paper_imports
    FOR EACH ROW EXECUTE FUNCTION require_approved_manifest_inclusion_for_import();
