-- Migration 008: Add doc_chunks table for RAG-powered site chatbot
-- Stores chunked markdown documentation with vector embeddings for semantic retrieval.

CREATE TABLE IF NOT EXISTS doc_chunks (
    id         SERIAL PRIMARY KEY,
    source     TEXT NOT NULL,         -- e.g. "docs-axiom/AXIOM-SPEC.md"
    heading    TEXT,                  -- nearest H2/H3 heading above this chunk
    content    TEXT NOT NULL,         -- chunk text (~800 chars)
    embedding  vector(1536),
    indexed_at TIMESTAMPTZ DEFAULT NOW()
);

-- HNSW handles incremental inserts correctly; ivfflat centroids degrade on an
-- initially empty table and require REINDEX after each full load.
CREATE INDEX IF NOT EXISTS doc_chunks_embedding_idx
    ON doc_chunks USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 200);
