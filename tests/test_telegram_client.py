from unittest.mock import patch, MagicMock, call

import pytest

from lib.telegram_client import (
    TELEGRAM_BASE,
    _sanitize,
    esc,
    send_message,
    send_idea_message,
    register_webhook,
)


class TestTelegramBase:

    def test_base_url(self):
        assert TELEGRAM_BASE == "https://api.telegram.org"


class TestSendMessage:

    @patch("lib.telegram_client.httpx.post")
    def test_posts_to_correct_url(self, mock_post):
        mock_post.return_value = MagicMock(raise_for_status=MagicMock())
        send_message(123, "hello", "tok123")
        url = mock_post.call_args[0][0]
        assert url == "https://api.telegram.org/bottok123/sendMessage"

    @patch("lib.telegram_client.httpx.post")
    def test_payload_without_parse_mode(self, mock_post):
        mock_post.return_value = MagicMock(raise_for_status=MagicMock())
        send_message(123, "hello", "tok123")
        payload = mock_post.call_args[1]["json"]
        assert payload == {"chat_id": 123, "text": "hello"}
        assert "parse_mode" not in payload

    @patch("lib.telegram_client.httpx.post")
    def test_payload_with_parse_mode(self, mock_post):
        mock_post.return_value = MagicMock(raise_for_status=MagicMock())
        send_message(123, "hello", "tok123", parse_mode="MarkdownV2")
        payload = mock_post.call_args[1]["json"]
        assert payload["parse_mode"] == "MarkdownV2"

    @patch("lib.telegram_client.httpx.post")
    def test_timeout_is_ten_seconds(self, mock_post):
        mock_post.return_value = MagicMock(raise_for_status=MagicMock())
        send_message(123, "hi", "tok123")
        assert mock_post.call_args[1]["timeout"] == 10

    @patch("lib.telegram_client.httpx.post")
    def test_raises_on_http_error(self, mock_post):
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = Exception("HTTP error")
        mock_post.return_value = mock_response
        with pytest.raises(Exception, match="HTTP error"):
            send_message(123, "hi", "tok123")


class TestSendIdeaMessage:

    def _make_idea(self, novelty=7, feasibility=8):
        return {
            "hypothesis": "Test hypothesis",
            "method": "Test method",
            "dataset": "Test dataset",
            "novelty_score": novelty,
            "feasibility_score": feasibility,
        }

    @patch("lib.telegram_client.httpx.post")
    def test_posts_to_correct_url(self, mock_post):
        mock_post.return_value = MagicMock(raise_for_status=MagicMock())
        send_idea_message(123, 42, "Title", "https://arxiv.org/abs/123", self._make_idea(), "tok")
        url = mock_post.call_args[0][0]
        assert url == "https://api.telegram.org/bottok/sendMessage"

    @patch("lib.telegram_client.httpx.post")
    def test_uses_markdownv2_parse_mode(self, mock_post):
        mock_post.return_value = MagicMock(raise_for_status=MagicMock())
        send_idea_message(123, 42, "Title", "https://arxiv.org/abs/123", self._make_idea(), "tok")
        payload = mock_post.call_args[1]["json"]
        assert payload["parse_mode"] == "MarkdownV2"

    @patch("lib.telegram_client.httpx.post")
    def test_disables_web_page_preview(self, mock_post):
        mock_post.return_value = MagicMock(raise_for_status=MagicMock())
        send_idea_message(123, 42, "Title", "https://arxiv.org/abs/123", self._make_idea(), "tok")
        payload = mock_post.call_args[1]["json"]
        assert payload["disable_web_page_preview"] is True

    @patch("lib.telegram_client.httpx.post")
    def test_inline_keyboard_buttons(self, mock_post):
        mock_post.return_value = MagicMock(raise_for_status=MagicMock())
        send_idea_message(123, 42, "Title", "https://arxiv.org/abs/123", self._make_idea(), "tok")
        payload = mock_post.call_args[1]["json"]
        keyboard = payload["reply_markup"]["inline_keyboard"]
        assert len(keyboard) == 1
        buttons = keyboard[0]
        assert len(buttons) == 3

    @patch("lib.telegram_client.httpx.post")
    def test_expand_button_absent_by_default(self, mock_post):
        mock_post.return_value = MagicMock(raise_for_status=MagicMock())
        send_idea_message(123, 42, "Title", "https://arxiv.org/abs/123", self._make_idea(), "tok")
        keyboard = mock_post.call_args[1]["json"]["reply_markup"]["inline_keyboard"]
        all_callbacks = [b.get("callback_data", "") for row in keyboard for b in row]
        assert not any(c.startswith("expand:") for c in all_callbacks)

    @patch("lib.telegram_client.httpx.post")
    def test_expand_button_present_when_enabled(self, mock_post):
        mock_post.return_value = MagicMock(raise_for_status=MagicMock())
        send_idea_message(
            123, 42, "Title", "https://arxiv.org/abs/123", self._make_idea(), "tok",
            expand_enabled=True,
        )
        keyboard = mock_post.call_args[1]["json"]["reply_markup"]["inline_keyboard"]
        assert len(keyboard) == 2
        assert keyboard[1][0]["callback_data"] == "expand:42"

    @patch("lib.telegram_client.httpx.post")
    def test_expand_button_on_second_row(self, mock_post):
        mock_post.return_value = MagicMock(raise_for_status=MagicMock())
        send_idea_message(
            123, 42, "Title", "https://arxiv.org/abs/123", self._make_idea(), "tok",
            expand_enabled=True,
        )
        keyboard = mock_post.call_args[1]["json"]["reply_markup"]["inline_keyboard"]
        # First row still has 3 buttons
        assert len(keyboard[0]) == 3
        # Second row has only the Expand button
        assert len(keyboard[1]) == 1

    @patch("lib.telegram_client.httpx.post")
    def test_feedback_callback_data_format(self, mock_post):
        mock_post.return_value = MagicMock(raise_for_status=MagicMock())
        send_idea_message(123, 42, "Title", "https://arxiv.org/abs/123", self._make_idea(), "tok")
        buttons = mock_post.call_args[1]["json"]["reply_markup"]["inline_keyboard"][0]
        assert buttons[0]["callback_data"] == "feedback:42:1"
        assert buttons[1]["callback_data"] == "feedback:42:-1"

    @patch("lib.telegram_client.httpx.post")
    def test_paper_button_has_url(self, mock_post):
        mock_post.return_value = MagicMock(raise_for_status=MagicMock())
        url = "https://arxiv.org/abs/2401.12345"
        send_idea_message(123, 42, "Title", url, self._make_idea(), "tok")
        buttons = mock_post.call_args[1]["json"]["reply_markup"]["inline_keyboard"][0]
        assert buttons[2]["url"] == url

    @patch("lib.telegram_client.httpx.post")
    def test_score_bar_in_message(self, mock_post):
        mock_post.return_value = MagicMock(raise_for_status=MagicMock())
        idea = self._make_idea(novelty=3)
        send_idea_message(123, 42, "Title", "https://arxiv.org/abs/123", idea, "tok")
        text = mock_post.call_args[1]["json"]["text"]
        expected_bar = "\u2588" * 3 + "\u2591" * 7
        assert expected_bar in text

    @patch("lib.telegram_client.httpx.post")
    def test_scores_displayed_in_message(self, mock_post):
        mock_post.return_value = MagicMock(raise_for_status=MagicMock())
        idea = self._make_idea(novelty=7, feasibility=8)
        send_idea_message(123, 42, "Title", "https://arxiv.org/abs/123", idea, "tok")
        text = mock_post.call_args[1]["json"]["text"]
        assert "7/10" in text
        assert "8/10" in text

    @patch("lib.telegram_client.httpx.post")
    def test_timeout_is_ten_seconds(self, mock_post):
        mock_post.return_value = MagicMock(raise_for_status=MagicMock())
        send_idea_message(123, 42, "Title", "https://arxiv.org/abs/123", self._make_idea(), "tok")
        assert mock_post.call_args[1]["timeout"] == 10


class TestEscMarkdownV2:

    @patch("lib.telegram_client.httpx.post")
    def test_escapes_special_characters(self, mock_post):
        mock_post.return_value = MagicMock(raise_for_status=MagicMock())
        idea = self._make_idea()
        idea["hypothesis"] = "Test with special chars: _*[]()~`>#+-=|{}.!"
        send_idea_message(123, 42, "Title", "https://arxiv.org/abs/123", idea, "tok")
        text = mock_post.call_args[1]["json"]["text"]
        # Each special char should be escaped with backslash
        assert r"\_" in text
        assert r"\*" in text or "\\*" in text

    def _make_idea(self, novelty=7, feasibility=8):
        return {
            "hypothesis": "Test hypothesis",
            "method": "Test method",
            "dataset": "Test dataset",
            "novelty_score": novelty,
            "feasibility_score": feasibility,
        }

    @patch("lib.telegram_client.httpx.post")
    def test_plain_text_unchanged(self, mock_post):
        mock_post.return_value = MagicMock(raise_for_status=MagicMock())
        idea = self._make_idea()
        idea["hypothesis"] = "plain text no special chars"
        send_idea_message(123, 42, "Title", "https://arxiv.org/abs/123", idea, "tok")
        text = mock_post.call_args[1]["json"]["text"]
        assert "plain text no special chars" in text


class TestSanitize:

    def test_strips_lone_surrogates(self):
        text = "hello \ud800 world"
        result = _sanitize(text)
        assert "\ud800" not in result
        assert "hello" in result
        assert "world" in result

    def test_leaves_normal_text_unchanged(self):
        text = "normal text with unicode: \u00e9\u00e0\u00fc"
        assert _sanitize(text) == text

    @patch("lib.telegram_client.httpx.post")
    def test_send_message_handles_surrogates(self, mock_post):
        mock_post.return_value = MagicMock(raise_for_status=MagicMock())
        send_message(123, "text with \ud800 surrogate", "tok123")
        payload = mock_post.call_args[1]["json"]
        assert "\ud800" not in payload["text"]


class TestRegisterWebhook:

    @patch("lib.telegram_client.httpx.post")
    def test_posts_to_correct_url(self, mock_post):
        mock_post.return_value = MagicMock(
            raise_for_status=MagicMock(),
            json=MagicMock(return_value={"ok": True}),
        )
        register_webhook("tok123", "https://example.com/webhook", "secret123")
        url = mock_post.call_args[0][0]
        assert url == "https://api.telegram.org/bottok123/setWebhook"

    @patch("lib.telegram_client.httpx.post")
    def test_payload_includes_webhook_url(self, mock_post):
        mock_post.return_value = MagicMock(
            raise_for_status=MagicMock(),
            json=MagicMock(return_value={"ok": True}),
        )
        register_webhook("tok123", "https://example.com/webhook", "secret123")
        payload = mock_post.call_args[1]["json"]
        assert payload["url"] == "https://example.com/webhook"

    @patch("lib.telegram_client.httpx.post")
    def test_payload_includes_secret_token(self, mock_post):
        mock_post.return_value = MagicMock(
            raise_for_status=MagicMock(),
            json=MagicMock(return_value={"ok": True}),
        )
        register_webhook("tok123", "https://example.com/webhook", "secret123")
        payload = mock_post.call_args[1]["json"]
        assert payload["secret_token"] == "secret123"

    @patch("lib.telegram_client.httpx.post")
    def test_allowed_updates(self, mock_post):
        mock_post.return_value = MagicMock(
            raise_for_status=MagicMock(),
            json=MagicMock(return_value={"ok": True}),
        )
        register_webhook("tok123", "https://example.com/webhook", "secret123")
        payload = mock_post.call_args[1]["json"]
        assert payload["allowed_updates"] == ["message", "callback_query"]

    @patch("lib.telegram_client.httpx.post")
    def test_returns_response_json(self, mock_post):
        mock_post.return_value = MagicMock(
            raise_for_status=MagicMock(),
            json=MagicMock(return_value={"ok": True, "result": True}),
        )
        result = register_webhook("tok123", "https://example.com/webhook", "secret123")
        assert result == {"ok": True, "result": True}
