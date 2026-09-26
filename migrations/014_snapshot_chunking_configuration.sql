-- Track the active searchable chunk set independently from immutable extraction output.

ALTER TABLE snapshot_items
    ADD COLUMN chunking_configuration_id TEXT
        CHECK (
            chunking_configuration_id IS NULL
            OR chunking_configuration_id ~ '^sha256:[0-9a-f]{64}$'
        );
