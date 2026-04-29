import pytest
from unittest.mock import MagicMock

from lib.audit_logger import is_telegram_ip, log_security_event, EVT_RATE_LIMITED


class TestIsTelegramIp:

    def test_accepts_ip_in_first_range(self):
        # 149.154.160.0/20 covers 149.154.160.0 - 149.154.175.255
        assert is_telegram_ip("149.154.160.1") is True

    def test_accepts_ip_in_second_range(self):
        # 91.108.4.0/22 covers 91.108.4.0 - 91.108.7.255
        assert is_telegram_ip("91.108.4.1") is True

    def test_rejects_non_telegram_ip(self):
        assert is_telegram_ip("1.2.3.4") is False

    def test_rejects_empty_string(self):
        assert is_telegram_ip("") is False

    def test_handles_invalid_string(self):
        assert is_telegram_ip("not-an-ip") is False


class TestLogSecurityEvent:

    def _make_conn(self):
        cursor = MagicMock()
        conn = MagicMock()
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        return conn, cursor

    def test_inserts_row(self):
        conn, cursor = self._make_conn()
        log_security_event(conn, EVT_RATE_LIMITED, user_id=1, details="test", ip_addr="1.2.3.4")
        sql_calls = [str(c) for c in cursor.execute.call_args_list]
        assert any("INSERT INTO security_audit_log" in s for s in sql_calls)
        conn.commit.assert_called()

    def test_swallows_db_exception(self):
        conn = MagicMock()
        conn.cursor.side_effect = Exception("DB is down")
        # Must not raise
        log_security_event(conn, EVT_RATE_LIMITED, user_id=1)
