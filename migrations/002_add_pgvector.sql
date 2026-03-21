CREATE EXTENSION IF NOT EXISTS vector;

ALTER TABLE ideas
    ADD COLUMN embedding vector(384);

CREATE TABLE seed_corpus (
    id          SERIAL PRIMARY KEY,
    title       TEXT NOT NULL,
    abstract    TEXT NOT NULL,
    embedding   vector(384) NOT NULL,
    added_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX ON ideas
    USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 10);

CREATE INDEX ON seed_corpus
    USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 10);
