import sys
import json
from io import BytesIO
from unittest.mock import patch, MagicMock, call

import pytest

# Mock psycopg2 before importing api.telegram
sys.modules.setdefault("psycopg2", MagicMock())
sys.modules.setdefault("psycopg2.extras", MagicMock())

from api.telegram import (  # noqa: E402
    handler, handle_message, handle_callback,
    handle_status, handle_topics, handle_pause,
    handle_resume, handle_feedback_summary,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config(**overrides):
    defaults = {
        "telegram_bot_token": "tok",
        "telegram_webhook_secret": "correct-secret",
        "telegram_chat_ids": [1],
        "bot_password": "s3cret-password",
        "database_url": "postgresql://localhost/test",
        "openrouter_api_key": "key",
        "default_model": "m",
        "deepdive_model": "m2",
        "deepdive_day": 4,
        "cron_secret": "cron",
    }
    defaults.update(overrides)
    cfg = MagicMock()
    for k, v in defaults.items():
        setattr(cfg, k, v)
    return cfg


def _mock_cursor_returning(*fetchone_returns):
    """Create a mock conn whose cursor returns the given values on successive fetchone calls."""
    mock_cursor = MagicMock()
    mock_cursor.fetchone.side_effect = list(fetchone_returns) if len(fetchone_returns) > 1 \
        else [fetchone_returns[0]]
    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    return mock_conn, mock_cursor


def _make_handler_mock(secret="correct-secret", body=None):
    """Create a mock handler for do_POST tests."""
    h = MagicMock(spec=handler)
    h.headers = {
        "X-Telegram-Bot-Api-Secret-Token": secret,
        "Content-Length": str(len(json.dumps(body or {}).encode())),
    }
    h.rfile = BytesIO(json.dumps(body or {}).encode())
    h.send_response = MagicMock()
    h.end_headers = MagicMock()
    return h


# ---------------------------------------------------------------------------
# Layer 1: webhook secret verification
# ---------------------------------------------------------------------------

class TestWebhookSecretRejection:

    @patch("api.telegram.load_config")
    @patch("api.telegram.get_connection")
    def test_wrong_secret_returns_401(self, mock_conn, mock_cfg):
        mock_cfg.return_value = _make_config()
        h = _make_handler_mock(secret="wrong-secret", body={"message": {}})
        handler.do_POST(h)
        h.send_response.assert_called_with(401)

    @patch("api.telegram.load_config")
    @patch("api.telegram.get_connection")
    def test_missing_secret_returns_401(self, mock_conn, mock_cfg):
        mock_cfg.return_value = _make_config()
        h = _make_handler_mock(secret="", body={"message": {}})
        handler.do_POST(h)
        h.send_response.assert_called_with(401)

    @patch("api.telegram.handle_message")
    @patch("api.telegram.load_config")
    @patch("api.telegram.get_connection")
    def test_correct_secret_returns_200(self, mock_conn_fn, mock_cfg, mock_handle):
        mock_cfg.return_value = _make_config()
        mock_conn_fn.return_value = MagicMock()
        body = {"message": {"from": {"id": 1}, "chat": {"id": 1}, "text": "/status"}}
        h = _make_handler_mock(secret="correct-secret", body=body)
        handler.do_POST(h)
        h.send_response.assert_called_with(200)


# ---------------------------------------------------------------------------
# Layer 2: unknown user silent ignore
# ---------------------------------------------------------------------------

class TestUnknownUserSilentIgnore:

    @patch("api.telegram.send_message")
    def test_unknown_user_gets_no_response(self, mock_send):
        mock_conn, mock_cursor = _mock_cursor_returning(None)  # user not found
        cfg = _make_config()
        msg = {
            "from": {"id": 99999},
            "chat": {"id": 99999},
            "text": "/status",
        }
        handle_message(msg, mock_conn, cfg)
        mock_send.assert_not_called()


# ---------------------------------------------------------------------------
# /start authentication
# ---------------------------------------------------------------------------

class TestStartAuthentication:

    @patch("api.telegram.send_message")
    def test_correct_password_inserts_user(self, mock_send):
        mock_conn, mock_cursor = _mock_cursor_returning(None)  # not already allowed
        cfg = _make_config()
        msg = {
            "from": {"id": 12345, "username": "testuser", "first_name": "Test"},
            "chat": {"id": 12345},
            "text": "/start s3cret-password",
        }
        handle_message(msg, mock_conn, cfg)
        # Verify INSERT was called
        insert_calls = [c for c in mock_cursor.execute.call_args_list
                        if "INSERT INTO allowed_users" in str(c)]
        assert len(insert_calls) == 1
        mock_conn.commit.assert_called()
        mock_send.assert_called_once()
        assert "Access granted" in mock_send.call_args[0][1]

    @patch("api.telegram.send_message")
    def test_wrong_password_sends_invalid(self, mock_send):
        mock_conn, mock_cursor = _mock_cursor_returning(None)
        cfg = _make_config()
        msg = {
            "from": {"id": 12345},
            "chat": {"id": 12345},
            "text": "/start wrong-password",
        }
        handle_message(msg, mock_conn, cfg)
        mock_send.assert_called_once()
        assert "Invalid token" in mock_send.call_args[0][1]

    @patch("api.telegram.send_message")
    def test_already_authorized_user_gets_message(self, mock_send):
        mock_conn, mock_cursor = _mock_cursor_returning({"user_id": 12345})  # already allowed
        cfg = _make_config()
        msg = {
            "from": {"id": 12345},
            "chat": {"id": 12345},
            "text": "/start s3cret-password",
        }
        handle_message(msg, mock_conn, cfg)
        mock_send.assert_called_once()
        assert "already have access" in mock_send.call_args[0][1]

    @patch("api.telegram.send_message")
    def test_start_without_token_sends_invalid(self, mock_send):
        mock_conn, mock_cursor = _mock_cursor_returning(None)
        cfg = _make_config()
        msg = {
            "from": {"id": 12345},
            "chat": {"id": 12345},
            "text": "/start",
        }
        handle_message(msg, mock_conn, cfg)
        mock_send.assert_called_once()
        assert "Invalid token" in mock_send.call_args[0][1]


# ---------------------------------------------------------------------------
# Callback: feedback handling
# ---------------------------------------------------------------------------

class TestCallbackFeedback:

    @patch("httpx.post")
    def test_unauthorized_user_callback_ignored(self, mock_post):
        mock_conn, mock_cursor = _mock_cursor_returning(None)
        cfg = _make_config()
        cb = {"from": {"id": 99999}, "data": "feedback:1:1", "id": "cb1"}
        handle_callback(cb, mock_conn, cfg)
        # Should not insert feedback
        insert_calls = [c for c in mock_cursor.execute.call_args_list
                        if "INSERT INTO idea_feedback" in str(c)]
        assert len(insert_calls) == 0

    @patch("httpx.post")
    def test_positive_feedback_inserts_and_boosts_weights(self, mock_post):
        mock_cursor = MagicMock()
        # First fetchone: user exists
        mock_cursor.fetchone.return_value = {"user_id": 123}
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        cfg = _make_config()
        cb = {"from": {"id": 123}, "data": "feedback:42:1", "id": "cb1"}
        handle_callback(cb, mock_conn, cfg)
        # Verify feedback insert and topic weight boost
        sql_calls = [str(c) for c in mock_cursor.execute.call_args_list]
        assert any("INSERT INTO idea_feedback" in s for s in sql_calls)
        assert any("LEAST(weight + 0.1, 3.0)" in s for s in sql_calls)
        mock_conn.commit.assert_called()

    @patch("httpx.post")
    def test_negative_feedback_reduces_weights(self, mock_post):
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = {"user_id": 123}
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        cfg = _make_config()
        cb = {"from": {"id": 123}, "data": "feedback:42:-1", "id": "cb1"}
        handle_callback(cb, mock_conn, cfg)
        sql_calls = [str(c) for c in mock_cursor.execute.call_args_list]
        assert any("GREATEST(weight - 0.05, 0.1)" in s for s in sql_calls)

    @patch("httpx.post")
    def test_answers_callback_query(self, mock_post):
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = {"user_id": 123}
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        cfg = _make_config()
        cb = {"from": {"id": 123}, "data": "feedback:42:1", "id": "cb-xyz"}
        handle_callback(cb, mock_conn, cfg)
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        assert "answerCallbackQuery" in call_args[0][0]
        assert call_args[1]["json"]["callback_query_id"] == "cb-xyz"


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

class TestHandleStatus:

    @patch("api.telegram.send_message")
    def test_sends_status_message(self, mock_send):
        mock_cursor = MagicMock()
        mock_cursor.fetchone.side_effect = [
            {"count": 50},   # papers fetched today
            {"count": 5},    # queued
            {"count": 2},    # sent today
        ]
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        cfg = _make_config()
        handle_status(123, mock_conn, cfg)
        mock_send.assert_called_once()
        text = mock_send.call_args[0][1]
        assert "50" in text
        assert "5" in text
        assert "2" in text


class TestHandleTopics:

    @patch("api.telegram.send_message")
    def test_sends_topic_weights(self, mock_send):
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            {"topic": "momentum", "weight": 2.5},
            {"topic": "factor model", "weight": 1.0},
        ]
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        cfg = _make_config()
        handle_topics(123, mock_conn, cfg)
        mock_send.assert_called_once()
        text = mock_send.call_args[0][1]
        assert "momentum" in text
        assert "2.50" in text


class TestHandlePause:

    @patch("api.telegram.send_message")
    def test_pause_updates_db_and_sends_message(self, mock_send):
        mock_cursor = MagicMock()
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        cfg = _make_config()
        handle_pause(123, 123, mock_conn, cfg)
        sql = mock_cursor.execute.call_args[0][0]
        assert "paused=TRUE" in sql
        mock_conn.commit.assert_called()
        mock_send.assert_called_once()
        assert "paused" in mock_send.call_args[0][1].lower()


class TestHandleResume:

    @patch("api.telegram.send_message")
    def test_resume_updates_db_and_sends_message(self, mock_send):
        mock_cursor = MagicMock()
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        cfg = _make_config()
        handle_resume(123, 123, mock_conn, cfg)
        sql = mock_cursor.execute.call_args[0][0]
        assert "paused=FALSE" in sql
        mock_conn.commit.assert_called()
        mock_send.assert_called_once()
        assert "resumed" in mock_send.call_args[0][1].lower()


class TestHandleFeedbackSummary:

    @patch("api.telegram.send_message")
    def test_sends_feedback_counts(self, mock_send):
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = {"likes": 10, "dislikes": 3}
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        cfg = _make_config()
        handle_feedback_summary(123, 123, mock_conn, cfg)
        mock_send.assert_called_once()
        text = mock_send.call_args[0][1]
        assert "10" in text
        assert "3" in text

    @patch("api.telegram.send_message")
    def test_handles_no_feedback(self, mock_send):
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = {"likes": None, "dislikes": None}
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        cfg = _make_config()
        handle_feedback_summary(123, 123, mock_conn, cfg)
        text = mock_send.call_args[0][1]
        assert "0" in text


# ---------------------------------------------------------------------------
# Message routing
# ---------------------------------------------------------------------------

class TestMessageRouting:

    @patch("api.telegram.handle_feedback_summary")
    @patch("api.telegram.handle_resume")
    @patch("api.telegram.handle_pause")
    @patch("api.telegram.handle_topics")
    @patch("api.telegram.handle_status")
    @patch("api.telegram.send_message")
    def test_routes_to_correct_handler(self, mock_send, mock_status, mock_topics,
                                        mock_pause, mock_resume, mock_feedback):
        cfg = _make_config()
        commands = {
            "/status": mock_status,
            "/topics": mock_topics,
            "/pause": mock_pause,
            "/resume": mock_resume,
            "/feedback": mock_feedback,
        }
        for cmd, expected_mock in commands.items():
            expected_mock.reset_mock()
            mock_cursor = MagicMock()
            mock_cursor.fetchone.return_value = {"paused": False, "pause_until": None}
            mock_conn = MagicMock()
            mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
            mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
            msg = {"from": {"id": 123}, "chat": {"id": 123}, "text": cmd}
            handle_message(msg, mock_conn, cfg)
            assert expected_mock.called, f"Expected {cmd} to call {expected_mock}"
