import math
from unittest.mock import patch, MagicMock

import numpy as np
import pytest

from lib.embeddings import embed_text, cosine_similarity, retrieve_doc_chunks


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


class TestRetrieveDocChunks:

    def _make_conn(self, rows):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchall.return_value = rows
        return conn, cur

    @patch("lib.embeddings.embed_text")
    def test_returns_mapped_chunks(self, mock_embed):
        mock_embed.return_value = [0.1] * 1536
        rows = [
            {"source": "docs/a.md", "heading": "Intro", "content": "Content A", "similarity": 0.95},
            {"source": "docs/b.md", "heading": "API", "content": "Content B", "similarity": 0.88},
        ]
        conn, _ = self._make_conn(rows)
        result = retrieve_doc_chunks("how does fetch work", conn, "sk-key", "openai/text-embedding-3-small", top_k=2)
        assert len(result) == 2
        assert result[0] == {"source": "docs/a.md", "heading": "Intro", "content": "Content A", "similarity": 0.95}
        assert result[1]["heading"] == "API"

    @patch("lib.embeddings.embed_text")
    def test_returns_empty_list_when_no_chunks(self, mock_embed):
        mock_embed.return_value = [0.1] * 1536
        conn, _ = self._make_conn([])
        result = retrieve_doc_chunks("query", conn, "sk-key", "model")
        assert result == []

    @patch("lib.embeddings.embed_text")
    def test_passes_top_k_to_query(self, mock_embed):
        mock_embed.return_value = [0.1] * 3
        conn, cur = self._make_conn([])
        retrieve_doc_chunks("query", conn, "sk-key", "model", top_k=5)
        args = cur.execute.call_args[0]
        assert args[1][2] == 5

    @patch("lib.embeddings.embed_text")
    def test_passes_embedding_list_as_vector_param(self, mock_embed):
        mock_embed.return_value = [0.5, 0.25]
        conn, cur = self._make_conn([])
        retrieve_doc_chunks("query", conn, "sk-key", "model")
        args = cur.execute.call_args[0]
        assert args[1][0] == [0.5, 0.25]

    @patch("lib.embeddings.embed_text")
    def test_similarity_cast_to_float(self, mock_embed):
        mock_embed.return_value = [0.1] * 1536
        conn, _ = self._make_conn([
            {"source": "s", "heading": "h", "content": "c", "similarity": 0.9},
        ])
        result = retrieve_doc_chunks("q", conn, "sk-key", "model")
        assert isinstance(result[0]["similarity"], float)
