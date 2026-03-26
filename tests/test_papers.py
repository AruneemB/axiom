import sys
import json
from io import BytesIO
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone

import pytest

# Mock external dependencies before importing api.papers
sys.modules.setdefault("psycopg2", MagicMock())
sys.modules.setdefault("psycopg2.extras", MagicMock())

from api.papers import handler  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_handler_mock():
    """Create a mock handler with real _respond bound."""
    h = MagicMock(spec=handler)
    h.wfile = BytesIO()
    h.send_response = MagicMock()
    h.send_header = MagicMock()
    h.end_headers = MagicMock()
    h._respond = lambda status, body: handler._respond(h, status, body)
    return h


def _make_config(**overrides):
    """Return a minimal Config-like object for testing."""
    defaults = {"database_url": "postgresql://localhost/test"}
    defaults.update(overrides)
    cfg = MagicMock()
    for k, v in defaults.items():
        setattr(cfg, k, v)
    return cfg


def _make_row(id="2401.00001", title="Test Paper", categories=["q-fin.PM"],
              url="https://arxiv.org/abs/2401.00001",
              fetched_at=datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)):
    return {
        "id": id,
        "title": title,
        "categories": categories,
        "url": url,
        "fetched_at": fetched_at,
    }


def _invoke_handler(mock_cfg_fn, mock_conn_fn, rows):
    """Set up mocks and call handler.do_GET, return the handler mock."""
    mock_cfg_fn.return_value = _make_config()

    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = rows
    mock_conn_obj = MagicMock()
    mock_conn_obj.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
    mock_conn_obj.cursor.return_value.__exit__ = MagicMock(return_value=False)
    mock_conn_fn.return_value = mock_conn_obj

    h = _make_handler_mock()
    handler.do_GET(h)
    return h, mock_cursor, mock_conn_obj


# ---------------------------------------------------------------------------
# Response format
# ---------------------------------------------------------------------------

class TestPapersRespond:

    def test_respond_writes_json(self):
        h = _make_handler_mock()
        handler._respond(h, 200, {"papers": []})
        written = json.loads(h.wfile.getvalue())
        assert written == {"papers": []}

    def test_respond_sets_cors_header(self):
        h = _make_handler_mock()
        handler._respond(h, 200, {"papers": []})
        h.send_header.assert_any_call("Access-Control-Allow-Origin", "*")

    def test_respond_sets_content_type(self):
        h = _make_handler_mock()
        handler._respond(h, 200, {"papers": []})
        h.send_header.assert_any_call("Content-Type", "application/json")

    def test_respond_sets_content_length(self):
        h = _make_handler_mock()
        body = {"papers": []}
        handler._respond(h, 200, body)
        expected_len = len(json.dumps(body).encode())
        h.send_header.assert_any_call("Content-Length", expected_len)


# ---------------------------------------------------------------------------
# Success cases
# ---------------------------------------------------------------------------

class TestPapersSuccess:

    @patch("api.papers.get_connection")
    @patch("api.papers.load_config")
    def test_returns_200_with_papers(self, mock_cfg, mock_conn):
        rows = [_make_row(), _make_row(id="2401.00002", title="Another Paper")]
        h, _, _ = _invoke_handler(mock_cfg, mock_conn, rows)
        h.send_response.assert_called_with(200)
        result = json.loads(h.wfile.getvalue())
        assert len(result["papers"]) == 2

    @patch("api.papers.get_connection")
    @patch("api.papers.load_config")
    def test_returns_empty_list(self, mock_cfg, mock_conn):
        h, _, _ = _invoke_handler(mock_cfg, mock_conn, [])
        h.send_response.assert_called_with(200)
        result = json.loads(h.wfile.getvalue())
        assert result["papers"] == []

    @patch("api.papers.get_connection")
    @patch("api.papers.load_config")
    def test_paper_fields_present(self, mock_cfg, mock_conn):
        h, _, _ = _invoke_handler(mock_cfg, mock_conn, [_make_row()])
        result = json.loads(h.wfile.getvalue())
        paper = result["papers"][0]
        assert "id" in paper
        assert "title" in paper
        assert "categories" in paper
        assert "url" in paper
        assert "fetched_at" in paper

    @patch("api.papers.get_connection")
    @patch("api.papers.load_config")
    def test_iso_date_serialization(self, mock_cfg, mock_conn):
        dt = datetime(2024, 3, 10, 8, 30, 0, tzinfo=timezone.utc)
        h, _, _ = _invoke_handler(mock_cfg, mock_conn, [_make_row(fetched_at=dt)])
        result = json.loads(h.wfile.getvalue())
        assert result["papers"][0]["fetched_at"] == "2024-03-10T08:30:00+00:00"

    @patch("api.papers.get_connection")
    @patch("api.papers.load_config")
    def test_null_fetched_at(self, mock_cfg, mock_conn):
        h, _, _ = _invoke_handler(mock_cfg, mock_conn, [_make_row(fetched_at=None)])
        result = json.loads(h.wfile.getvalue())
        assert result["papers"][0]["fetched_at"] is None


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

class TestPapersError:

    @patch("api.papers.get_connection", side_effect=RuntimeError("db down"))
    @patch("api.papers.load_config")
    def test_returns_500_on_db_exception(self, mock_cfg, mock_conn):
        mock_cfg.return_value = _make_config()
        h = _make_handler_mock()
        handler.do_GET(h)
        h.send_response.assert_called_with(500)
        result = json.loads(h.wfile.getvalue())
        assert "error" in result


# ---------------------------------------------------------------------------
# Query validation
# ---------------------------------------------------------------------------

class TestPapersQuery:

    @patch("api.papers.get_connection")
    @patch("api.papers.load_config")
    def test_query_filters_skipped(self, mock_cfg, mock_conn):
        _, mock_cursor, _ = _invoke_handler(mock_cfg, mock_conn, [])
        sql = mock_cursor.execute.call_args[0][0]
        assert "NOT skipped" in sql

    @patch("api.papers.get_connection")
    @patch("api.papers.load_config")
    def test_query_orders_by_fetched_at_desc(self, mock_cfg, mock_conn):
        _, mock_cursor, _ = _invoke_handler(mock_cfg, mock_conn, [])
        sql = mock_cursor.execute.call_args[0][0]
        assert "ORDER BY fetched_at DESC" in sql

    @patch("api.papers.get_connection")
    @patch("api.papers.load_config")
    def test_query_limits_to_20(self, mock_cfg, mock_conn):
        _, mock_cursor, _ = _invoke_handler(mock_cfg, mock_conn, [])
        sql = mock_cursor.execute.call_args[0][0]
        assert "LIMIT 20" in sql


# ---------------------------------------------------------------------------
# Connection cleanup
# ---------------------------------------------------------------------------

class TestPapersConnection:

    @patch("api.papers.get_connection")
    @patch("api.papers.load_config")
    def test_connection_closed_on_success(self, mock_cfg, mock_conn):
        _, _, mock_conn_obj = _invoke_handler(mock_cfg, mock_conn, [])
        mock_conn_obj.close.assert_called_once()
