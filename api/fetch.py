import json
from http.server import BaseHTTPRequestHandler

from lib.config import load_config
from lib.arxiv import fetch_recent_papers
from lib.rss import fetch_rss_papers
from lib.filter import RelevanceFilter
from lib.db import get_connection


class handler(BaseHTTPRequestHandler):

    def do_GET(self):
        cfg = load_config()

        # Verify cron secret
        from urllib.parse import urlparse, parse_qs
        params = parse_qs(urlparse(self.path).query)
        if params.get("key", [None])[0] != cfg.cron_secret:
            self._respond(401, {"error": "unauthorized"})
            return

        try:
            result = run_fetch(cfg)
            self._respond(200, result)
        except Exception as e:
            self._respond(500, {"error": str(e)})

    def _respond(self, status: int, body: dict):
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(payload))
        self.end_headers()
        self.wfile.write(payload)


def run_fetch(cfg) -> dict:
    papers = []

    # Fetch from arXiv
    arxiv_papers = fetch_recent_papers(
        categories=cfg.arxiv_categories,
        max_results=cfg.arxiv_max_results,
    )
    papers.extend(arxiv_papers)

    # TODO: uncomment when lib/rss.py is implemented (Prompt 13)
    # rss_papers = fetch_rss_papers(urls=RSS_FEED_URLS)
    # papers.extend(rss_papers)

    if not papers:
        return {"fetched": 0, "stored": 0, "skipped": 0}

    relevance_filter = RelevanceFilter(
        topics=cfg.allowed_topics,
        threshold=cfg.relevance_threshold,
        database_url=cfg.database_url,
        api_key=cfg.openrouter_api_key,
        embedding_model=cfg.embedding_model,
    )

    stored, skipped = 0, 0
    conn = get_connection(cfg.database_url)

    with conn.cursor() as cur:
        for paper in papers:
            # Skip if already in DB
            cur.execute("SELECT 1 FROM papers WHERE id = %s", (paper.id,))
            if cur.fetchone():
                skipped += 1
                continue

            score, keyword_hits = relevance_filter.score(paper.abstract)

            if score < cfg.relevance_threshold:
                cur.execute(
                    """INSERT INTO papers (id, title, abstract, authors, categories,
                       url, published_at, relevance_score, keyword_hits, skipped, skip_reason)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,TRUE,%s)""",
                    (paper.id, paper.title, paper.abstract, paper.authors,
                     paper.categories, paper.url, paper.published_at,
                     score, keyword_hits, "below_relevance_threshold"),
                )
                skipped += 1
            else:
                cur.execute(
                    """INSERT INTO papers (id, title, abstract, authors, categories,
                       url, published_at, relevance_score, keyword_hits)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (paper.id, paper.title, paper.abstract, paper.authors,
                     paper.categories, paper.url, paper.published_at,
                     score, keyword_hits),
                )
                stored += 1

        conn.commit()

    conn.close()
    return {"fetched": len(papers), "stored": stored, "skipped": skipped}
