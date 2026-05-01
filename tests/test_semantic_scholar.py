from unittest.mock import patch, MagicMock

import pytest

from lib.semantic_scholar import _arxiv_id_to_ss_id, fetch_citation_counts


class TestArxivIdToSsId:

    def test_strips_version_suffix(self):
        assert _arxiv_id_to_ss_id("2406.12345v1") == "ArXiv:2406.12345"

    def test_strips_higher_version(self):
        assert _arxiv_id_to_ss_id("2406.12345v3") == "ArXiv:2406.12345"

    def test_no_version_suffix(self):
        assert _arxiv_id_to_ss_id("2406.12345") == "ArXiv:2406.12345"

    def test_old_format_with_underscores(self):
        # Old arXiv IDs stored as hep-ph_9905221 → ArXiv:hep-ph/9905221
        assert _arxiv_id_to_ss_id("hep-ph_9905221") == "ArXiv:hep-ph/9905221"

    def test_old_format_with_version(self):
        assert _arxiv_id_to_ss_id("hep-ph_9905221v2") == "ArXiv:hep-ph/9905221"


class TestFetchCitationCounts:

    def test_empty_list_returns_empty_dict(self):
        result = fetch_citation_counts([])
        assert result == {}

    @patch("lib.semantic_scholar.httpx.post")
    def test_returns_correct_mapping(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [
            {"citationCount": 42},
            {"citationCount": 7},
        ]
        mock_post.return_value = mock_resp

        result = fetch_citation_counts(["2406.00001v1", "2406.00002v1"])

        assert result == {"2406.00001v1": 42, "2406.00002v1": 7}

    @patch("lib.semantic_scholar.httpx.post")
    def test_skips_null_entries(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [
            None,
            {"citationCount": 10},
        ]
        mock_post.return_value = mock_resp

        result = fetch_citation_counts(["2406.00001v1", "2406.00002v1"])

        assert result == {"2406.00002v1": 10}
        assert "2406.00001v1" not in result

    @patch("lib.semantic_scholar.httpx.post")
    def test_skips_entries_without_citation_count(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [{"paperId": "abc"}]
        mock_post.return_value = mock_resp

        result = fetch_citation_counts(["2406.00001v1"])

        assert result == {}

    @patch("lib.semantic_scholar.httpx.post")
    def test_returns_empty_on_429(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 429
        mock_post.return_value = mock_resp

        result = fetch_citation_counts(["2406.00001v1"])

        assert result == {}

    @patch("lib.semantic_scholar.httpx.post")
    def test_returns_empty_on_http_error(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_post.return_value = mock_resp

        result = fetch_citation_counts(["2406.00001v1"])

        assert result == {}

    @patch("lib.semantic_scholar.httpx.post")
    def test_returns_empty_on_network_exception(self, mock_post):
        mock_post.side_effect = Exception("connection refused")

        result = fetch_citation_counts(["2406.00001v1"])

        assert result == {}

    @patch("lib.semantic_scholar.httpx.post")
    def test_includes_api_key_header_when_provided(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [{"citationCount": 5}]
        mock_post.return_value = mock_resp

        fetch_citation_counts(["2406.00001v1"], api_key="mykey")

        _, kwargs = mock_post.call_args
        assert kwargs["headers"].get("x-api-key") == "mykey"

    @patch("lib.semantic_scholar.httpx.post")
    def test_omits_api_key_header_when_not_provided(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [{"citationCount": 5}]
        mock_post.return_value = mock_resp

        fetch_citation_counts(["2406.00001v1"])

        _, kwargs = mock_post.call_args
        assert "x-api-key" not in kwargs["headers"]

    @patch("lib.semantic_scholar.httpx.post")
    def test_sends_correct_ss_ids(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [{"citationCount": 0}]
        mock_post.return_value = mock_resp

        fetch_citation_counts(["2406.12345v2"])

        _, kwargs = mock_post.call_args
        assert kwargs["json"] == {"ids": ["ArXiv:2406.12345"]}
