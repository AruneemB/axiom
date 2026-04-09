-- Migration 006: Add conversation tables for chat feature

-- Conversation sessions
CREATE TABLE conversation_sessions (
    id              SERIAL PRIMARY KEY,
    user_id         BIGINT NOT NULL REFERENCES allowed_users(user_id),
    paper_id        TEXT REFERENCES papers(id),
    idea_id         INT REFERENCES ideas(id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at      TIMESTAMPTZ NOT NULL DEFAULT NOW() + INTERVAL '2 hours',
    message_count   INT NOT NULL DEFAULT 0,
    CONSTRAINT valid_message_count CHECK (message_count >= 0 AND message_count <= 20)
);

CREATE INDEX idx_sessions_user_active
    ON conversation_sessions (user_id, expires_at DESC)
    WHERE expires_at > NOW();

CREATE INDEX idx_sessions_expiration
    ON conversation_sessions (expires_at)
    WHERE expires_at > NOW();

-- Conversation messages
CREATE TABLE conversation_messages (
    id              SERIAL PRIMARY KEY,
    session_id      INT NOT NULL REFERENCES conversation_sessions(id) ON DELETE CASCADE,
    role            TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content         TEXT NOT NULL,
    tokens_used     INT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT valid_content_length CHECK (LENGTH(content) <= 5000)
);

CREATE INDEX idx_messages_session
    ON conversation_messages (session_id, created_at);
