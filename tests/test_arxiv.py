from datetime import datetime, timezone

from lib.arxiv import ArxivPaper, ARXIV_API


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
