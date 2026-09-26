-- Freeze exact snapshot chunk membership and record variant ancestry.

ALTER TABLE snapshot_items
    ADD CONSTRAINT snapshot_items_selection_reference_key
        UNIQUE (snapshot_id, paper_id, document_id, extraction_id);

ALTER TABLE chunks
    ADD CONSTRAINT chunks_snapshot_selection_reference_key
        UNIQUE (id, document_id, extraction_id);

CREATE TABLE snapshot_item_chunks (
    snapshot_id UUID NOT NULL,
    paper_id TEXT NOT NULL,
    document_id UUID NOT NULL,
    extraction_id UUID NOT NULL,
    chunk_id TEXT NOT NULL,
    PRIMARY KEY (snapshot_id, paper_id, chunk_id),
    UNIQUE (snapshot_id, chunk_id),
    FOREIGN KEY (snapshot_id, paper_id, document_id, extraction_id)
        REFERENCES snapshot_items (snapshot_id, paper_id, document_id, extraction_id)
        ON DELETE CASCADE,
    FOREIGN KEY (chunk_id, document_id, extraction_id)
        REFERENCES chunks (id, document_id, extraction_id) ON DELETE RESTRICT
);

CREATE INDEX snapshot_item_chunks_by_member
    ON snapshot_item_chunks (snapshot_id, paper_id);

-- Preserve the exact selection each existing snapshot resolved under migration 014.
INSERT INTO snapshot_item_chunks
    (snapshot_id, paper_id, document_id, extraction_id, chunk_id)
SELECT item.snapshot_id, item.paper_id, item.document_id, item.extraction_id, chunk.id
FROM snapshot_items item
JOIN chunks chunk
  ON chunk.document_id = item.document_id
 AND chunk.extraction_id = item.extraction_id
WHERE item.extraction_id IS NOT NULL
  AND (item.chunking_configuration_id IS NULL
       OR chunk.metadata ->> 'chunking_configuration_id' =
          item.chunking_configuration_id);

CREATE FUNCTION prevent_finalized_snapshot_chunk_selection_change() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    target_snapshot_id UUID;
    target_status TEXT;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        SELECT status INTO target_status
        FROM snapshots WHERE id = OLD.snapshot_id FOR UPDATE;
        IF target_status = 'finalized' THEN
            RAISE EXCEPTION 'chunk selection in a finalized snapshot is immutable';
        END IF;
    END IF;
    IF TG_OP <> 'DELETE' THEN
        target_snapshot_id := NEW.snapshot_id;
        SELECT status INTO target_status
        FROM snapshots WHERE id = target_snapshot_id FOR UPDATE;
        IF target_status = 'finalized' THEN
            RAISE EXCEPTION 'chunk selection in a finalized snapshot is immutable';
        END IF;
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER snapshot_item_chunks_immutable_after_finalize
    BEFORE INSERT OR UPDATE OR DELETE ON snapshot_item_chunks
    FOR EACH ROW EXECUTE FUNCTION prevent_finalized_snapshot_chunk_selection_change();

CREATE TABLE snapshot_variant_lineage (
    snapshot_id UUID PRIMARY KEY REFERENCES snapshots(id) ON DELETE CASCADE,
    parent_snapshot_id UUID NOT NULL REFERENCES snapshots(id) ON DELETE RESTRICT,
    parent_chunk_selection_id TEXT NOT NULL
        CHECK (parent_chunk_selection_id ~ '^sha256:[0-9a-f]{64}$'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (snapshot_id <> parent_snapshot_id)
);

CREATE INDEX snapshot_variant_lineage_by_parent
    ON snapshot_variant_lineage (parent_snapshot_id);

CREATE FUNCTION protect_snapshot_variant_lineage() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    child_status TEXT;
    parent_status TEXT;
BEGIN
    IF TG_OP = 'INSERT' THEN
        SELECT status INTO child_status
        FROM snapshots WHERE id = NEW.snapshot_id FOR UPDATE;
        SELECT status INTO parent_status
        FROM snapshots WHERE id = NEW.parent_snapshot_id FOR SHARE;
        IF child_status IS DISTINCT FROM 'draft' THEN
            RAISE EXCEPTION 'a snapshot variant must start as a draft';
        END IF;
        IF parent_status IS DISTINCT FROM 'finalized' THEN
            RAISE EXCEPTION 'a snapshot variant parent must be finalized';
        END IF;
        RETURN NEW;
    END IF;

    IF TG_OP = 'UPDATE' THEN
        RAISE EXCEPTION 'snapshot variant ancestry is immutable';
    END IF;

    SELECT status INTO child_status
    FROM snapshots WHERE id = OLD.snapshot_id FOR UPDATE;
    IF child_status = 'finalized' THEN
        RAISE EXCEPTION 'lineage of a finalized variant is immutable';
    END IF;
    RETURN OLD;
END;
$$;

CREATE TRIGGER snapshot_variant_lineage_immutable_after_finalize
    BEFORE INSERT OR UPDATE OR DELETE ON snapshot_variant_lineage
    FOR EACH ROW EXECUTE FUNCTION protect_snapshot_variant_lineage();
