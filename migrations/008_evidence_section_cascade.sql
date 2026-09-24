-- Phase 1: evidence rows cannot outlive their source section or extraction.

ALTER TABLE evidence_units
    DROP CONSTRAINT evidence_units_section_id_extraction_id_fkey,
    ADD CONSTRAINT evidence_units_section_extraction_fk
        FOREIGN KEY (section_id, extraction_id)
        REFERENCES sections (id, extraction_id) ON DELETE CASCADE;

ALTER TABLE evidence_tables
    DROP CONSTRAINT evidence_tables_section_id_extraction_id_fkey,
    ADD CONSTRAINT evidence_tables_section_extraction_fk
        FOREIGN KEY (section_id, extraction_id)
        REFERENCES sections (id, extraction_id) ON DELETE CASCADE;
