import sys
from unittest.mock import MagicMock

# Mock psycopg2 before importing lib.db so it can load without the real driver
_mock_psycopg2 = MagicMock()
sys.modules.setdefault("psycopg2", _mock_psycopg2)
sys.modules.setdefault("psycopg2.extras", _mock_psycopg2.extras)

from lib.db import get_connection  # noqa: E402


class TestGetConnection:

    def setup_method(self):
        _mock_psycopg2.reset_mock()

    def test_calls_connect_with_url(self):
        mock_conn = MagicMock()
        _mock_psycopg2.connect.return_value = mock_conn

        get_connection("postgresql://user:pass@host/db")

        _mock_psycopg2.connect.assert_called_once_with(
            "postgresql://user:pass@host/db",
            cursor_factory=_mock_psycopg2.extras.RealDictCursor,
        )

    def test_autocommit_disabled(self):
        mock_conn = MagicMock()
        _mock_psycopg2.connect.return_value = mock_conn

        conn = get_connection("postgresql://user:pass@host/db")

        assert conn.autocommit is False

    def test_returns_connection_object(self):
        mock_conn = MagicMock()
        _mock_psycopg2.connect.return_value = mock_conn

        result = get_connection("postgresql://user:pass@host/db")

        assert result is mock_conn

    def test_uses_real_dict_cursor_factory(self):
        mock_conn = MagicMock()
        _mock_psycopg2.connect.return_value = mock_conn

        get_connection("postgresql://localhost/test")

        call_kwargs = _mock_psycopg2.connect.call_args
        assert call_kwargs.kwargs["cursor_factory"] is _mock_psycopg2.extras.RealDictCursor
