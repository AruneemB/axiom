import sys
from unittest.mock import patch, MagicMock

import pytest

# Mock psycopg2 before importing api.spark
sys.modules.setdefault("psycopg2", MagicMock())
sys.modules.setdefault("psycopg2.extras", MagicMock())

from api.spark import run_spark, _find_paper_for_spark, _store_spark_idea  # noqa: E402


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
        "fallback_model": "m-fallback",
        "deepdive_model": "m2",
        "deepdive_day": 4,
        "cron_secret": "cron",
        "arxiv_categories": ["q-fin.ST"],
        "arxiv_max_results": 50,
        "allowed_topics": ["momentum"],
        "relevance_threshold": 0.65,
        "quality_gate_min": 11,
        "citation_weight": 0.02,
        "embedding_model": "openai/text-embedding-3-small",
    }
    defaults.update(overrides)
    cfg = MagicMock()
    for k, v in defaults.items():
        setattr(cfg, k, v)
    return cfg


def _mock_conn_with_cursor():
    mock_cursor = MagicMock()
    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    return mock_conn, mock_cursor


# ---------------------------------------------------------------------------
# run_spark
# ---------------------------------------------------------------------------

class TestRunSpark:

    @patch("api.spark.send_message")
    @patch("api.spark._find_paper_for_spark")
    def test_no_papers_sends_message(self, mock_find, mock_send):
        mock_find.return_value = (None, {})
        mock_conn, _ = _mock_conn_with_cursor()
        cfg = _make_config()

        result = run_spark(123, 456, mock_conn, cfg)

        assert result["ok"] is False
        assert result["reason"] == "no_papers"
        mock_send.assert_called_once()
        assert "No papers" in mock_send.call_args[0][1]

    @patch("api.spark.send_message")
    @patch("api.spark.synthesize_idea")
    @patch("api.spark._find_paper_for_spark")
    def test_llm_failure_sends_error(self, mock_find, mock_synth, mock_send):
        mock_find.return_value = ({"id": "2305_12345", "title": "T", "abstract": "A",
                                   "url": "https://arxiv.org/abs/2305.12345"}, {})
        mock_synth.return_value = (None, "test debug")
        mock_conn, _ = _mock_conn_with_cursor()
        cfg = _make_config()

        result = run_spark(123, 456, mock_conn, cfg)

        assert result["ok"] is False
        assert result["reason"] == "llm_failure"
        assert "I couldn't generate" in mock_send.call_args[0][1]

    @patch("api.spark.send_message")
    @patch("api.spark.synthesize_idea")
    @patch("api.spark._find_paper_for_spark")
    def test_below_quality_gate_sends_error(self, mock_find, mock_synth, mock_send):
        mock_find.return_value = ({"id": "2305_12345", "title": "T", "abstract": "A",
                                   "url": "https://arxiv.org/abs/2305.12345"}, {})
        mock_synth.return_value = ({
            "hypothesis": "H", "method": "M", "dataset": "D",
            "novelty_score": 3, "feasibility_score": 3,
        }, "")
        mock_conn, _ = _mock_conn_with_cursor()
        cfg = _make_config()

        result = run_spark(123, 456, mock_conn, cfg)

        assert result["ok"] is False
        assert result["reason"] == "below_quality_gate"

    @patch("api.spark.send_idea_message")
    @patch("api.spark._store_spark_idea")
    @patch("api.spark.embed_text")
    @patch("api.spark.synthesize_idea")
    @patch("api.spark._find_paper_for_spark")
    def test_success_stores_and_sends_idea(self, mock_find, mock_synth, mock_embed,
                                            mock_store, mock_send_idea):
        mock_find.return_value = ({"id": "2305_12345", "title": "Test Paper", "abstract": "A",
                                   "url": "https://arxiv.org/abs/2305.12345"}, {})
        mock_synth.return_value = ({
            "hypothesis": "H1", "method": "M1", "dataset": "D1",
            "novelty_score": 7, "feasibility_score": 6,
        }, "")
        mock_embed.return_value = [0.1] * 256
        mock_store.return_value = 42
        mock_conn, mock_cursor = _mock_conn_with_cursor()
        cfg = _make_config()

        result = run_spark(123, 456, mock_conn, cfg)

        assert result["ok"] is True
        assert result["idea_id"] == 42
        mock_store.assert_called_once()
        mock_send_idea.assert_called_once()

        # Verify paper is marked as processed for diversity
        update_calls = [
            c for c in mock_cursor.execute.call_args_list
            if "UPDATE papers SET processed" in str(c)
        ]
        assert len(update_calls) == 1

    @patch("api.spark.send_message")
    @patch("api.spark.send_idea_message", side_effect=Exception("telegram down"))
    @patch("api.spark._store_spark_idea")
    @patch("api.spark.embed_text")
    @patch("api.spark.synthesize_idea")
    @patch("api.spark._find_paper_for_spark")
    def test_telegram_send_failure_rolls_back(self, mock_find, mock_synth, mock_embed,
                                               mock_store, mock_send_idea, mock_send_msg):
        mock_find.return_value = ({"id": "2305_12345", "title": "Test Paper", "abstract": "A",
                                   "url": "https://arxiv.org/abs/2305.12345"}, {})
        mock_synth.return_value = ({
            "hypothesis": "H1", "method": "M1", "dataset": "D1",
            "novelty_score": 7, "feasibility_score": 6,
        }, "")
        mock_embed.return_value = [0.1] * 256
        mock_store.return_value = 55
        mock_conn, mock_cursor = _mock_conn_with_cursor()
        cfg = _make_config()

        result = run_spark(123, 456, mock_conn, cfg)

        assert result["ok"] is False
        assert result["reason"] == "telegram_send_failed"
        # Idea is deleted and paper is NOT marked processed
        delete_calls = [c for c in mock_cursor.execute.call_args_list
                        if "DELETE FROM ideas" in str(c)]
        assert len(delete_calls) == 1
        update_calls = [c for c in mock_cursor.execute.call_args_list
                        if "UPDATE papers SET processed" in str(c)]
        assert len(update_calls) == 0


# ---------------------------------------------------------------------------
# _find_paper_for_spark tiers
# ---------------------------------------------------------------------------

class TestFindPaperForSpark:

    def test_tier1_returns_unprocessed_paper(self):
        mock_conn, mock_cursor = _mock_conn_with_cursor()
        paper_row = {"id": "2305_11111", "title": "T", "abstract": "A", "url": "u"}
        mock_cursor.fetchone.return_value = paper_row
        cfg = _make_config()

        paper, tiers = _find_paper_for_spark(mock_conn, cfg)

        assert paper == paper_row

    @patch("api.spark.fetch_recent_papers")
    def test_tier2_excludes_papers_already_in_db(self, mock_fetch):
        """Tier 2 skips arXiv papers that are already in the database."""
        mock_cursor = MagicMock()
        # Tier 1: no unprocessed paper
        mock_cursor.fetchone.return_value = None
        # DB lookup for existing papers: all arXiv papers already exist
        mock_cursor.fetchall.side_effect = [
            [{"id": "2305_aaaa"}],  # existing IDs query
            [],                      # Tier 3: no archived papers
        ]
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        arxiv_paper = MagicMock()
        arxiv_paper.id = "2305_aaaa"
        arxiv_paper.abstract = "momentum strategy"
        mock_fetch.return_value = [arxiv_paper]
        cfg = _make_config()

        paper, tiers = _find_paper_for_spark(mock_conn, cfg)

        # Paper was in DB so Tier 2 skipped it, Tier 3 also empty → None
        assert paper is None

    @patch("api.spark.fetch_recent_papers")
    def test_tier3_returns_random_archived_paper(self, mock_fetch):
        """When tier 1 and tier 2 miss, returns a random archived paper."""
        mock_cursor = MagicMock()
        # Tier 1: no unprocessed paper
        mock_cursor.fetchone.return_value = None
        # Tier 3: top papers
        mock_cursor.fetchall.return_value = [
            {"id": "2305_99999", "title": "T", "abstract": "momentum strategy paper", "url": "u"},
        ]
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        # Tier 2: no arxiv papers
        mock_fetch.return_value = []
        cfg = _make_config()

        paper, tiers = _find_paper_for_spark(mock_conn, cfg)

        assert paper["id"] == "2305_99999"

    @patch("api.spark.fetch_recent_papers")
    def test_tier4_returns_none(self, mock_fetch):
        """When all tiers miss, returns None."""
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = None
        mock_cursor.fetchall.return_value = []
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_fetch.return_value = []
        cfg = _make_config()

        paper, tiers = _find_paper_for_spark(mock_conn, cfg)

        assert paper is None
