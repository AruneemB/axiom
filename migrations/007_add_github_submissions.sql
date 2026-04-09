-- Migration 007: Add GitHub submissions table

-- GitHub issue submissions
CREATE TABLE github_submissions (
    id              SERIAL PRIMARY KEY,
    user_id         BIGINT NOT NULL REFERENCES allowed_users(user_id),
    issue_number    INT NOT NULL,
    issue_url       TEXT NOT NULL,
    title           TEXT NOT NULL,
    description     TEXT NOT NULL,
    context_data    JSONB,
    validation_flags JSONB,
    submitted_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_submissions_user
    ON github_submissions (user_id, submitted_at DESC);

CREATE INDEX idx_submissions_date
    ON github_submissions (submitted_at DESC);

CREATE INDEX idx_submissions_issue
    ON github_submissions (issue_number);
