-- Phase 3.5: index generations, one published pointer per collection and index
-- configuration, and the generation a research run reads (ADR-0023).

CREATE TABLE index_generations (
    collection_id UUID NOT NULL REFERENCES collections (id) ON DELETE RESTRICT,
    configuration_id TEXT NOT NULL
        REFERENCES index_configurations (configuration_id) ON DELETE RESTRICT,
    generation INTEGER NOT NULL CHECK (generation >= 1),
    snapshot_id UUID NOT NULL REFERENCES snapshots (id) ON DELETE RESTRICT,
    parent_generation INTEGER,
    manifest_sha256 TEXT NOT NULL CHECK (manifest_sha256 ~ '^[0-9a-f]{64}$'),
    state TEXT NOT NULL
        CHECK (state IN ('building', 'verified', 'published', 'failed')),
    point_count INTEGER NOT NULL DEFAULT 0 CHECK (point_count >= 0),
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (collection_id, configuration_id, generation),
    UNIQUE (configuration_id, snapshot_id),
    CHECK ((generation = 1) = (parent_generation IS NULL)),
    CHECK (parent_generation IS NULL OR parent_generation = generation - 1)
);

CREATE TABLE index_generation_pointers (
    collection_id UUID NOT NULL,
    configuration_id TEXT NOT NULL,
    published_generation INTEGER NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (collection_id, configuration_id),
    FOREIGN KEY (collection_id, configuration_id, published_generation)
        REFERENCES index_generations (collection_id, configuration_id, generation)
);

ALTER TABLE research_runs
    ADD COLUMN generation INTEGER CHECK (generation IS NULL OR generation >= 1);
