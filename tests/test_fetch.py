import sys
import json
from io import BytesIO
from unittest.mock import patch, MagicMock, PropertyMock
from dataclasses import dataclass
from datetime import datetime, timezone

import pytest

# Mock external dependencies before importing api.fetch
sys.modules.setdefault("psycopg2", MagicMock())
sys.modules.setdefault("psycopg2.extras", MagicMock())
sys.modules.setdefault("feedparser", MagicMock())

from api.fetch import handler, run_fetch  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_handler_mock(headers=None):
    """Create a mock handler with real _respond bound."""
    h = MagicMock(spec=handler)
    h.wfile = BytesIO()
    h.send_response = MagicMock()
    h.send_header = MagicMock()
    h.end_headers = MagicMock()
    h.headers = headers or {}
    # Bind real _respond so do_GET can write proper responses
    h._respond = lambda status, body: handler._respond(h, status, body)
    return h


def _make_config(**overrides):
    """Return a minimal Config-like object for testing."""
    defaults = {
        "telegram_bot_token": "tok",
        "telegram_webhook_secret": "sec",
        "telegram_chat_ids": [1],
        "bot_password": "pw",
        "database_url": "postgresql://localhost/test",
        "openrouter_api_key": "key",
        "default_model": "m",
        "deepdive_model": "m2",
        "deepdive_day": 4,
        "cron_secret": "my-secret",
        "arxiv_categories": ["q-fin.PM"],
        "arxiv_max_results": 50,
        "allowed_topics": ["momentum", "factor model"],
        "relevance_threshold": 0.65,
        "quality_gate_min": 13,
        "dedup_similarity_max": 0.80,
        "embedding_model": "openai/text-embedding-3-small",
        "max_ideas_per_day": 2,
        "openrouter_timeout": 90,
    }
    defaults.update(overrides)
    cfg = MagicMock()
    for k, v in defaults.items():
        setattr(cfg, k, v)
    return cfg


@dataclass
class FakePaper:
    id: str
    title: str
    abstract: str
    authors: list
    categories: list
    url: str
    published_at: datetime


def _sample_paper(id="2401.00001", abstract="momentum factor model study"):
    return FakePaper(
        id=id,
        title="Test Paper",
        abstract=abstract,
        authors=["A"],
        categories=["q-fin.PM"],
        url="https://arxiv.org/abs/2401.00001",
        published_at=datetime(2024, 1, 15, tzinfo=timezone.utc),
    )


# ---------------------------------------------------------------------------
# Handler: cron secret verification
# ---------------------------------------------------------------------------

class TestHandlerCronAuth:

    @patch("api.fetch.load_config")
    @patch("api.fetch.run_fetch")
    def test_rejects_missing_key(self, mock_run, mock_cfg):
        mock_cfg.return_value = _make_config()
        h = _make_handler_mock()
        h.path = "/api/fetch"
        handler.do_GET(h)
        h.send_response.assert_called_with(401)
        mock_run.assert_not_called()

    @patch("api.fetch.load_config")
    @patch("api.fetch.run_fetch")
    def test_rejects_wrong_key(self, mock_run, mock_cfg):
        mock_cfg.return_value = _make_config()
        h = _make_handler_mock()
        h.path = "/api/fetch?key=wrong-secret"
        handler.do_GET(h)
        h.send_response.assert_called_with(401)
        mock_run.assert_not_called()

    @patch("api.fetch.load_config")
    @patch("api.fetch.run_fetch")
    def test_accepts_correct_key(self, mock_run, mock_cfg):
        mock_cfg.return_value = _make_config()
        mock_run.return_value = {"fetched": 0, "stored": 0, "skipped": 0}
        h = _make_handler_mock()
        h.path = "/api/fetch?key=my-secret"
        handler.do_GET(h)
        h.send_response.assert_called_with(200)
        mock_run.assert_called_once()

    @patch("api.fetch.load_config")
    @patch("api.fetch.run_fetch")
    def test_accepts_valid_bearer_token(self, mock_run, mock_cfg):
        mock_cfg.return_value = _make_config()
        mock_run.return_value = {"fetched": 0, "stored": 0, "skipped": 0}
        h = _make_handler_mock(headers={"Authorization": "Bearer my-secret"})
        h.path = "/api/fetch"
        handler.do_GET(h)
        h.send_response.assert_called_with(200)
        mock_run.assert_called_once()

    @patch("api.fetch.load_config")
    @patch("api.fetch.run_fetch")
    def test_accepts_lowercase_bearer_token(self, mock_run, mock_cfg):
        mock_cfg.return_value = _make_config()
        mock_run.return_value = {"fetched": 0, "stored": 0, "skipped": 0}
        h = _make_handler_mock(headers={"Authorization": "bearer my-secret"})
        h.path = "/api/fetch"
        handler.do_GET(h)
        h.send_response.assert_called_with(200)
        mock_run.assert_called_once()

    @patch("api.fetch.load_config")
    @patch("api.fetch.run_fetch")
    def test_rejects_invalid_bearer_token(self, mock_run, mock_cfg):
        mock_cfg.return_value = _make_config()
        h = _make_handler_mock(headers={"Authorization": "Bearer wrong-secret"})
        h.path = "/api/fetch"
        handler.do_GET(h)
        h.send_response.assert_called_with(401)
        mock_run.assert_not_called()

    @patch("api.fetch.load_config")
    @patch("api.fetch.run_fetch")
    def test_rejects_no_auth(self, mock_run, mock_cfg):
        mock_cfg.return_value = _make_config()
        h = _make_handler_mock()
        h.path = "/api/fetch"
        handler.do_GET(h)
        h.send_response.assert_called_with(401)
        mock_run.assert_not_called()

    @patch("api.fetch.load_config")
    @patch("api.fetch.run_fetch")
    def test_rejects_non_bearer_scheme(self, mock_run, mock_cfg):
        """Non-Bearer Authorization scheme (e.g. Basic) is not accepted."""
        mock_cfg.return_value = _make_config()
        h = _make_handler_mock(headers={"Authorization": "Basic my-secret"})
        h.path = "/api/fetch"
        handler.do_GET(h)
        h.send_response.assert_called_with(401)
        mock_run.assert_not_called()

    @patch("api.fetch.load_config")
    @patch("api.fetch.run_fetch")
    def test_rejects_empty_bearer_token(self, mock_run, mock_cfg):
        """'Bearer ' prefix with no actual token is rejected."""
        mock_cfg.return_value = _make_config()
        h = _make_handler_mock(headers={"Authorization": "Bearer "})
        h.path = "/api/fetch"
        handler.do_GET(h)
        h.send_response.assert_called_with(401)
        mock_run.assert_not_called()

    @patch("api.fetch.load_config")
    @patch("api.fetch.run_fetch")
    def test_accepts_valid_key_when_bearer_is_wrong(self, mock_run, mock_cfg):
        """Valid ?key= param overrides an invalid Bearer token -> 200."""
        mock_cfg.return_value = _make_config()
        mock_run.return_value = {"fetched": 0, "stored": 0, "skipped": 0}
        h = _make_handler_mock(headers={"Authorization": "Bearer wrong-secret"})
        h.path = "/api/fetch?key=my-secret"
        handler.do_GET(h)
        h.send_response.assert_called_with(200)
        mock_run.assert_called_once()

    @patch("api.fetch.load_config")
    @patch("api.fetch.run_fetch")
    def test_accepts_valid_bearer_when_key_is_wrong(self, mock_run, mock_cfg):
        """Valid Bearer token overrides an invalid ?key= param -> 200."""
        mock_cfg.return_value = _make_config()
        mock_run.return_value = {"fetched": 0, "stored": 0, "skipped": 0}
        h = _make_handler_mock(headers={"Authorization": "Bearer my-secret"})
        h.path = "/api/fetch?key=wrong-secret"
        handler.do_GET(h)
        h.send_response.assert_called_with(200)
        mock_run.assert_called_once()

    @patch("api.fetch.load_config")
    @patch("api.fetch.run_fetch")
    def test_rejects_both_key_and_bearer_wrong(self, mock_run, mock_cfg):
        """Both ?key= and Bearer token wrong -> 401."""
        mock_cfg.return_value = _make_config()
        h = _make_handler_mock(headers={"Authorization": "Bearer bad"})
        h.path = "/api/fetch?key=bad"
        handler.do_GET(h)
        h.send_response.assert_called_with(401)
        mock_run.assert_not_called()

    @patch("api.fetch.load_config")
    @patch("api.fetch.run_fetch")
    def test_accepts_both_key_and_bearer_valid(self, mock_run, mock_cfg):
        """Both ?key= and Bearer token valid -> 200 (redundant but well-formed)."""
        mock_cfg.return_value = _make_config()
        mock_run.return_value = {"fetched": 0, "stored": 0, "skipped": 0}
        h = _make_handler_mock(headers={"Authorization": "Bearer my-secret"})
        h.path = "/api/fetch?key=my-secret"
        handler.do_GET(h)
        h.send_response.assert_called_with(200)
        mock_run.assert_called_once()


class TestHandlerRespond:

    def test_respond_writes_json(self):
        h = MagicMock(spec=handler)
        h.wfile = BytesIO()
        h.send_response = MagicMock()
        h.send_header = MagicMock()
        h.end_headers = MagicMock()
        handler._respond(h, 200, {"ok": True})
        written = h.wfile.getvalue()
        assert json.loads(written) == {"ok": True}

    def test_respond_sets_content_type(self):
        h = MagicMock(spec=handler)
        h.wfile = BytesIO()
        h.send_response = MagicMock()
        h.send_header = MagicMock()
        h.end_headers = MagicMock()
        handler._respond(h, 200, {"ok": True})
        h.send_header.assert_any_call("Content-Type", "application/json")

    def test_respond_sets_content_length(self):
        h = MagicMock(spec=handler)
        h.wfile = BytesIO()
        h.send_response = MagicMock()
        h.send_header = MagicMock()
        h.end_headers = MagicMock()
        body = {"key": "value"}
        handler._respond(h, 200, body)
        expected_len = len(json.dumps(body).encode())
        h.send_header.assert_any_call("Content-Length", expected_len)

    @patch("api.fetch.load_config")
    @patch("api.fetch.run_fetch", side_effect=RuntimeError("db down"))
    def test_handler_returns_500_on_exception(self, mock_run, mock_cfg):
        mock_cfg.return_value = _make_config()
        h = _make_handler_mock()
        h.path = "/api/fetch?key=my-secret"
        handler.do_GET(h)
        h.send_response.assert_called_with(500)
        written = json.loads(h.wfile.getvalue())
        assert "error" in written


# ---------------------------------------------------------------------------
# run_fetch: core logic
# ---------------------------------------------------------------------------

class TestRunFetchEmpty:

    @patch("api.fetch.fetch_recent_papers", return_value=[])
    def test_no_papers_returns_zeros(self, mock_fetch):
        cfg = _make_config()
        result = run_fetch(cfg)
        assert result == {
            "fetched": 0,
            "stored": 0,
            "skipped": 0,
            "details": {
                "skipped": {
                    "already_in_db": 0,
                    "below_relevance_threshold": 0
                }
            }
        }


class TestRunFetchDuplicateSkip:

    @patch("api.fetch.get_connection")
    @patch("api.fetch.RelevanceFilter")
    @patch("api.fetch.fetch_recent_papers")
    def test_existing_paper_skipped(self, mock_fetch, mock_filter_cls, mock_conn):
        mock_fetch.return_value = [_sample_paper()]
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = {"id": "exists"}  # paper already in DB
        mock_conn_obj = MagicMock()
        mock_conn_obj.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn_obj.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.return_value = mock_conn_obj

        cfg = _make_config()
        result = run_fetch(cfg)
        assert result["skipped"] == 1
        assert result["stored"] == 0


class TestRunFetchBelowThreshold:

    @patch("api.fetch.get_connection")
    @patch("api.fetch.RelevanceFilter")
    @patch("api.fetch.fetch_recent_papers")
    def test_low_score_stored_as_skipped(self, mock_fetch, mock_filter_cls, mock_conn):
        mock_fetch.return_value = [_sample_paper()]

        mock_filter = MagicMock()
        mock_filter.score.return_value = (0.3, ["momentum"])
        mock_filter_cls.return_value = mock_filter

        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = None  # not in DB yet
        mock_conn_obj = MagicMock()
        mock_conn_obj.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn_obj.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.return_value = mock_conn_obj

        cfg = _make_config()
        result = run_fetch(cfg)
        assert result["skipped"] == 1
        assert result["stored"] == 0

        # Verify skipped INSERT includes skip_reason
        insert_call = mock_cursor.execute.call_args_list[-1]
        sql = insert_call[0][0]
        params = insert_call[0][1]
        assert "skipped" in sql.lower() or "TRUE" in sql
        assert "below_relevance_threshold" in params


class TestRunFetchAboveThreshold:

    @patch("api.fetch.get_connection")
    @patch("api.fetch.RelevanceFilter")
    @patch("api.fetch.fetch_recent_papers")
    def test_high_score_stored_normally(self, mock_fetch, mock_filter_cls, mock_conn):
        mock_fetch.return_value = [_sample_paper()]

        mock_filter = MagicMock()
        mock_filter.score.return_value = (0.85, ["momentum", "factor model"])
        mock_filter_cls.return_value = mock_filter

        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = None
        mock_conn_obj = MagicMock()
        mock_conn_obj.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn_obj.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.return_value = mock_conn_obj

        cfg = _make_config()
        result = run_fetch(cfg)
        assert result["stored"] == 1
        assert result["skipped"] == 0


class TestRunFetchConnection:

    @patch("api.fetch.get_connection")
    @patch("api.fetch.RelevanceFilter")
    @patch("api.fetch.fetch_recent_papers")
    def test_connection_committed_and_closed(self, mock_fetch, mock_filter_cls, mock_conn):
        mock_fetch.return_value = [_sample_paper()]

        mock_filter = MagicMock()
        mock_filter.score.return_value = (0.85, ["momentum"])
        mock_filter_cls.return_value = mock_filter

        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = None
        mock_conn_obj = MagicMock()
        mock_conn_obj.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn_obj.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.return_value = mock_conn_obj

        cfg = _make_config()
        run_fetch(cfg)

        mock_conn_obj.commit.assert_called_once()
        mock_conn_obj.close.assert_called_once()

    @patch("api.fetch.get_connection")
    @patch("api.fetch.RelevanceFilter")
    @patch("api.fetch.fetch_recent_papers")
    def test_uses_config_database_url(self, mock_fetch, mock_filter_cls, mock_conn):
        mock_fetch.return_value = [_sample_paper()]

        mock_filter = MagicMock()
        mock_filter.score.return_value = (0.85, ["momentum"])
        mock_filter_cls.return_value = mock_filter

        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = None
        mock_conn_obj = MagicMock()
        mock_conn_obj.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn_obj.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.return_value = mock_conn_obj

        cfg = _make_config(database_url="postgresql://custom/db")
        run_fetch(cfg)

        mock_conn.assert_called_once_with("postgresql://custom/db")


class TestRunFetchFilterInit:

    @patch("api.fetch.get_connection")
    @patch("api.fetch.RelevanceFilter")
    @patch("api.fetch.fetch_recent_papers")
    def test_filter_initialized_with_config(self, mock_fetch, mock_filter_cls, mock_conn):
        mock_fetch.return_value = [_sample_paper()]

        mock_filter = MagicMock()
        mock_filter.score.return_value = (0.85, ["momentum"])
        mock_filter_cls.return_value = mock_filter

        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = None
        mock_conn_obj = MagicMock()
        mock_conn_obj.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn_obj.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.return_value = mock_conn_obj

        cfg = _make_config(
            allowed_topics=["alpha decay", "liquidity"],
            relevance_threshold=0.70,
            database_url="postgresql://localhost/test",
            openrouter_api_key="key",
            embedding_model="openai/text-embedding-3-small",
        )
        run_fetch(cfg)

        mock_filter_cls.assert_called_once_with(
            topics=["alpha decay", "liquidity"],
            threshold=0.70,
            database_url="postgresql://localhost/test",
            api_key="key",
            embedding_model="openai/text-embedding-3-small",
        )


class TestRunFetchFetchedCount:

    @patch("api.fetch.get_connection")
    @patch("api.fetch.RelevanceFilter")
    @patch("api.fetch.fetch_recent_papers")
    def test_fetched_count_matches_total_papers(self, mock_fetch, mock_filter_cls, mock_conn):
        papers = [_sample_paper(id=f"2401.{i:05d}") for i in range(5)]
        mock_fetch.return_value = papers

        mock_filter = MagicMock()
        mock_filter.score.return_value = (0.85, ["momentum"])
        mock_filter_cls.return_value = mock_filter

        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = None
        mock_conn_obj = MagicMock()
        mock_conn_obj.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn_obj.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.return_value = mock_conn_obj

        cfg = _make_config()
        result = run_fetch(cfg)
        assert result["fetched"] == 5


class TestRunFetchArxivCall:

    @patch("api.fetch.get_connection")
    @patch("api.fetch.RelevanceFilter")
    @patch("api.fetch.fetch_recent_papers")
    def test_passes_config_to_arxiv(self, mock_fetch, mock_filter_cls, mock_conn):
        mock_fetch.return_value = []
        cfg = _make_config(
            arxiv_categories=["q-fin.PM", "stat.ML"],
            arxiv_max_results=25,
        )
        run_fetch(cfg)
        mock_fetch.assert_called_once_with(
            categories=["q-fin.PM", "stat.ML"],
            max_results=25,
        )