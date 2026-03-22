import math
from unittest.mock import patch, MagicMock

import numpy as np
import pytest

from lib.embeddings import embed_text, cosine_similarity


class TestCosineSimlarity:

    def test_identical_vectors_return_one(self):
        v = [1.0, 0.0, 0.0]
        assert cosine_similarity(v, v) == pytest.approx(1.0)

    def test_orthogonal_vectors_return_zero(self):
        a = [1.0, 0.0, 0.0]
        b = [0.0, 1.0, 0.0]
        assert cosine_similarity(a, b) == pytest.approx(0.0)

    def test_opposite_vectors_return_negative_one(self):
        a = [1.0, 0.0]
        b = [-1.0, 0.0]
        assert cosine_similarity(a, b) == pytest.approx(-1.0)

    def test_similar_vectors_positive(self):
        a = [1.0, 1.0, 0.0]
        b = [1.0, 0.0, 0.0]
        result = cosine_similarity(a, b)
        assert 0.0 < result < 1.0

    def test_returns_float(self):
        a = [1.0, 2.0, 3.0]
        b = [4.0, 5.0, 6.0]
        result = cosine_similarity(a, b)
        assert isinstance(result, float)

    def test_known_value(self):
        a = [1.0, 2.0, 3.0]
        b = [4.0, 5.0, 6.0]
        # Manual calculation
        dot = 1*4 + 2*5 + 3*6  # 32
        norm_a = math.sqrt(1 + 4 + 9)  # sqrt(14)
        norm_b = math.sqrt(16 + 25 + 36)  # sqrt(77)
        expected = dot / (norm_a * norm_b)
        assert cosine_similarity(a, b) == pytest.approx(expected)

    def test_normalized_vectors(self):
        # Pre-normalized vectors should still work correctly
        a = [1.0 / math.sqrt(2), 1.0 / math.sqrt(2)]
        b = [1.0, 0.0]
        result = cosine_similarity(a, b)
        assert result == pytest.approx(1.0 / math.sqrt(2))

    def test_high_dimensional_identical(self):
        v = [0.1] * 1536
        assert cosine_similarity(v, v) == pytest.approx(1.0)


class TestEmbedText:

    @patch("lib.embeddings.httpx.post")
    def test_returns_list_of_floats(self, mock_post):
        mock_post.return_value = MagicMock(
            json=lambda: {"data": [{"embedding": [0.1] * 1536}]},
            raise_for_status=MagicMock(),
        )
        result = embed_text("test text", model="openai/text-embedding-3-small", api_key="sk-test")
        assert isinstance(result, list)
        assert all(isinstance(x, float) for x in result)

    @patch("lib.embeddings.httpx.post")
    def test_returns_1536_dimensions(self, mock_post):
        mock_post.return_value = MagicMock(
            json=lambda: {"data": [{"embedding": [0.1] * 1536}]},
            raise_for_status=MagicMock(),
        )
        result = embed_text("test text", model="openai/text-embedding-3-small", api_key="sk-test")
        assert len(result) == 1536

    @patch("lib.embeddings.httpx.post")
    def test_calls_openrouter_embeddings_endpoint(self, mock_post):
        mock_post.return_value = MagicMock(
            json=lambda: {"data": [{"embedding": [0.1] * 1536}]},
            raise_for_status=MagicMock(),
        )
        embed_text("hello world", model="openai/text-embedding-3-small", api_key="sk-test")
        call_args = mock_post.call_args
        assert call_args[0][0] == "https://openrouter.ai/api/v1/embeddings"

    @patch("lib.embeddings.httpx.post")
    def test_sends_correct_headers(self, mock_post):
        mock_post.return_value = MagicMock(
            json=lambda: {"data": [{"embedding": [0.1] * 1536}]},
            raise_for_status=MagicMock(),
        )
        embed_text("hello", model="openai/text-embedding-3-small", api_key="sk-my-key")
        headers = mock_post.call_args[1]["headers"]
        assert headers["Authorization"] == "Bearer sk-my-key"
        assert headers["HTTP-Referer"] == "https://axiom.app"
        assert headers["X-Title"] == "Axiom"

    @patch("lib.embeddings.httpx.post")
    def test_sends_correct_body(self, mock_post):
        mock_post.return_value = MagicMock(
            json=lambda: {"data": [{"embedding": [0.1] * 1536}]},
            raise_for_status=MagicMock(),
        )
        embed_text("test input", model="openai/text-embedding-3-small", api_key="sk-test")
        body = mock_post.call_args[1]["json"]
        assert body["model"] == "openai/text-embedding-3-small"
        assert body["input"] == "test input"

    @patch("lib.embeddings.httpx.post")
    def test_raises_on_http_error(self, mock_post):
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = Exception("401 Unauthorized")
        mock_post.return_value = mock_response
        with pytest.raises(Exception, match="401"):
            embed_text("test", model="m", api_key="bad-key")
