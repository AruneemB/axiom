import pytest
from unittest.mock import MagicMock, patch, call

from lib.rate_limiter import (
    check_burst_limit,
    check_global_rate_limit,
    record_violation,
    check_auto_suspend,
    BURST_LIMIT,
    VIOLATION_THRESHOLD,
)


def _make_conn(fetchone_values):
    """Return a mock conn whose cursor fetchone returns successive values."""
    mock_cursor = MagicMock()
    mock_cursor.fetchone.side_effect = list(fetchone_values)
    mock_cursor.rowcount = 0
    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    return mock_conn, mock_cursor


class TestCheckBurstLimit:

    def test_allows_under_threshold(self):
        conn, cursor = _make_conn([{"cnt": BURST_LIMIT - 1}])
        ok, msg = check_burst_limit(12345, conn)
        assert ok is True
        assert msg == ""
        conn.commit.assert_called()

    def test_blocks_at_threshold(self):
        conn, cursor = _make_conn([{"cnt": BURST_LIMIT}])
        ok, msg = check_burst_limit(12345, conn)
        assert ok is False
        assert "slow down" in msg.lower()
        conn.commit.assert_not_called()

    def test_blocks_above_threshold(self):
        conn, cursor = _make_conn([{"cnt": BURST_LIMIT + 5}])
        ok, msg = check_burst_limit(12345, conn)
        assert ok is False


class TestCheckGlobalRateLimit:

    def test_allows_unknown_command_under_default(self):
        conn, cursor = _make_conn([{"cnt": 0}])
        ok, msg = check_global_rate_limit(1, "unknown_cmd", conn)
        assert ok is True
        conn.commit.assert_called()

    def test_blocks_at_command_limit(self):
        from lib.rate_limiter import COMMAND_LIMITS, DEFAULT_LIMIT
        limit = COMMAND_LIMITS.get("/status", DEFAULT_LIMIT)
        conn, cursor = _make_conn([{"cnt": limit}])
        ok, msg = check_global_rate_limit(1, "/status", conn)
        assert ok is False
        assert str(limit) in msg

    def test_allows_first_message(self):
        conn, cursor = _make_conn([{"cnt": 0}])
        ok, _ = check_global_rate_limit(1, "/topics", conn)
        assert ok is True


class TestRecordViolation:

    def test_inserts_violation_row(self):
        conn, cursor = _make_conn([])
        record_violation(99, "burst_blocked", conn)
        sql_calls = [str(c) for c in cursor.execute.call_args_list]
        assert any("INSERT INTO rate_limit_events" in s for s in sql_calls)
        assert any("burst_blocked" in s for s in sql_calls)
        conn.commit.assert_called()


class TestCheckAutoSuspend:

    def test_does_not_suspend_below_threshold(self):
        conn, cursor = _make_conn([{"cnt": VIOLATION_THRESHOLD - 1}])
        result = check_auto_suspend(1, conn)
        assert result is False
        # No UPDATE should have been issued
        sql_calls = [str(c) for c in cursor.execute.call_args_list]
        assert not any("UPDATE allowed_users" in s for s in sql_calls)

    def test_triggers_suspension_at_threshold(self):
        conn, cursor = _make_conn([{"cnt": VIOLATION_THRESHOLD}])
        cursor.rowcount = 1  # UPDATE affected 1 row → first time triggered
        result = check_auto_suspend(1, conn)
        assert result is True
        sql_calls = [str(c) for c in cursor.execute.call_args_list]
        assert any("UPDATE allowed_users" in s for s in sql_calls)
        conn.commit.assert_called()

    def test_does_not_retrigger_if_already_suspended(self):
        conn, cursor = _make_conn([{"cnt": VIOLATION_THRESHOLD + 3}])
        cursor.rowcount = 0  # UPDATE matched no rows → already suspended
        result = check_auto_suspend(1, conn)
        assert result is False
