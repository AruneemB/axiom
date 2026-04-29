-- Migration 009: Security hardening tables
--
-- Adds two tables to support rate limiting, burst protection,
-- abuse detection, and security audit logging for the Telegram bot.

-- ---------------------------------------------------------------------------
-- rate_limit_events
-- Unified sliding-window store. No FK to allowed_users — burst checks
-- fire before the whitelist check, so unknown user_ids must be insertable.
-- ---------------------------------------------------------------------------
CREATE TABLE rate_limit_events (
    id             BIGSERIAL    PRIMARY KEY,
    user_id        BIGINT       NOT NULL,
    command        TEXT         NOT NULL DEFAULT '',
    ts             TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    violation_type TEXT         -- NULL = normal tracking; non-NULL = abuse event
);

CREATE INDEX idx_rle_user_ts
    ON rate_limit_events (user_id, ts DESC);

CREATE INDEX idx_rle_user_command_ts
    ON rate_limit_events (user_id, command, ts DESC);

CREATE INDEX idx_rle_user_violation_ts
    ON rate_limit_events (user_id, violation_type, ts DESC)
    WHERE violation_type IS NOT NULL;

-- ---------------------------------------------------------------------------
-- security_audit_log
-- Append-only record of significant security events for monitoring.
-- user_id is nullable so pre-auth events (IP rejection) can be logged.
-- ---------------------------------------------------------------------------
CREATE TABLE security_audit_log (
    id          BIGSERIAL    PRIMARY KEY,
    user_id     BIGINT,
    event_type  TEXT         NOT NULL,
    details     TEXT,
    ip_addr     TEXT,
    ts          TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_sal_event_ts
    ON security_audit_log (event_type, ts DESC);

CREATE INDEX idx_sal_user_ts
    ON security_audit_log (user_id, ts DESC)
    WHERE user_id IS NOT NULL;
