import sys
import json
from io import BytesIO
from unittest.mock import patch, MagicMock, call
from datetime import datetime

import pytest

# Mock psycopg2 before importing api.deliver
sys.modules.setdefault("psycopg2", MagicMock())
sys.modules.setdefault("psycopg2.extras", MagicMock())

from api.deliver import (  # noqa: E402
    handler, run_deliver, mark_processed, is_duplicate, store_idea, _notify_owner,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_handler_mock(headers=None):
    h = MagicMock(spec=handler)
    h.wfile = BytesIO()
    h.send_response = MagicMock()
    h.send_header = MagicMock()
    h.end_headers = MagicMock()
    h.headers = headers or {}
    h._respond = lambda status, body: handler._respond(h, status, body)
    return h


def _make_config(**overrides):
    defaults = {
        "telegram_bot_token": "tok",
        "telegram_webhook_secret": "sec",
        "telegram_chat_ids": [1],
        "bot_password": "pw",
        "database_url": "postgresql://localhost/test",
        "openrouter_api_key": "or-key",
        "default_model": "google/gemini-flash-1.5",
        "fallback_model": "google/gemini-2.0-flash",
        "deepdive_model": "anthropic/claude-haiku",
        "deepdive_day": 4,
        "cron_secret": "my-secret",
        "arxiv_categories": ["q-fin.PM"],
        "arxiv_max_results": 50,
        "allowed_topics": ["momentum"],
        "relevance_threshold": 0.65,
        "quality_gate_min": 13,
        "dedup_similarity_max": 0.80,
        "embedding_model": "openai/text-embedding-3-small",
        "max_ideas_per_day": 2,
        "openrouter_timeout": 90,
        "deliver_llm_timeout": 50,
    }
    defaults.update(overrides)
    cfg = MagicMock()
    for k, v in defaults.items():
        setattr(cfg, k, v)
    return cfg


def _make_paper(id="p1", title="Test", abstract="Abstract", url="https://arxiv.org/abs/p1"):
    return {"id": id, "title": title, "abstract": abstract, "url": url}


def _make_idea(novelty=7, feasibility=8):
    return {
        "hypothesis": "We hypothesize that...",
        "method": "OLS regression...",
        "dataset": "CRSP daily returns...",
        "novelty_score": novelty,
        "feasibility_score": feasibility,
    }


def _mock_conn_with_papers(paper, users):
    """Create a mock connection returning a single paper via fetchone and users via fetchall."""
    mock_cursor = MagicMock()
    # fetchone call order: 1) paper SELECT query, 2) store_idea INSERT RETURNING id
    mock_cursor.fetchone.side_effect = [paper, {"id": 1}]
    mock_cursor.fetchall.return_value = [{"user_id": u} for u in users]
    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    return mock_conn


# ---------------------------------------------------------------------------
# Handler: cron secret verification
# ---------------------------------------------------------------------------

class TestDeliverHandlerAuth:

    @patch("api.deliver.load_config")
    @patch("api.deliver.run_deliver")
    def test_rejects_wrong_key(self, mock_run, mock_cfg):
        mock_cfg.return_value = _make_config()
        h = _make_handler_mock()
        h.path = "/api/deliver?key=bad"
        handler.do_GET(h)
        h.send_response.assert_called_with(401)
        mock_run.assert_not_called()

    @patch("api.deliver.load_config")
    @patch("api.deliver.run_deliver")
    def test_accepts_correct_key(self, mock_run, mock_cfg):
        mock_cfg.return_value = _make_config()
        mock_run.return_value = {"sent": 0, "reason": "no papers or no active users"}
        h = _make_handler_mock()
        h.path = "/api/deliver?key=my-secret"
        handler.do_GET(h)
        h.send_response.assert_called_with(200)

    @patch("api.deliver.load_config")
    @patch("api.deliver.run_deliver")
    def test_accepts_valid_bearer_token(self, mock_run, mock_cfg):
        mock_cfg.return_value = _make_config()
        mock_run.return_value = {"sent": 0, "reason": "no papers or no active users"}
        h = _make_handler_mock(headers={"Authorization": "Bearer my-secret"})
        h.path = "/api/deliver"
        handler.do_GET(h)
        h.send_response.assert_called_with(200)

    @patch("api.deliver.load_config")
    @patch("api.deliver.run_deliver")
    def test_accepts_lowercase_bearer_token(self, mock_run, mock_cfg):
        mock_cfg.return_value = _make_config()
        mock_run.return_value = {"sent": 0, "reason": "no papers or no active users"}
        h = _make_handler_mock(headers={"Authorization": "bearer my-secret"})
        h.path = "/api/deliver"
        handler.do_GET(h)
        h.send_response.assert_called_with(200)

    @patch("api.deliver.load_config")
    @patch("api.deliver.run_deliver")
    def test_rejects_invalid_bearer_token(self, mock_run, mock_cfg):
        mock_cfg.return_value = _make_config()
        h = _make_handler_mock(headers={"Authorization": "Bearer wrong-secret"})
        h.path = "/api/deliver"
        handler.do_GET(h)
        h.send_response.assert_called_with(401)
        mock_run.assert_not_called()

    @patch("api.deliver.load_config")
    @patch("api.deliver.run_deliver")
    def test_rejects_missing_auth(self, mock_run, mock_cfg):
        """No key param and no Authorization header -> 401."""
        mock_cfg.return_value = _make_config()
        h = _make_handler_mock()
        h.path = "/api/deliver"
        handler.do_GET(h)
        h.send_response.assert_called_with(401)
        mock_run.assert_not_called()

    @patch("api.deliver.load_config")
    @patch("api.deliver.run_deliver")
    def test_rejects_non_bearer_scheme(self, mock_run, mock_cfg):
        """Non-Bearer Authorization scheme (e.g. Basic) is not accepted."""
        mock_cfg.return_value = _make_config()
        h = _make_handler_mock(headers={"Authorization": "Basic my-secret"})
        h.path = "/api/deliver"
        handler.do_GET(h)
        h.send_response.assert_called_with(401)
        mock_run.assert_not_called()

    @patch("api.deliver.load_config")
    @patch("api.deliver.run_deliver")
    def test_rejects_empty_bearer_token(self, mock_run, mock_cfg):
        """'Bearer ' prefix with no actual token is rejected."""
        mock_cfg.return_value = _make_config()
        h = _make_handler_mock(headers={"Authorization": "Bearer "})
        h.path = "/api/deliver"
        handler.do_GET(h)
        h.send_response.assert_called_with(401)
        mock_run.assert_not_called()

    @patch("api.deliver.load_config")
    @patch("api.deliver.run_deliver")
    def test_accepts_valid_key_when_bearer_is_wrong(self, mock_run, mock_cfg):
        """Valid ?key= param overrides an invalid Bearer token -> 200."""
        mock_cfg.return_value = _make_config()
        mock_run.return_value = {"sent": 0, "reason": "no papers or no active users"}
        h = _make_handler_mock(headers={"Authorization": "Bearer wrong-secret"})
        h.path = "/api/deliver?key=my-secret"
        handler.do_GET(h)
        h.send_response.assert_called_with(200)
        mock_run.assert_called_once()

    @patch("api.deliver.load_config")
    @patch("api.deliver.run_deliver")
    def test_accepts_valid_bearer_when_key_is_wrong(self, mock_run, mock_cfg):
        """Valid Bearer token overrides an invalid ?key= param -> 200."""
        mock_cfg.return_value = _make_config()
        mock_run.return_value = {"sent": 0, "reason": "no papers or no active users"}
        h = _make_handler_mock(headers={"Authorization": "Bearer my-secret"})
        h.path = "/api/deliver?key=wrong-secret"
        handler.do_GET(h)
        h.send_response.assert_called_with(200)
        mock_run.assert_called_once()

    @patch("api.deliver.load_config")
    @patch("api.deliver.run_deliver")
    def test_rejects_both_key_and_bearer_wrong(self, mock_run, mock_cfg):
        """Both ?key= and Bearer token wrong -> 401."""
        mock_cfg.return_value = _make_config()
        h = _make_handler_mock(headers={"Authorization": "Bearer bad"})
        h.path = "/api/deliver?key=bad"
        handler.do_GET(h)
        h.send_response.assert_called_with(401)
        mock_run.assert_not_called()

    @patch("api.deliver.load_config")
    @patch("api.deliver.run_deliver")
    def test_accepts_both_key_and_bearer_valid(self, mock_run, mock_cfg):
        """Both ?key= and Bearer token valid -> 200 (redundant but well-formed)."""
        mock_cfg.return_value = _make_config()
        mock_run.return_value = {"sent": 0, "reason": "no papers or no active users"}
        h = _make_handler_mock(headers={"Authorization": "Bearer my-secret"})
        h.path = "/api/deliver?key=my-secret"
        handler.do_GET(h)
        h.send_response.assert_called_with(200)
        mock_run.assert_called_once()

    @patch("api.deliver.load_config")
    @patch("api.deliver.run_deliver", side_effect=RuntimeError("fail"))
    def test_returns_500_on_exception(self, mock_run, mock_cfg):
        mock_cfg.return_value = _make_config()
        h = _make_handler_mock()
        h.path = "/api/deliver?key=my-secret"
        handler.do_GET(h)
        h.send_response.assert_called_with(500)


# ---------------------------------------------------------------------------
# run_deliver: early exit
# ---------------------------------------------------------------------------

class TestRunDeliverEarlyExit:

    @patch("api.deliver.get_connection")
    def test_no_papers_returns_zero(self, mock_get_conn):
        mock_conn = _mock_conn_with_papers(paper=None, users=[123])
        mock_get_conn.return_value = mock_conn
        cfg = _make_config()
        result = run_deliver(cfg)
        assert result["sent"] == 0
        assert "stats" in result
        assert result["stats"]["papers_found"] == 0
        mock_conn.close.assert_called_once()

    @patch("api.deliver.get_connection")
    def test_no_users_returns_zero(self, mock_get_conn):
        mock_conn = _mock_conn_with_papers(paper=_make_paper(), users=[])
        mock_get_conn.return_value = mock_conn
        cfg = _make_config()
        result = run_deliver(cfg)
        assert result["sent"] == 0
        mock_conn.close.assert_called_once()


# ---------------------------------------------------------------------------
# run_deliver: model selection
# ---------------------------------------------------------------------------

class TestRunDeliverModelSelection:

    @patch("api.deliver.send_idea_message")
    @patch("api.deliver.store_idea", return_value=1)
    @patch("api.deliver.is_duplicate", return_value=False)
    @patch("api.deliver.embed_text", return_value=[0.1] * 1536)
    @patch("api.deliver.synthesize_idea")
    @patch("api.deliver.get_connection")
    @patch("api.deliver.datetime")
    def test_uses_default_model_on_normal_day(self, mock_dt, mock_conn_fn,
                                               mock_synth, mock_embed,
                                               mock_dedup, mock_store, mock_send):
        mock_dt.utcnow.return_value = datetime(2024, 1, 15)  # Monday (weekday=0)
        mock_conn = _mock_conn_with_papers(_make_paper(), [123])
        mock_conn_fn.return_value = mock_conn
        mock_synth.return_value = (_make_idea(), "")
        cfg = _make_config(deepdive_day=4)
        result = run_deliver(cfg)
        assert result["model"] == "google/gemini-flash-1.5"

    @patch("api.deliver.send_idea_message")
    @patch("api.deliver.store_idea", return_value=1)
    @patch("api.deliver.is_duplicate", return_value=False)
    @patch("api.deliver.embed_text", return_value=[0.1] * 1536)
    @patch("api.deliver.synthesize_idea")
    @patch("api.deliver.get_connection")
    @patch("api.deliver.datetime")
    def test_uses_deepdive_model_on_configured_day(self, mock_dt, mock_conn_fn,
                                                    mock_synth, mock_embed,
                                                    mock_dedup, mock_store, mock_send):
        mock_dt.utcnow.return_value = datetime(2024, 1, 19)  # Friday (weekday=4)
        mock_conn = _mock_conn_with_papers(_make_paper(), [123])
        mock_conn_fn.return_value = mock_conn
        mock_synth.return_value = (_make_idea(), "")
        cfg = _make_config(deepdive_day=4)
        result = run_deliver(cfg)
        assert result["model"] == "anthropic/claude-haiku"


# ---------------------------------------------------------------------------
# run_deliver: skip reasons
# ---------------------------------------------------------------------------

class TestRunDeliverSkipReasons:

    @patch("api.deliver.mark_processed")
    @patch("api.deliver.synthesize_idea", return_value=(None, "mock error"))
    @patch("api.deliver.get_connection")
    @patch("api.deliver.datetime")
    def test_llm_parse_error_marks_processed(self, mock_dt, mock_conn_fn,
                                              mock_synth, mock_mark):
        mock_dt.utcnow.return_value = datetime(2024, 1, 15)
        mock_conn = _mock_conn_with_papers(_make_paper(), [123])
        mock_conn_fn.return_value = mock_conn
        cfg = _make_config()
        run_deliver(cfg)
        mock_mark.assert_called_with(mock_conn, "p1", skip_reason="llm_parse_error")

    @patch("api.deliver.mark_processed")
    @patch("api.deliver.synthesize_idea")
    @patch("api.deliver.get_connection")
    @patch("api.deliver.datetime")
    def test_below_quality_gate_marks_processed(self, mock_dt, mock_conn_fn,
                                                 mock_synth, mock_mark):
        mock_dt.utcnow.return_value = datetime(2024, 1, 15)
        mock_conn = _mock_conn_with_papers(_make_paper(), [123])
        mock_conn_fn.return_value = mock_conn
        mock_synth.return_value = (_make_idea(novelty=3, feasibility=4), "")  # 7 < 13
        cfg = _make_config(quality_gate_min=13)
        run_deliver(cfg)
        mock_mark.assert_called_with(mock_conn, "p1", skip_reason="below_quality_gate")

    @patch("api.deliver.mark_processed")
    @patch("api.deliver.is_duplicate", return_value=True)
    @patch("api.deliver.embed_text", return_value=[0.1] * 1536)
    @patch("api.deliver.synthesize_idea")
    @patch("api.deliver.get_connection")
    @patch("api.deliver.datetime")
    def test_duplicate_idea_marks_processed(self, mock_dt, mock_conn_fn,
                                             mock_synth, mock_embed,
                                             mock_dedup, mock_mark):
        mock_dt.utcnow.return_value = datetime(2024, 1, 15)
        mock_conn = _mock_conn_with_papers(_make_paper(), [123])
        mock_conn_fn.return_value = mock_conn
        mock_synth.return_value = (_make_idea(), "")
        cfg = _make_config()
        run_deliver(cfg)
        mock_mark.assert_called_with(mock_conn, "p1", skip_reason="duplicate_idea")


# ---------------------------------------------------------------------------
# run_deliver: successful send
# ---------------------------------------------------------------------------

class TestRunDeliverSuccess:

    @patch("api.deliver.mark_processed")
    @patch("api.deliver.send_idea_message")
    @patch("api.deliver.store_idea", return_value=42)
    @patch("api.deliver.is_duplicate", return_value=False)
    @patch("api.deliver.embed_text", return_value=[0.1] * 1536)
    @patch("api.deliver.synthesize_idea")
    @patch("api.deliver.get_connection")
    @patch("api.deliver.datetime")
    def test_sends_to_all_active_users(self, mock_dt, mock_conn_fn,
                                        mock_synth, mock_embed,
                                        mock_dedup, mock_store, mock_send, mock_mark):
        mock_dt.utcnow.return_value = datetime(2024, 1, 15)
        mock_conn = _mock_conn_with_papers(_make_paper(), [100, 200, 300])
        mock_conn_fn.return_value = mock_conn
        mock_synth.return_value = (_make_idea(), "")
        cfg = _make_config()
        result = run_deliver(cfg)
        assert result["sent"] == 1
        assert mock_send.call_count == 3
        sent_user_ids = [c.kwargs["chat_id"] for c in mock_send.call_args_list]
        assert sorted(sent_user_ids) == [100, 200, 300]

    @patch("api.deliver.mark_processed")
    @patch("api.deliver.send_idea_message")
    @patch("api.deliver.store_idea", return_value=42)
    @patch("api.deliver.is_duplicate", return_value=False)
    @patch("api.deliver.embed_text", return_value=[0.1] * 1536)
    @patch("api.deliver.synthesize_idea")
    @patch("api.deliver.get_connection")
    @patch("api.deliver.datetime")
    def test_single_run_sends_exactly_one_paper(self, mock_dt, mock_conn_fn,
                                                 mock_synth, mock_embed,
                                                 mock_dedup, mock_store, mock_send, mock_mark):
        mock_dt.utcnow.return_value = datetime(2024, 1, 15)
        mock_conn = _mock_conn_with_papers(_make_paper(id="p1"), [123])
        mock_conn_fn.return_value = mock_conn
        mock_synth.return_value = (_make_idea(), "")
        cfg = _make_config()
        result = run_deliver(cfg)
        assert result["sent"] == 1
        assert result["papers"] == ["p1"]

    @patch("api.deliver.mark_processed")
    @patch("api.deliver.send_idea_message")
    @patch("api.deliver.store_idea", return_value=42)
    @patch("api.deliver.is_duplicate", return_value=False)
    @patch("api.deliver.embed_text", return_value=[0.1] * 1536)
    @patch("api.deliver.synthesize_idea")
    @patch("api.deliver.get_connection")
    @patch("api.deliver.datetime")
    def test_returns_processed_paper_ids(self, mock_dt, mock_conn_fn,
                                          mock_synth, mock_embed,
                                          mock_dedup, mock_store, mock_send, mock_mark):
        mock_dt.utcnow.return_value = datetime(2024, 1, 15)
        mock_conn = _mock_conn_with_papers(_make_paper(id="2401.99999"), [123])
        mock_conn_fn.return_value = mock_conn
        mock_synth.return_value = (_make_idea(), "")
        cfg = _make_config()
        result = run_deliver(cfg)
        assert "2401.99999" in result["papers"]


# ---------------------------------------------------------------------------
# run_deliver: deliver_llm_timeout is used (not openrouter_timeout)
# ---------------------------------------------------------------------------

class TestRunDeliverTimeout:

    @patch("api.deliver._notify_owner")
    @patch("api.deliver.mark_processed")
    @patch("api.deliver.synthesize_idea", return_value=(None, "error"))
    @patch("api.deliver.get_connection")
    @patch("api.deliver.datetime")
    def test_uses_deliver_llm_timeout_not_openrouter_timeout(
            self, mock_dt, mock_get_conn, mock_synth, mock_mark, mock_notify):
        mock_dt.utcnow.return_value = datetime(2024, 1, 15)
        mock_conn = _mock_conn_with_papers(_make_paper(), [123])
        mock_get_conn.return_value = mock_conn
        cfg = _make_config(deliver_llm_timeout=42, openrouter_timeout=90)
        run_deliver(cfg)
        _, kwargs = mock_synth.call_args
        assert kwargs["timeout"] == 42

    @patch("api.deliver._notify_owner")
    @patch("api.deliver.mark_processed")
    @patch("api.deliver.synthesize_idea", return_value=(None, "error"))
    @patch("api.deliver.get_connection")
    @patch("api.deliver.datetime")
    def test_openrouter_timeout_not_passed_to_deliver(
            self, mock_dt, mock_get_conn, mock_synth, mock_mark, mock_notify):
        """openrouter_timeout (90s) must never be used as the deliver LLM timeout."""
        mock_dt.utcnow.return_value = datetime(2024, 1, 15)
        mock_conn = _mock_conn_with_papers(_make_paper(), [123])
        mock_get_conn.return_value = mock_conn
        cfg = _make_config(deliver_llm_timeout=50, openrouter_timeout=90)
        run_deliver(cfg)
        _, kwargs = mock_synth.call_args
        assert kwargs["timeout"] != 90


# ---------------------------------------------------------------------------
# _notify_owner
# ---------------------------------------------------------------------------

class TestNotifyOwner:

    @patch("api.deliver.send_message")
    def test_sends_to_all_telegram_chat_ids(self, mock_send):
        cfg = _make_config(telegram_chat_ids=[111, 222])
        _notify_owner(cfg, status="sent", idea_id=5, paper_id="2401.1234", model="gemini")
        assert mock_send.call_count == 2
        chat_ids_called = [c[0][0] for c in mock_send.call_args_list]
        assert sorted(chat_ids_called) == [111, 222]

    @patch("api.deliver.send_message")
    def test_sent_message_contains_idea_id(self, mock_send):
        cfg = _make_config(telegram_chat_ids=[1])
        _notify_owner(cfg, status="sent", idea_id=99, paper_id="p1", model="m")
        text = mock_send.call_args[0][1]
        assert "99" in text

    @patch("api.deliver.send_message")
    def test_skipped_message_contains_reason(self, mock_send):
        cfg = _make_config(telegram_chat_ids=[1])
        _notify_owner(cfg, status="skipped", reason="below_quality_gate", paper_id="p1")
        text = mock_send.call_args[0][1]
        assert "below_quality_gate" in text

    @patch("api.deliver.send_message", side_effect=Exception("network error"))
    def test_swallows_send_errors(self, mock_send):
        """_notify_owner must never raise even if send_message fails."""
        cfg = _make_config(telegram_chat_ids=[111])
        _notify_owner(cfg, status="sent", idea_id=1, paper_id="p1", model="m")
        # Reached here without raising — test passes


# ---------------------------------------------------------------------------
# Helper: mark_processed
# ---------------------------------------------------------------------------

class TestMarkProcessed:

    def test_marks_with_skip_reason(self):
        mock_cursor = MagicMock()
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mark_processed(mock_conn, "p1", skip_reason="llm_parse_error")
        sql = mock_cursor.execute.call_args[0][0]
        params = mock_cursor.execute.call_args[0][1]
        assert "processed=TRUE" in sql
        assert "skipped=TRUE" in sql
        assert params == ("llm_parse_error", "p1")
        mock_conn.commit.assert_called_once()

    def test_marks_without_skip_reason(self):
        mock_cursor = MagicMock()
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mark_processed(mock_conn, "p1")
        sql = mock_cursor.execute.call_args[0][0]
        assert "processed=TRUE" in sql
        assert "skipped" not in sql.lower() or "skipped=TRUE" not in sql
        mock_conn.commit.assert_called_once()


# ---------------------------------------------------------------------------
# Helper: is_duplicate
# ---------------------------------------------------------------------------

class TestIsDuplicate:

    def test_returns_true_when_match_found(self):
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = {"?column?": 1}
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        assert is_duplicate(mock_conn, [0.1] * 1536, 0.80) is True

    def test_returns_false_when_no_match(self):
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = None
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        assert is_duplicate(mock_conn, [0.1] * 1536, 0.80) is False

    def test_passes_embedding_and_threshold_to_query(self):
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = None
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        emb = [0.5] * 1536
        is_duplicate(mock_conn, emb, 0.75)
        params = mock_cursor.execute.call_args[0][1]
        assert params == (emb, 0.75)


# ---------------------------------------------------------------------------
# Helper: store_idea
# ---------------------------------------------------------------------------

class TestStoreIdea:

    def test_returns_idea_id(self):
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = {"id": 42}
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        idea = _make_idea()
        result = store_idea(mock_conn, "p1", idea, [0.1] * 1536)
        assert result == 42
        mock_conn.commit.assert_called_once()

    def test_inserts_all_idea_fields(self):
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = {"id": 1}
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        idea = _make_idea(novelty=6, feasibility=9)
        emb = [0.2] * 1536
        store_idea(mock_conn, "paper-123", idea, emb)
        params = mock_cursor.execute.call_args[0][1]
        assert params[0] == "paper-123"
        assert params[1] == idea["hypothesis"]
        assert params[2] == idea["method"]
        assert params[3] == idea["dataset"]
        assert params[4] == 6
        assert params[5] == 9
        assert params[6] == emb
