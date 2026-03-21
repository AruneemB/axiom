ALTER TABLE papers
    ADD COLUMN embedding vector(384);

CREATE INDEX ON papers
    USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 10);
