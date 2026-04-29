"""
Rate limiting and abuse detection for the Telegram bot.

Provides burst protection, per-command sliding-window limits,
violation recording, and automatic account suspension.
All state is persisted in the rate_limit_events table so limits
survive serverless cold starts.
"""

from typing import Tuple

# Per-command hourly message limits.
# /chat and /report are NOT listed — they have their own subsystems.
COMMAND_LIMITS: dict[str, int] = {
    "/start":    30,
    "/status":   30,
    "/topics":   30,
    "/pause":    30,
    "/resume":   30,
    "/feedback": 30,
    "/context":  30,
    "/spark":     6,  # safety net; the 10-min spark check still runs too
    "callback":  60,
    "text":      30,
}
DEFAULT_LIMIT = 30

BURST_LIMIT = 10          # max messages per BURST_WINDOW_SECS
BURST_WINDOW_SECS = 60

VIOLATION_THRESHOLD = 5   # violations in 24 h before auto-suspend
SUSPEND_HOURS = 1


def check_burst_limit(user_id: int, conn) -> Tuple[bool, str]:
    """
    Return (True, "") if the user is within the burst limit,
    (False, msg) if they have exceeded it.
    Inserts a tracking row on success (commit immediately).
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*) AS cnt
            FROM rate_limit_events
            WHERE user_id = %s
              AND command = '__burst__'
              AND ts > NOW() - INTERVAL '60 seconds'
            """,
            (user_id,),
        )
        cnt = cur.fetchone()["cnt"]

    if cnt >= BURST_LIMIT:
        return False, "Too many messages. Please slow down."

    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO rate_limit_events (user_id, command) VALUES (%s, %s)",
            (user_id, "__burst__"),
        )
    conn.commit()
    return True, ""


def check_global_rate_limit(user_id: int, command: str, conn) -> Tuple[bool, str]:
    """
    Return (True, "") if the user is within the hourly limit for command,
    (False, msg) if they have exceeded it.
    Inserts a tracking row on success (commit immediately).
    """
    limit = COMMAND_LIMITS.get(command, DEFAULT_LIMIT)

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*) AS cnt
            FROM rate_limit_events
            WHERE user_id = %s
              AND command = %s
              AND ts > NOW() - INTERVAL '1 hour'
            """,
            (user_id, command),
        )
        cnt = cur.fetchone()["cnt"]

    if cnt >= limit:
        return False, f"You've reached the limit for this command ({limit}/hour). Please wait before trying again."

    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO rate_limit_events (user_id, command) VALUES (%s, %s)",
            (user_id, command),
        )
    conn.commit()
    return True, ""


def record_violation(user_id: int, violation_type: str, conn) -> None:
    """Persist an abuse event to rate_limit_events for suspension tracking."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO rate_limit_events (user_id, command, violation_type)
            VALUES (%s, %s, %s)
            """,
            (user_id, "", violation_type),
        )
    conn.commit()


def check_auto_suspend(user_id: int, conn) -> bool:
    """
    Count violations in the last 24 hours. If >= VIOLATION_THRESHOLD,
    pause the user for SUSPEND_HOURS hours.

    Returns True only when THIS call triggers the suspension (so the
    caller can send exactly one notification message).
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*) AS cnt
            FROM rate_limit_events
            WHERE user_id = %s
              AND violation_type IS NOT NULL
              AND ts > NOW() - INTERVAL '24 hours'
            """,
            (user_id,),
        )
        cnt = cur.fetchone()["cnt"]

    if cnt < VIOLATION_THRESHOLD:
        return False

    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE allowed_users
               SET paused = TRUE,
                   pause_until = NOW() + INTERVAL '1 hour'
             WHERE user_id = %s
               AND (pause_until IS NULL OR pause_until < NOW())
            """,
            (user_id,),
        )
        triggered = cur.rowcount == 1
    conn.commit()
    return triggered


def purge_old_events(conn) -> int:
    """Delete rate_limit_events older than 48 hours. Returns row count removed."""
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM rate_limit_events WHERE ts < NOW() - INTERVAL '48 hours'"
        )
        removed = cur.rowcount
    conn.commit()
    return removed
