import sys
from unittest.mock import patch, MagicMock

import pytest

# Mock psycopg2 before importing lib.filter (which imports lib.db)
sys.modules.setdefault("psycopg2", MagicMock())
sys.modules.setdefault("psycopg2.extras", MagicMock())

from lib.filter import RelevanceFilter, _parse_vector  # noqa: E402


class TestRelevanceFilterInit:

    def test_topics_lowercased(self):
        rf = RelevanceFilter(topics=["Momentum", "VOLATILITY"], threshold=0.65)
        assert rf.topics == ["momentum", "volatility"]

    def test_topics_stripped(self):
        rf = RelevanceFilter(topics=["  momentum  ", "volatility  "], threshold=0.65)
        assert rf.topics == ["momentum", "volatility"]

    def test_threshold_stored(self):
        rf = RelevanceFilter(topics=["momentum"], threshold=0.7)
        assert rf.threshold == 0.7

    def test_seed_embeddings_initially_none(self):
        rf = RelevanceFilter(topics=["momentum"], threshold=0.65)
        assert rf._seed_embeddings is None

    def test_database_url_default_none(self):
        rf = RelevanceFilter(topics=["momentum"], threshold=0.65)
        assert rf._database_url is None

    def test_database_url_stored(self):
        rf = RelevanceFilter(topics=["momentum"], threshold=0.65, database_url="postgresql://localhost/test")
        assert rf._database_url == "postgresql://localhost/test"

    def test_api_key_stored(self):
        rf = RelevanceFilter(topics=["momentum"], threshold=0.65, api_key="sk-test")
        assert rf._api_key == "sk-test"

    def test_embedding_model_stored(self):
        rf = RelevanceFilter(topics=["momentum"], threshold=0.65, embedding_model="openai/text-embedding-3-small")
        assert rf._embedding_model == "openai/text-embedding-3-small"


class TestKeywordFilterRejectsIrrelevant:

    @patch("lib.filter.embed_text")
    def test_irrelevant_abstract_returns_zero(self, mock_embed):
        rf = RelevanceFilter(
            topics=["momentum", "factor model", "volatility"],
            threshold=0.65,
        )
        score, hits = rf.score(
            "This paper studies protein folding mechanisms in ribosomes "
            "using cryo-electron microscopy techniques."
        )
        assert score == 0.0
        assert hits == []
        mock_embed.assert_not_called()


class TestKeywordFilterPassesRelevant:

    @patch("lib.filter.embed_text")
    @patch.object(RelevanceFilter, "_get_seed_embeddings", return_value=[])
    def test_relevant_abstract_returns_hits(self, mock_seeds, mock_embed):
        mock_embed.return_value = [0.1] * 1536
        rf = RelevanceFilter(
            topics=["momentum", "factor model", "volatility"],
            threshold=0.65,
            api_key="sk-test",
            embedding_model="openai/text-embedding-3-small",
        )
        score, hits = rf.score(
            "We propose a novel momentum factor model for equity returns "
            "that incorporates cross-sectional momentum signals."
        )
        assert "momentum" in hits
        assert "factor model" in hits
        assert score > 0

    @patch("lib.filter.embed_text")
    @patch.object(RelevanceFilter, "_get_seed_embeddings", return_value=[])
    def test_single_keyword_hit(self, mock_seeds, mock_embed):
        mock_embed.return_value = [0.1] * 1536
        rf = RelevanceFilter(
            topics=["momentum", "factor model"],
            threshold=0.65,
            api_key="sk-test",
            embedding_model="openai/text-embedding-3-small",
        )
        score, hits = rf.score(
            "This paper examines momentum effects in stock markets."
        )
        assert hits == ["momentum"]
        assert score > 0


class TestKeywordFilterCaseInsensitive:

    @patch("lib.filter.embed_text")
    @patch.object(RelevanceFilter, "_get_seed_embeddings", return_value=[])
    def test_uppercase_abstract_matches(self, mock_seeds, mock_embed):
        mock_embed.return_value = [0.1] * 1536
        rf = RelevanceFilter(topics=["momentum"], threshold=0.65,
                             api_key="sk-test", embedding_model="m")
        score, hits = rf.score("MOMENTUM strategies in equity markets.")
        assert "momentum" in hits
        assert score > 0

    @patch("lib.filter.embed_text")
    @patch.object(RelevanceFilter, "_get_seed_embeddings", return_value=[])
    def test_mixed_case_abstract_matches(self, mock_seeds, mock_embed):
        mock_embed.return_value = [0.1] * 1536
        rf = RelevanceFilter(topics=["factor model"], threshold=0.65,
                             api_key="sk-test", embedding_model="m")
        score, hits = rf.score("A new Factor Model for risk analysis.")
        assert "factor model" in hits


class TestFallbackScoring:

    def test_one_hit_fallback_score_no_api_key(self):
        rf = RelevanceFilter(topics=["momentum"], threshold=0.65)
        score, hits = rf.score("This paper uses momentum signals.")
        assert score == pytest.approx(0.55)

    def test_two_hits_fallback_score_no_api_key(self):
        rf = RelevanceFilter(
            topics=["momentum", "volatility"],
            threshold=0.65,
        )
        score, hits = rf.score("Momentum and volatility in equity returns.")
        assert score == pytest.approx(0.6)

    def test_fallback_capped_at_0_9_no_api_key(self):
        topics = [f"topic{i}" for i in range(20)]
        rf = RelevanceFilter(topics=topics, threshold=0.65)
        # Build abstract with all topics
        abstract = " ".join(topics)
        score, hits = rf.score(abstract)
        assert score == pytest.approx(0.9)
        assert score <= 0.9

    @patch("lib.filter.embed_text")
    @patch.object(RelevanceFilter, "_get_seed_embeddings", return_value=[])
    def test_one_hit_fallback_with_empty_seeds(self, mock_seeds, mock_embed):
        mock_embed.return_value = [0.1] * 1536
        rf = RelevanceFilter(topics=["momentum"], threshold=0.65,
                             api_key="sk-test", embedding_model="m")
        score, hits = rf.score("This paper uses momentum signals.")
        assert score == pytest.approx(0.55)

    @patch("lib.filter.embed_text")
    @patch.object(RelevanceFilter, "_get_seed_embeddings", return_value=[])
    def test_two_hits_fallback_with_empty_seeds(self, mock_seeds, mock_embed):
        mock_embed.return_value = [0.1] * 1536
        rf = RelevanceFilter(
            topics=["momentum", "volatility"],
            threshold=0.65,
            api_key="sk-test",
            embedding_model="m",
        )
        score, hits = rf.score("Momentum and volatility in equity returns.")
        assert score == pytest.approx(0.6)

    @patch("lib.filter.embed_text")
    @patch.object(RelevanceFilter, "_get_seed_embeddings", return_value=[])
    def test_fallback_capped_at_0_9_with_empty_seeds(self, mock_seeds, mock_embed):
        mock_embed.return_value = [0.1] * 1536
        topics = [f"topic{i}" for i in range(20)]
        rf = RelevanceFilter(topics=topics, threshold=0.65,
                             api_key="sk-test", embedding_model="m")
        # Build abstract with all topics
        abstract = " ".join(topics)
        score, hits = rf.score(abstract)
        assert score == pytest.approx(0.9)
        assert score <= 0.9


class TestEmbeddingSimilarityScoring:

    @patch("lib.filter.cosine_similarity")
    @patch("lib.filter.embed_text")
    @patch.object(RelevanceFilter, "_get_seed_embeddings")
    def test_returns_max_similarity(self, mock_seeds, mock_embed, mock_cosine):
        mock_seeds.return_value = [[0.1] * 1536, [0.2] * 1536, [0.3] * 1536]
        mock_embed.return_value = [0.5] * 1536
        mock_cosine.side_effect = [0.6, 0.85, 0.7]
        rf = RelevanceFilter(topics=["momentum"], threshold=0.65,
                             api_key="sk-test", embedding_model="m")
        score, hits = rf.score("This paper uses momentum signals.")
        assert score == 0.85
        assert hits == ["momentum"]

    @patch("lib.filter.cosine_similarity")
    @patch("lib.filter.embed_text")
    @patch.object(RelevanceFilter, "_get_seed_embeddings")
    def test_calls_embed_text_with_abstract(self, mock_seeds, mock_embed, mock_cosine):
        mock_seeds.return_value = [[0.1] * 1536]
        mock_embed.return_value = [0.5] * 1536
        mock_cosine.return_value = 0.8
        rf = RelevanceFilter(topics=["momentum"], threshold=0.65,
                             api_key="sk-test", embedding_model="m")
        abstract = "Momentum effects in markets."
        rf.score(abstract)
        mock_embed.assert_called_once_with(abstract, model="m", api_key="sk-test")

    @patch("lib.filter.cosine_similarity")
    @patch("lib.filter.embed_text")
    @patch.object(RelevanceFilter, "_get_seed_embeddings")
    def test_compares_against_each_seed(self, mock_seeds, mock_embed, mock_cosine):
        seeds = [[0.1] * 1536, [0.2] * 1536]
        mock_seeds.return_value = seeds
        mock_embed.return_value = [0.5] * 1536
        mock_cosine.return_value = 0.7
        rf = RelevanceFilter(topics=["momentum"], threshold=0.65,
                             api_key="sk-test", embedding_model="m")
        rf.score("Momentum paper abstract.")
        assert mock_cosine.call_count == 2


class TestGetSeedEmbeddings:

    def test_returns_empty_list_without_database_url(self):
        rf = RelevanceFilter(topics=["momentum"], threshold=0.65)
        result = rf._get_seed_embeddings()
        assert result == []

    @patch("lib.filter.get_connection")
    def test_queries_seed_corpus_table(self, mock_get_conn):
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            {"embedding": [0.1] * 1536},
            {"embedding": [0.2] * 1536},
        ]
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_get_conn.return_value = mock_conn

        rf = RelevanceFilter(topics=["momentum"], threshold=0.65, database_url="postgresql://localhost/test")
        result = rf._get_seed_embeddings()

        mock_cursor.execute.assert_called_once_with("SELECT embedding FROM seed_corpus")
        assert len(result) == 2

    @patch("lib.filter.get_connection")
    def test_caches_seed_embeddings(self, mock_get_conn):
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [{"embedding": [0.1] * 1536}]
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_get_conn.return_value = mock_conn

        rf = RelevanceFilter(topics=["momentum"], threshold=0.65, database_url="postgresql://localhost/test")
        rf._get_seed_embeddings()
        rf._get_seed_embeddings()

        # Should only connect once due to caching
        mock_get_conn.assert_called_once()

    @patch("lib.filter.get_connection")
    def test_closes_connection(self, mock_get_conn):
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_get_conn.return_value = mock_conn

        rf = RelevanceFilter(topics=["momentum"], threshold=0.65, database_url="postgresql://localhost/test")
        rf._get_seed_embeddings()

        mock_conn.close.assert_called_once()

    @patch("lib.filter.get_connection")
    def test_filters_none_embeddings(self, mock_get_conn):
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            {"embedding": [0.1] * 1536},
            {"embedding": None},
            {"embedding": [0.3] * 1536},
        ]
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_get_conn.return_value = mock_conn

        rf = RelevanceFilter(topics=["momentum"], threshold=0.65, database_url="postgresql://localhost/test")
        result = rf._get_seed_embeddings()

        assert len(result) == 2

    @patch("lib.filter.get_connection")
    def test_parses_string_vector_from_db(self, mock_get_conn):
        # psycopg2 without a pgvector adapter returns vector columns as raw
        # strings ("[0.1,0.2,...]"). Verify they are correctly parsed to floats.
        vec = [0.1] * 4
        string_repr = "[" + ",".join(str(x) for x in vec) + "]"
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [{"embedding": string_repr}]
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_get_conn.return_value = mock_conn

        rf = RelevanceFilter(topics=["momentum"], threshold=0.65, database_url="postgresql://localhost/test")
        result = rf._get_seed_embeddings()

        assert result == [pytest.approx(vec)]
        assert all(isinstance(x, float) for x in result[0])


class TestParseVector:

    def test_parses_string_format(self):
        assert _parse_vector("[0.1,0.2,0.3]") == pytest.approx([0.1, 0.2, 0.3])

    def test_parses_list_passthrough(self):
        v = [0.1, 0.2, 0.3]
        assert _parse_vector(v) == pytest.approx(v)

    def test_string_length_matches_dimension(self):
        vec = [0.5] * 1536
        s = "[" + ",".join(str(x) for x in vec) + "]"
        result = _parse_vector(s)
        assert len(result) == 1536

    def test_string_values_are_floats(self):
        result = _parse_vector("[1.0,2.0,3.0]")
        assert all(isinstance(x, float) for x in result)
