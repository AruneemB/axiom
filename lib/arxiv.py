import httpx
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from xml.etree import ElementTree as ET

ARXIV_API = "https://export.arxiv.org/api/query"


@dataclass
class ArxivPaper:
    id: str
    title: str
    abstract: str
    authors: list[str]
    categories: list[str]
    url: str
    published_at: datetime


def fetch_recent_papers(categories: list[str], max_results: int = 50, hours: int = 36) -> list[ArxivPaper]:
    query = " OR ".join(f"cat:{c}" for c in categories)

    params = {
        "search_query": query,
        "start": 0,
        "max_results": max_results,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    }

    try:
        resp = httpx.get(ARXIV_API, params=params, timeout=20)
        resp.raise_for_status()
    except (httpx.TimeoutException, httpx.HTTPStatusError, httpx.ConnectError) as e:
        print(f"[arxiv] fetch failed: {e}")
        return []

    ns = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
    try:
        root = ET.fromstring(resp.text)
    except ET.ParseError as e:
        print(f"[arxiv] XML parse failed: {e}")
        return []
    papers = []

    for entry in root.findall("atom:entry", ns):
        try:
            raw_id = entry.find("atom:id", ns).text.strip()
            arxiv_id = raw_id.split("/abs/")[-1].replace("/", "_")

            published_str = entry.find("atom:published", ns).text.strip()
            published_at = datetime.fromisoformat(published_str.replace("Z", "+00:00"))

            if published_at < datetime.now(timezone.utc) - timedelta(hours=hours):
                continue

            title = entry.find("atom:title", ns).text.strip().replace("\n", " ")
            abstract = entry.find("atom:summary", ns).text.strip().replace("\n", " ")
            authors = [
                a.find("atom:name", ns).text
                for a in entry.findall("atom:author", ns)
            ]
            categories_list = [t.attrib.get("term", "") for t in entry.findall("atom:category", ns)]
            url = f"https://arxiv.org/abs/{arxiv_id.replace('_', '/')}"

            papers.append(ArxivPaper(
                id=arxiv_id,
                title=title,
                abstract=abstract,
                authors=authors,
                categories=categories_list,
                url=url,
                published_at=published_at,
            ))
        except (AttributeError, ValueError) as e:
            print(f"[arxiv] skipping malformed entry: {e}")
            continue

    return papers
