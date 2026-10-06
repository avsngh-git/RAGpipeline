-- Phase 3.5: append-only term IDs for scientific BM25 sparse vectors (ADR-0022).

CREATE TABLE lexical_vocabularies (
    vocabulary_id TEXT PRIMARY KEY,
    analyzer TEXT NOT NULL,
    analyzer_revision TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE lexical_terms (
    vocabulary_id TEXT NOT NULL
        REFERENCES lexical_vocabularies (vocabulary_id) ON DELETE RESTRICT,
    term TEXT NOT NULL,
    term_id INTEGER NOT NULL CHECK (term_id >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (vocabulary_id, term),
    UNIQUE (vocabulary_id, term_id)
);

CREATE FUNCTION prevent_lexical_term_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'lexical term IDs are append-only';
END;
$$;

CREATE TRIGGER lexical_terms_append_only
    BEFORE UPDATE OR DELETE ON lexical_terms
    FOR EACH ROW EXECUTE FUNCTION prevent_lexical_term_change();
