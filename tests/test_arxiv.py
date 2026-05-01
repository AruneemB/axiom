from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

import httpx
import pytest

from lib.arxiv import ArxivPaper, ARXIV_API, fetch_recent_papers


class TestArxivApiConstant:

    def test_api_url_value(self):
        assert ARXIV_API == "https://export.arxiv.org/api/query"


class TestArxivPaperDataclass:

    def _make_paper(self, **overrides):
        defaults = {
            "id": "2305_12345",
            "title": "Test Paper Title",
            "abstract": "Test abstract content.",
            "authors": ["Alice", "Bob"],
            "categories": ["q-fin.ST", "cs.CE"],
            "url": "https://arxiv.org/abs/2305.12345",
            "published_at": datetime(2025, 5, 1, 12, 0, 0, tzinfo=timezone.utc),
        }
        defaults.update(overrides)
        return ArxivPaper(**defaults)

    def test_instantiation(self):
        paper = self._make_paper()
        assert paper.id == "2305_12345"
        assert paper.title == "Test Paper Title"

    def test_authors_is_list_of_str(self):
        paper = self._make_paper()
        assert isinstance(paper.authors, list)
        assert all(isinstance(a, str) for a in paper.authors)

    def test_categories_is_list_of_str(self):
        paper = self._make_paper()
        assert isinstance(paper.categories, list)
        assert all(isinstance(c, str) for c in paper.categories)

    def test_published_at_is_datetime(self):
        paper = self._make_paper()
        assert isinstance(paper.published_at, datetime)

    def test_url_format(self):
        paper = self._make_paper()
        assert paper.url.startswith("https://arxiv.org/abs/")

    def test_fields_match_constructor_args(self):
        dt = datetime(2025, 3, 15, 8, 30, 0, tzinfo=timezone.utc)
        paper = self._make_paper(
            id="2503_99999",
            title="Custom Title",
            abstract="Custom abstract.",
            authors=["Charlie"],
            categories=["q-fin.PM"],
            url="https://arxiv.org/abs/2503.99999",
            published_at=dt,
        )
        assert paper.id == "2503_99999"
        assert paper.title == "Custom Title"
        assert paper.abstract == "Custom abstract."
        assert paper.authors == ["Charlie"]
        assert paper.categories == ["q-fin.PM"]
        assert paper.url == "https://arxiv.org/abs/2503.99999"
        assert paper.published_at == dt


def _make_atom_xml(entries_xml: str) -> str:
    """Build a minimal Atom XML feed wrapping the given entry elements."""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<feed xmlns="http://www.w3.org/2005/Atom" '
        'xmlns:arxiv="http://arxiv.org/schemas/atom">'
        f"{entries_xml}"
        "</feed>"
    )


def _make_entry_xml(
    arxiv_id: str = "2305.12345v1",
    title: str = "Test Title",
    summary: str = "Test abstract.",
    authors: list[str] | None = None,
    categories: list[str] | None = None,
    published: str | None = None,
) -> str:
    """Build a single Atom entry element."""
    if authors is None:
        authors = ["Alice"]
    if categories is None:
        categories = ["q-fin.ST"]
    if published is None:
        # Default to 1 hour ago so it passes the 36h filter
        dt = datetime.now(timezone.utc) - timedelta(hours=1)
        published = dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    author_xml = "".join(f"<author><name>{a}</name></author>" for a in authors)
    cat_xml = "".join(f'<category term="{c}"/>' for c in categories)

    return (
        "<entry>"
        f"<id>http://arxiv.org/abs/{arxiv_id}</id>"
        f"<title>{title}</title>"
        f"<summary>{summary}</summary>"
        f"{author_xml}"
        f"{cat_xml}"
        f"<published>{published}</published>"
        "</entry>"
    )


def _mock_response(xml_text: str) -> MagicMock:
    """Create a mock httpx.Response with the given text."""
    resp = MagicMock(spec=httpx.Response)
    resp.text = xml_text
    resp.raise_for_status = MagicMock()
    return resp


class TestFetchRecentPapersXmlParsing:

    @patch("lib.arxiv.httpx.get")
    def test_parses_single_entry(self, mock_get):
        entry = _make_entry_xml(
            arxiv_id="2305.12345v1",
            title="Momentum Factor Analysis",
            summary="We study momentum factors.",
            authors=["Alice", "Bob"],
            categories=["q-fin.ST", "cs.CE"],
        )
        mock_get.return_value = _mock_response(_make_atom_xml(entry))

        papers = fetch_recent_papers(["q-fin.ST"])

        assert len(papers) == 1
        assert papers[0].id == "2305.12345v1"
        assert papers[0].title == "Momentum Factor Analysis"
        assert papers[0].abstract == "We study momentum factors."
        assert papers[0].authors == ["Alice", "Bob"]
        assert papers[0].categories == ["q-fin.ST", "cs.CE"]

    @patch("lib.arxiv.httpx.get")
    def test_parses_multiple_entries(self, mock_get):
        entries = _make_entry_xml(arxiv_id="2305.11111v1") + _make_entry_xml(arxiv_id="2305.22222v1")
        mock_get.return_value = _mock_response(_make_atom_xml(entries))

        papers = fetch_recent_papers(["q-fin.ST"])
        assert len(papers) == 2

    @patch("lib.arxiv.httpx.get")
    def test_empty_feed_returns_empty_list(self, mock_get):
        mock_get.return_value = _mock_response(_make_atom_xml(""))

        papers = fetch_recent_papers(["q-fin.ST"])
        assert papers == []


class TestFetchRecentPapersFiltering:

    @patch("lib.arxiv.httpx.get")
    def test_filters_out_old_papers(self, mock_get):
        old_dt = (datetime.now(timezone.utc) - timedelta(hours=48)).strftime("%Y-%m-%dT%H:%M:%SZ")
        entry = _make_entry_xml(published=old_dt)
        mock_get.return_value = _mock_response(_make_atom_xml(entry))

        papers = fetch_recent_papers(["q-fin.ST"])
        assert len(papers) == 0

    @patch("lib.arxiv.httpx.get")
    def test_keeps_recent_papers(self, mock_get):
        recent_dt = (datetime.now(timezone.utc) - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
        entry = _make_entry_xml(published=recent_dt)
        mock_get.return_value = _mock_response(_make_atom_xml(entry))

        papers = fetch_recent_papers(["q-fin.ST"])
        assert len(papers) == 1

    @patch("lib.arxiv.httpx.get")
    def test_mixed_old_and_recent(self, mock_get):
        old_dt = (datetime.now(timezone.utc) - timedelta(hours=48)).strftime("%Y-%m-%dT%H:%M:%SZ")
        recent_dt = (datetime.now(timezone.utc) - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
        entries = _make_entry_xml(arxiv_id="2305.00001v1", published=old_dt) + \
                  _make_entry_xml(arxiv_id="2305.00002v1", published=recent_dt)
        mock_get.return_value = _mock_response(_make_atom_xml(entries))

        papers = fetch_recent_papers(["q-fin.ST"])
        assert len(papers) == 1
        assert papers[0].id == "2305.00002v1"


class TestFetchRecentPapersIdNormalization:

    @patch("lib.arxiv.httpx.get")
    def test_id_extracted_from_abs_url(self, mock_get):
        entry = _make_entry_xml(arxiv_id="2305.12345v1")
        mock_get.return_value = _mock_response(_make_atom_xml(entry))

        papers = fetch_recent_papers(["q-fin.ST"])
        assert papers[0].id == "2305.12345v1"

    @patch("lib.arxiv.httpx.get")
    def test_id_with_slash_replaced_by_underscore(self, mock_get):
        # Older arXiv IDs have a category prefix like hep-th/9901001
        entry = _make_entry_xml(arxiv_id="hep-th/9901001")
        mock_get.return_value = _mock_response(_make_atom_xml(entry))

        papers = fetch_recent_papers(["hep-th"])
        assert papers[0].id == "hep-th_9901001"

    @patch("lib.arxiv.httpx.get")
    def test_url_reconstructed_from_id(self, mock_get):
        entry = _make_entry_xml(arxiv_id="hep-th/9901001")
        mock_get.return_value = _mock_response(_make_atom_xml(entry))

        papers = fetch_recent_papers(["hep-th"])
        assert papers[0].url == "https://arxiv.org/abs/hep-th/9901001"


class TestFetchRecentPapersTextCleaning:

    @patch("lib.arxiv.httpx.get")
    def test_title_newlines_replaced_with_spaces(self, mock_get):
        entry = _make_entry_xml(title="Multi\nLine\nTitle")
        mock_get.return_value = _mock_response(_make_atom_xml(entry))

        papers = fetch_recent_papers(["q-fin.ST"])
        assert papers[0].title == "Multi Line Title"

    @patch("lib.arxiv.httpx.get")
    def test_abstract_newlines_replaced_with_spaces(self, mock_get):
        entry = _make_entry_xml(summary="Abstract with\nnewlines\nin it.")
        mock_get.return_value = _mock_response(_make_atom_xml(entry))

        papers = fetch_recent_papers(["q-fin.ST"])
        assert papers[0].abstract == "Abstract with newlines in it."

    @patch("lib.arxiv.httpx.get")
    def test_title_whitespace_stripped(self, mock_get):
        entry = _make_entry_xml(title="  Padded Title  ")
        mock_get.return_value = _mock_response(_make_atom_xml(entry))

        papers = fetch_recent_papers(["q-fin.ST"])
        assert papers[0].title == "Padded Title"


class TestFetchRecentPapersApiCall:

    @patch("lib.arxiv.httpx.get")
    def test_query_format_single_category(self, mock_get):
        mock_get.return_value = _mock_response(_make_atom_xml(""))

        fetch_recent_papers(["q-fin.ST"])

        call_kwargs = mock_get.call_args
        params = call_kwargs.kwargs.get("params") or call_kwargs[1].get("params")
        assert params["search_query"] == "cat:q-fin.ST"

    @patch("lib.arxiv.httpx.get")
    def test_query_format_multiple_categories(self, mock_get):
        mock_get.return_value = _mock_response(_make_atom_xml(""))

        fetch_recent_papers(["q-fin.ST", "q-fin.PM", "cs.CE"])

        call_kwargs = mock_get.call_args
        params = call_kwargs.kwargs.get("params") or call_kwargs[1].get("params")
        assert params["search_query"] == "cat:q-fin.ST OR cat:q-fin.PM OR cat:cs.CE"

    @patch("lib.arxiv.httpx.get")
    def test_max_results_passed_to_api(self, mock_get):
        mock_get.return_value = _mock_response(_make_atom_xml(""))

        fetch_recent_papers(["q-fin.ST"], max_results=25)

        call_kwargs = mock_get.call_args
        params = call_kwargs.kwargs.get("params") or call_kwargs[1].get("params")
        assert params["max_results"] == 25

    @patch("lib.arxiv.httpx.get")
    def test_sort_by_submitted_date_descending(self, mock_get):
        mock_get.return_value = _mock_response(_make_atom_xml(""))

        fetch_recent_papers(["q-fin.ST"])

        call_kwargs = mock_get.call_args
        params = call_kwargs.kwargs.get("params") or call_kwargs[1].get("params")
        assert params["sortBy"] == "submittedDate"
        assert params["sortOrder"] == "descending"

    @patch("lib.arxiv.httpx.get")
    def test_timeout_is_20_seconds(self, mock_get):
        mock_get.return_value = _mock_response(_make_atom_xml(""))

        fetch_recent_papers(["q-fin.ST"])

        call_kwargs = mock_get.call_args
        timeout = call_kwargs.kwargs.get("timeout") or call_kwargs[1].get("timeout")
        assert timeout == 20

    @patch("lib.arxiv.httpx.get")
    def test_calls_correct_api_url(self, mock_get):
        mock_get.return_value = _mock_response(_make_atom_xml(""))

        fetch_recent_papers(["q-fin.ST"])

        assert mock_get.call_args[0][0] == ARXIV_API

    @patch("lib.arxiv.httpx.get")
    def test_raise_for_status_called(self, mock_get):
        mock_get.return_value = _mock_response(_make_atom_xml(""))

        fetch_recent_papers(["q-fin.ST"])

        mock_get.return_value.raise_for_status.assert_called_once()

    @patch("lib.arxiv.httpx.get")
    def test_http_error_returns_empty_list(self, mock_get):
        mock_get.return_value.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Server Error", request=MagicMock(), response=MagicMock()
        )

        papers = fetch_recent_papers(["q-fin.ST"])
        assert papers == []


class TestFetchRecentPapersMalformedEntries:

    @patch("lib.arxiv.httpx.get")
    def test_malformed_entry_skipped_valid_entry_returned(self, mock_get):
        """A malformed entry missing <id> should be skipped; the valid entry after it is returned."""
        recent_dt = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        malformed = (
            "<entry>"
            "<title>Broken Entry</title>"
            "<summary>Abstract.</summary>"
            f"<published>{recent_dt}</published>"
            "</entry>"
        )
        valid = _make_entry_xml(arxiv_id="2305.99999v1", title="Good Paper")
        mock_get.return_value = _mock_response(_make_atom_xml(malformed + valid))

        papers = fetch_recent_papers(["q-fin.ST"])

        assert len(papers) == 1
        assert papers[0].id == "2305.99999v1"

    @patch("lib.arxiv.httpx.get")
    def test_all_malformed_entries_returns_empty(self, mock_get):
        """All malformed entries should be skipped, returning an empty list without raising."""
        recent_dt = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        malformed = (
            "<entry>"
            "<title>Broken Entry</title>"
            f"<published>{recent_dt}</published>"
            "</entry>"
        )
        mock_get.return_value = _mock_response(_make_atom_xml(malformed))

        papers = fetch_recent_papers(["q-fin.ST"])

        assert papers == []


class TestFetchRecentPapersHoursParameter:

    @patch("lib.arxiv.httpx.get")
    def test_hours_parameter_widens_time_window(self, mock_get):
        """A paper 48h old is excluded with default hours=36 but included with hours=168."""
        dt_48h_ago = (datetime.now(timezone.utc) - timedelta(hours=48)).strftime("%Y-%m-%dT%H:%M:%SZ")
        entry = _make_entry_xml(published=dt_48h_ago)
        mock_get.return_value = _mock_response(_make_atom_xml(entry))

        # Default (36h) should filter it out
        papers_default = fetch_recent_papers(["q-fin.ST"])
        assert len(papers_default) == 0

        # With hours=168 should include it
        papers_wide = fetch_recent_papers(["q-fin.ST"], hours=168)
        assert len(papers_wide) == 1

    @patch("lib.arxiv.httpx.get")
    def test_hours_parameter_still_filters_beyond_window(self, mock_get):
        """A paper older than the specified hours window is still filtered out."""
        dt_200h_ago = (datetime.now(timezone.utc) - timedelta(hours=200)).strftime("%Y-%m-%dT%H:%M:%SZ")
        entry = _make_entry_xml(published=dt_200h_ago)
        mock_get.return_value = _mock_response(_make_atom_xml(entry))

        papers = fetch_recent_papers(["q-fin.ST"], hours=168)
        assert len(papers) == 0
