import pytest
from unittest.mock import MagicMock, patch
from lib.chat import check_rate_limits, generate_chat_response

def test_check_rate_limits_passes_fresh_user():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    
    # Mock all queries to return 0 or small values
    cur.fetchone.side_effect = [
        {"message_count": 0}, # session count
        {"count": 0},         # active sessions
        {"count": 0},         # hourly messages
        {"total": 0}          # daily tokens
    ]
    
    allowed, msg = check_rate_limits(123, 1, conn)
    assert allowed is True
    assert msg == ""

def test_check_rate_limits_blocks_session_limit():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    
    # Mock session message count at 20
    cur.fetchone.return_value = {"message_count": 20}
    
    allowed, msg = check_rate_limits(123, 1, conn)
    assert allowed is False
    assert "Session message limit reached" in msg

@patch("httpx.Client")
def test_generate_chat_response_builds_correct_payload(mock_client_class):
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "choices": [{"message": {"content": "Test response"}}],
        "usage": {"total_tokens": 100}
    }
    mock_response.raise_for_status = MagicMock()
    
    mock_client_instance = mock_client_class.return_value.__enter__.return_value
    mock_client_instance.post.return_value = mock_response
    
    context = {
        "title": "Paper Title",
        "abstract": "Abstract",
        "hypothesis": "Hypothesis",
        "method": "Method",
        "dataset": "Dataset",
        "novelty_score": 8,
        "feasibility_score": 7,
        "messages": [{"role": "user", "content": "Previous hi"}]
    }
    
    # Ensure prompts/chat_system.txt exists or mock open
    with patch("builtins.open", MagicMock(return_value=MagicMock(__enter__=MagicMock(return_value=MagicMock(read=MagicMock(return_value="System {title}")))))):
        response, tokens = generate_chat_response(context, "New msg", "model", "key", 10)
    
    assert response == "Test response"
    assert tokens == 100
    
    # Verify payload
    args, kwargs = mock_client_instance.post.call_args
    payload = kwargs["json"]
    assert payload["model"] == "model"
    assert len(payload["messages"]) == 3 # System + 1 history + 1 new user
    assert payload["messages"][0]["role"] == "system"
    assert payload["messages"][1]["content"] == "Previous hi"
    assert payload["messages"][2]["content"] == "New msg"
