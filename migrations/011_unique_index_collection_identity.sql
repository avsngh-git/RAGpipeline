-- Phase 1: one Qdrant collection belongs to exactly one embedding configuration.

CREATE UNIQUE INDEX index_configurations_collection_name_unique
    ON index_configurations ((configuration ->> 'collection_name'));
