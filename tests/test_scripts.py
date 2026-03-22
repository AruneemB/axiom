import sys
from unittest.mock import patch, MagicMock
from xml.etree import ElementTree as ET

import pytest

# Mock psycopg2 and feedparser
sys.modules.setdefault("psycopg2", MagicMock())
sys.modules.setdefault("psycopg2.extras", MagicMock())
sys.modules.setdefault("feedparser", MagicMock())

from scripts.register_webhook import main as register_main  # noqa: E402
from scripts.seed_corpus import main as seed_main  # noqa: E402
from scripts.backfill_embeddings import main as backfill_main  # noqa: E402


# ---------------------------------------------------------------------------
# register_webhook.py
# ---------------------------------------------------------------------------

class TestRegisterWebhook:

    @patch("scripts.register_webhook.register_webhook")
    @patch("sys.argv", ["register_webhook.py",
                         "--bot-token", "tok",
                         "--webhook-url", "https://example.com/api/telegram",
                         "--secret", "my-secret"])
    def test_calls_register_webhook(self, mock_reg):
        mock_reg.return_value = {"ok": True}
        register_main()
        mock_reg.assert_called_once_with(
            bot_token="tok",
            webhook_url="https://example.com/api/telegram",
            secret="my-secret",
        )

    @patch("scripts.register_webhook.register_webhook")
    def test_missing_args_raises(self, mock_reg):
        with patch("sys.argv", ["register_webhook.py"]):
            with pytest.raises(SystemExit):
                register_main()


# ---------------------------------------------------------------------------
# seed_corpus.py
# ---------------------------------------------------------------------------

class TestSeedCorpus:

    @patch("scripts.seed_corpus.get_connection")
    @patch("scripts.seed_corpus.embed_text", return_value=[0.1] * 1536)
    @patch("scripts.seed_corpus.httpx")
    @patch("sys.argv", ["seed_corpus.py",
                         "--papers", "2401.12345,2401.67890",
                         "--database-url", "postgresql://localhost/test",
                         "--openrouter-api-key", "sk-test"])
    def test_fetches_and_inserts_papers(self, mock_httpx, mock_embed, mock_conn):
        # Build a minimal Atom XML response
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <feed xmlns="http://www.w3.org/2005/Atom">
          <entry>
            <title>Test Paper Title</title>
            <summary>Test abstract about momentum factors.</summary>
          </entry>
        </feed>"""
        mock_response = MagicMock()
        mock_response.text = xml
        mock_httpx.get.return_value = mock_response

        mock_cursor = MagicMock()
        mock_conn_obj = MagicMock()
        mock_conn_obj.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn_obj.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.return_value = mock_conn_obj

        seed_main()

        # Should have fetched both papers
        assert mock_httpx.get.call_count == 2
        # Should have called embed_text for each paper
        assert mock_embed.call_count == 2
        # Should have inserted into seed_corpus for each paper
        insert_calls = [c for c in mock_cursor.execute.call_args_list
                        if "INSERT INTO seed_corpus" in str(c)]
        assert len(insert_calls) == 2

    @patch("scripts.seed_corpus.get_connection")
    @patch("scripts.seed_corpus.embed_text")
    @patch("scripts.seed_corpus.httpx")
    @patch("sys.argv", ["seed_corpus.py",
                         "--papers", "9999.99999",
                         "--database-url", "postgresql://localhost/test",
                         "--openrouter-api-key", "sk-test"])
    def test_skips_paper_not_found(self, mock_httpx, mock_embed, mock_conn):
        # XML with no entry
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <feed xmlns="http://www.w3.org/2005/Atom">
        </feed>"""
        mock_response = MagicMock()
        mock_response.text = xml
        mock_httpx.get.return_value = mock_response
        mock_conn.return_value = MagicMock()

        seed_main()
        mock_embed.assert_not_called()


# ---------------------------------------------------------------------------
# backfill_embeddings.py
# ---------------------------------------------------------------------------

class TestBackfillEmbeddings:

    @patch("scripts.backfill_embeddings.get_connection")
    @patch("scripts.backfill_embeddings.embed_text", return_value=[0.1] * 1536)
    @patch("sys.argv", ["backfill_embeddings.py",
                         "--database-url", "postgresql://localhost/test",
                         "--openrouter-api-key", "sk-test"])
    def test_updates_papers_with_null_embeddings(self, mock_embed, mock_conn):
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            {"id": "p1", "abstract": "Abstract 1"},
            {"id": "p2", "abstract": "Abstract 2"},
        ]
        mock_conn_obj = MagicMock()
        mock_conn_obj.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn_obj.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.return_value = mock_conn_obj

        backfill_main()

        assert mock_embed.call_count == 2
        update_calls = [c for c in mock_cursor.execute.call_args_list
                        if "UPDATE papers" in str(c)]
        assert len(update_calls) == 2
        mock_conn_obj.close.assert_called_once()

    @patch("scripts.backfill_embeddings.get_connection")
    @patch("scripts.backfill_embeddings.embed_text")
    @patch("sys.argv", ["backfill_embeddings.py",
                         "--database-url", "postgresql://localhost/test",
                         "--openrouter-api-key", "sk-test"])
    def test_no_papers_to_backfill(self, mock_embed, mock_conn):
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_conn_obj = MagicMock()
        mock_conn_obj.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn_obj.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.return_value = mock_conn_obj

        backfill_main()

        mock_embed.assert_not_called()
        mock_conn_obj.close.assert_called_once()
