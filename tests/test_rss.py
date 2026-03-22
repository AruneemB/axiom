import sys
from unittest.mock import MagicMock

# Mock feedparser since it may not be installed locally
sys.modules.setdefault("feedparser", MagicMock())

from lib.rss import fetch_rss_papers  # noqa: E402


class TestFetchRssPapers:

    def test_returns_empty_list(self):
        result = fetch_rss_papers(["https://example.com/rss"])
        assert result == []

    def test_accepts_multiple_urls(self):
        result = fetch_rss_papers([
            "https://example.com/rss1",
            "https://example.com/rss2",
        ])
        assert result == []

    def test_accepts_empty_list(self):
        result = fetch_rss_papers([])
        assert result == []

    def test_returns_list_type(self):
        result = fetch_rss_papers(["https://example.com/rss"])
        assert isinstance(result, list)
