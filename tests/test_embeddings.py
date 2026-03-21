import math
from unittest.mock import patch, MagicMock

import numpy as np
import pytest

import lib.embeddings as embeddings_module
from lib.embeddings import cosine_similarity


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
        v = [0.1] * 384
        assert cosine_similarity(v, v) == pytest.approx(1.0)


class TestGetModel:

    def test_lazy_load_returns_model(self):
        mock_model = MagicMock()
        with patch.object(embeddings_module, "_model", None):
            with patch("lib.embeddings.SentenceTransformer", create=True) as mock_cls:
                mock_cls.return_value = mock_model
                # Need to patch the import inside _get_model
                with patch.dict("sys.modules", {"sentence_transformers": MagicMock(SentenceTransformer=mock_cls)}):
                    result = embeddings_module._get_model()
                    assert result is not None

    def test_model_cached_after_first_load(self):
        sentinel = MagicMock()
        with patch.object(embeddings_module, "_model", sentinel):
            result = embeddings_module._get_model()
            assert result is sentinel


class TestEmbedText:

    def _mock_model(self):
        mock = MagicMock()
        mock.encode.return_value = np.random.randn(384).astype(np.float32)
        return mock

    @patch.object(embeddings_module, "_get_model")
    def test_returns_list_of_floats(self, mock_get_model):
        mock_get_model.return_value = self._mock_model()
        result = embeddings_module.embed_text("test text")
        assert isinstance(result, list)
        assert all(isinstance(x, float) for x in result)

    @patch.object(embeddings_module, "_get_model")
    def test_returns_384_dimensions(self, mock_get_model):
        mock_get_model.return_value = self._mock_model()
        result = embeddings_module.embed_text("test text")
        assert len(result) == 384

    @patch.object(embeddings_module, "_get_model")
    def test_calls_encode_with_normalize(self, mock_get_model):
        mock_model = self._mock_model()
        mock_get_model.return_value = mock_model
        embeddings_module.embed_text("hello world")
        mock_model.encode.assert_called_once_with("hello world", normalize_embeddings=True)

    @patch.object(embeddings_module, "_get_model")
    def test_calls_get_model(self, mock_get_model):
        mock_get_model.return_value = self._mock_model()
        embeddings_module.embed_text("anything")
        mock_get_model.assert_called_once()

    @patch.object(embeddings_module, "_get_model")
    def test_tolist_called_on_result(self, mock_get_model):
        mock_model = MagicMock()
        mock_array = MagicMock()
        mock_array.tolist.return_value = [0.1] * 384
        mock_model.encode.return_value = mock_array
        mock_get_model.return_value = mock_model

        result = embeddings_module.embed_text("test")
        mock_array.tolist.assert_called_once()
        assert result == [0.1] * 384
