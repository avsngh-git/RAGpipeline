-- Phase 1: tie parsed evidence to the exact reviewed source artifact.

ALTER TABLE document_artifacts
    ADD CONSTRAINT document_artifacts_document_id_id_key
        UNIQUE (document_id, id);

ALTER TABLE extractions
    ADD COLUMN source_artifact_id UUID,
    ADD CONSTRAINT extractions_source_artifact_document_fk
        FOREIGN KEY (document_id, source_artifact_id)
        REFERENCES document_artifacts (document_id, id) ON DELETE CASCADE;
