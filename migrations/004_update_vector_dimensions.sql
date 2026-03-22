-- Update vector columns from 384 dimensions (sentence-transformers)
-- to 1536 dimensions (OpenRouter openai/text-embedding-3-small).
-- Safe to run on empty tables; existing data will be dropped.

-- Drop existing IVFFlat indexes (they reference the old dimension)
DROP INDEX IF EXISTS ideas_embedding_idx;
DROP INDEX IF EXISTS seed_corpus_embedding_idx;

-- Alter vector columns to new dimension
ALTER TABLE ideas
    ALTER COLUMN embedding TYPE vector(1536);

ALTER TABLE seed_corpus
    ALTER COLUMN embedding TYPE vector(1536);

-- Recreate IVFFlat indexes with new dimension
CREATE INDEX ideas_embedding_idx ON ideas
    USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 10);

CREATE INDEX seed_corpus_embedding_idx ON seed_corpus
    USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 10);
