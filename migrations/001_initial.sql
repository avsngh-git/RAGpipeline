CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS collections (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL UNIQUE,
    description TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS papers (
    id TEXT PRIMARY KEY,
    openalex_id TEXT UNIQUE,
    title TEXT NOT NULL,
    publication_year INTEGER,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS authors (
    id BIGSERIAL PRIMARY KEY,
    openalex_id TEXT UNIQUE,
    display_name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS paper_authors (
    paper_id TEXT NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    author_id BIGINT NOT NULL REFERENCES authors(id) ON DELETE CASCADE,
    author_position INTEGER NOT NULL,
    PRIMARY KEY (paper_id, author_id),
    UNIQUE (paper_id, author_position)
);

CREATE TABLE IF NOT EXISTS citations (
    citing_paper_id TEXT NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    cited_paper_id TEXT NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    source TEXT NOT NULL DEFAULT 'openalex',
    PRIMARY KEY (citing_paper_id, cited_paper_id)
);

CREATE TABLE IF NOT EXISTS documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    paper_id TEXT NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    source_type TEXT NOT NULL,
    source_url TEXT,
    version TEXT NOT NULL,
    checksum TEXT,
    status TEXT NOT NULL DEFAULT 'metadata_only',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (paper_id, source_type, version)
);

CREATE TABLE IF NOT EXISTS sections (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    ordinal INTEGER NOT NULL,
    UNIQUE (document_id, ordinal)
);

CREATE TABLE IF NOT EXISTS chunks (
    id TEXT PRIMARY KEY,
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    section_id UUID REFERENCES sections(id) ON DELETE SET NULL,
    text TEXT NOT NULL,
    start_offset INTEGER,
    end_offset INTEGER,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS collection_papers (
    collection_id UUID NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
    paper_id TEXT NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    inclusion_reason TEXT,
    PRIMARY KEY (collection_id, paper_id)
);

CREATE TABLE IF NOT EXISTS ingestion_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    collection_id UUID REFERENCES collections(id) ON DELETE SET NULL,
    status TEXT NOT NULL,
    configuration JSONB NOT NULL DEFAULT '{}'::jsonb,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ingestion_documents (
    job_id UUID NOT NULL REFERENCES ingestion_jobs(id) ON DELETE CASCADE,
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    status TEXT NOT NULL,
    stage TEXT,
    error_message TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (job_id, document_id)
);

CREATE TABLE IF NOT EXISTS research_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    question TEXT NOT NULL,
    status TEXT NOT NULL,
    configuration_id TEXT,
    trace_id TEXT,
    answer TEXT,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS tool_calls (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id UUID NOT NULL REFERENCES research_runs(id) ON DELETE CASCADE,
    tool_name TEXT NOT NULL,
    arguments JSONB NOT NULL DEFAULT '{}'::jsonb,
    result JSONB,
    status TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS claims (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id UUID NOT NULL REFERENCES research_runs(id) ON DELETE CASCADE,
    claim_text TEXT NOT NULL,
    ordinal INTEGER NOT NULL,
    UNIQUE (run_id, ordinal)
);

CREATE TABLE IF NOT EXISTS claim_evidence (
    claim_id UUID NOT NULL REFERENCES claims(id) ON DELETE CASCADE,
    chunk_id TEXT NOT NULL REFERENCES chunks(id) ON DELETE RESTRICT,
    PRIMARY KEY (claim_id, chunk_id)
);

CREATE INDEX IF NOT EXISTS idx_documents_paper_id ON documents (paper_id);
CREATE INDEX IF NOT EXISTS idx_chunks_document_id ON chunks (document_id);
CREATE INDEX IF NOT EXISTS idx_citations_cited_paper_id
    ON citations (cited_paper_id);
CREATE INDEX IF NOT EXISTS idx_research_runs_status ON research_runs (status);
