import json
import sys
from io import BytesIO
from unittest.mock import patch, MagicMock

import pytest

sys.modules.setdefault("psycopg2", MagicMock())
sys.modules.setdefault("psycopg2.extras", MagicMock())

from api.chat import handler, _SYSTEM_PROMPT  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_handler(body: dict, ip: str = "1.2.3.4"):
    h = MagicMock(spec=handler)
    h.wfile = BytesIO()
    h.send_response = MagicMock()
    h.send_header = MagicMock()
    h.end_headers = MagicMock()
    h._respond = lambda status, body: handler._respond(h, status, body)
    h._handle_post = lambda: handler._handle_post(h)

    encoded = json.dumps(body).encode()
    h.headers = {"Content-Length": str(len(encoded)), "X-Forwarded-For": ip}
    h.rfile = BytesIO(encoded)
    return h


def _llm_response(text: str = "Test reply", tokens: int = 42):
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": text}}],
        "usage": {"total_tokens": tokens},
    }
    return mock_resp


def _call(body: dict, env: dict | None = None, chunks=None, ip: str = "1.2.3.4"):
    """Invoke handler.do_POST with mocked LLM, optional RAG chunks, and env vars."""
    if chunks is None:
        chunks = []
    env_defaults = {
        "OPENROUTER_API_KEY": "sk-test",
        "DATABASE_URL": "postgresql://localhost/test",
        "EMBEDDING_MODEL": "openai/text-embedding-3-small",
    }
    if env:
        env_defaults.update(env)

    h = _make_handler(body, ip=ip)
    with patch("api.chat.retrieve_doc_chunks", return_value=chunks) as mock_rag, \
         patch("api.chat.get_connection") as mock_conn, \
         patch("api.chat.httpx.post", return_value=_llm_response()) as mock_llm, \
         patch.dict("os.environ", env_defaults, clear=False):
        handler.do_POST(h)
    return h, mock_rag, mock_conn, mock_llm


# ---------------------------------------------------------------------------
# Response format
# ---------------------------------------------------------------------------

class TestSiteChatRespond:

    def test_respond_writes_json(self):
        h = _make_handler({"message": "hi"})
        handler._respond(h, 200, {"reply": "hello"})
        assert json.loads(h.wfile.getvalue()) == {"reply": "hello"}

    def test_respond_sets_cors_header(self):
        h = _make_handler({"message": "hi"})
        handler._respond(h, 200, {"reply": "x"})
        h.send_header.assert_any_call("Access-Control-Allow-Origin", "*")

    def test_respond_sets_content_type(self):
        h = _make_handler({"message": "hi"})
        handler._respond(h, 200, {"reply": "x"})
        h.send_header.assert_any_call("Content-Type", "application/json")


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------

class TestSiteChatValidation:

    def test_missing_message_returns_400(self):
        h, *_ = _call({})
        h.send_response.assert_called_with(400)

    def test_empty_message_returns_400(self):
        h, *_ = _call({"message": "   "})
        h.send_response.assert_called_with(400)

    def test_message_too_long_returns_400(self):
        h, *_ = _call({"message": "x" * 501})
        h.send_response.assert_called_with(400)

    def test_invalid_history_type_returns_400(self):
        h, *_ = _call({"message": "hi", "history": "not-a-list"})
        h.send_response.assert_called_with(400)

    def test_history_item_missing_role_returns_400(self):
        h, *_ = _call({"message": "hi", "history": [{"content": "oops"}]})
        h.send_response.assert_called_with(400)


# ---------------------------------------------------------------------------
# RAG retrieval
# ---------------------------------------------------------------------------

class TestSiteChatRAG:

    def test_retrieve_doc_chunks_called_with_user_message(self):
        h, mock_rag, mock_conn, _ = _call({"message": "how does fetch work?"})
        mock_rag.assert_called_once()
        call_args = mock_rag.call_args[0]
        assert call_args[0] == "how does fetch work?"

    def test_chunks_injected_into_system_prompt(self):
        chunks = [
            {"source": "docs/SPEC.md", "heading": "Fetch", "content": "Fetch runs at 06:00 UTC.", "similarity": 0.93},
        ]
        h, _, _, mock_llm = _call({"message": "when does fetch run?"}, chunks=chunks)
        payload = mock_llm.call_args[1]["json"]
        system_content = payload["messages"][0]["content"]
        assert "RELEVANT DOCUMENTATION" in system_content
        assert "Fetch runs at 06:00 UTC." in system_content
        assert "[docs/SPEC.md / Fetch]" in system_content

    def test_static_prompt_used_when_no_chunks(self):
        h, _, _, mock_llm = _call({"message": "what is axiom?"}, chunks=[])
        payload = mock_llm.call_args[1]["json"]
        system_content = payload["messages"][0]["content"]
        assert system_content == _SYSTEM_PROMPT

    def test_static_prompt_used_when_database_url_missing(self):
        h, mock_rag, _, mock_llm = _call(
            {"message": "what is axiom?"},
            env={"DATABASE_URL": ""},
        )
        mock_rag.assert_not_called()
        payload = mock_llm.call_args[1]["json"]
        assert payload["messages"][0]["content"] == _SYSTEM_PROMPT

    def test_fallback_to_static_prompt_on_rag_exception(self):
        h = _make_handler({"message": "what is axiom?"})
        with patch("api.chat.retrieve_doc_chunks", side_effect=Exception("db down")), \
             patch("api.chat.get_connection"), \
             patch("api.chat.httpx.post", return_value=_llm_response()) as mock_llm, \
             patch.dict("os.environ", {"OPENROUTER_API_KEY": "sk-test", "DATABASE_URL": "postgresql://localhost/test"}):
            handler.do_POST(h)
        payload = mock_llm.call_args[1]["json"]
        assert payload["messages"][0]["content"] == _SYSTEM_PROMPT

    def test_multiple_chunks_all_injected(self):
        chunks = [
            {"source": "docs/a.md", "heading": "A", "content": "Content A", "similarity": 0.95},
            {"source": "docs/b.md", "heading": "B", "content": "Content B", "similarity": 0.88},
            {"source": "docs/c.md", "heading": "C", "content": "Content C", "similarity": 0.80},
        ]
        h, _, _, mock_llm = _call({"message": "tell me everything"}, chunks=chunks)
        system_content = mock_llm.call_args[1]["json"]["messages"][0]["content"]
        assert "Content A" in system_content
        assert "Content B" in system_content
        assert "Content C" in system_content


# ---------------------------------------------------------------------------
# LLM call construction
# ---------------------------------------------------------------------------

class TestSiteChatLLM:

    def test_returns_200_with_reply(self):
        h, *_ = _call({"message": "hello"})
        h.send_response.assert_called_with(200)
        result = json.loads(h.wfile.getvalue())
        assert result["reply"] == "Test reply"
        assert result["tokens_used"] == 42

    def test_history_appended_to_messages(self):
        history = [
            {"role": "user", "content": "first question"},
            {"role": "assistant", "content": "first answer"},
        ]
        h, _, _, mock_llm = _call({"message": "follow-up", "history": history})
        messages = mock_llm.call_args[1]["json"]["messages"]
        roles = [m["role"] for m in messages]
        assert roles == ["system", "user", "assistant", "user"]

    def test_missing_api_key_returns_500(self):
        h, *_ = _call({"message": "hi"}, env={"OPENROUTER_API_KEY": ""})
        h.send_response.assert_called_with(500)
        result = json.loads(h.wfile.getvalue())
        assert result["error"] == "config_error"
