CREATE TABLE papers (
    id              TEXT PRIMARY KEY,
    title           TEXT NOT NULL,
    abstract        TEXT NOT NULL,
    authors         TEXT[],
    categories      TEXT[],
    url             TEXT NOT NULL,
    source          TEXT NOT NULL DEFAULT 'arxiv',
    published_at    TIMESTAMPTZ,
    fetched_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    relevance_score FLOAT,
    keyword_hits    TEXT[],
    processed       BOOLEAN NOT NULL DEFAULT FALSE,
    skipped         BOOLEAN NOT NULL DEFAULT FALSE,
    skip_reason     TEXT
);

CREATE TABLE ideas (
    id                  SERIAL PRIMARY KEY,
    paper_id            TEXT NOT NULL REFERENCES papers(id),
    hypothesis          TEXT NOT NULL,
    method              TEXT NOT NULL,
    dataset             TEXT NOT NULL,
    novelty_score       INT NOT NULL CHECK (novelty_score BETWEEN 1 AND 10),
    feasibility_score   INT NOT NULL CHECK (feasibility_score BETWEEN 1 AND 10),
    combined_score      INT GENERATED ALWAYS AS (novelty_score + feasibility_score) STORED,
    sent_at             TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE idea_feedback (
    id          SERIAL PRIMARY KEY,
    idea_id     INT NOT NULL REFERENCES ideas(id),
    user_id     BIGINT NOT NULL,
    feedback    SMALLINT NOT NULL CHECK (feedback IN (-1, 1)),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (idea_id, user_id)
);

CREATE TABLE allowed_users (
    user_id     BIGINT PRIMARY KEY,
    username    TEXT,
    first_name  TEXT,
    paused      BOOLEAN NOT NULL DEFAULT FALSE,
    pause_until TIMESTAMPTZ,
    added_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE topic_weights (
    topic       TEXT PRIMARY KEY,
    weight      FLOAT NOT NULL DEFAULT 1.0,
    hit_count   INT NOT NULL DEFAULT 0,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Performance indexes
CREATE INDEX idx_papers_processed     ON papers (processed, fetched_at DESC);
CREATE INDEX idx_papers_relevance     ON papers (relevance_score DESC) WHERE NOT processed AND NOT skipped;
CREATE INDEX idx_ideas_sent_at        ON ideas (sent_at DESC);
CREATE INDEX idx_feedback_idea        ON idea_feedback (idea_id);
CREATE INDEX idx_feedback_user        ON idea_feedback (user_id);
