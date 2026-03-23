import json
import random
from http.server import BaseHTTPRequestHandler

from lib.config import load_config
from lib.db import get_connection
from lib.openrouter import synthesize_idea
from lib.embeddings import embed_text
from lib.telegram_client import send_message, send_idea_message
from lib.arxiv import fetch_recent_papers
from lib.filter import RelevanceFilter


class handler(BaseHTTPRequestHandler):

    def do_POST(self):
        cfg = load_config()

        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length))

        if body.get("secret") != cfg.cron_secret:
            self._respond(401, {"error": "unauthorized"})
            return

        user_id = body["user_id"]
        chat_id = body["chat_id"]

        conn = get_connection(cfg.database_url)
        try:
            result = run_spark(user_id, chat_id, conn, cfg)
            self._respond(200, result)
        except Exception as e:
            send_message(chat_id, f"Something went wrong (model={cfg.default_model}): {e}", cfg.telegram_bot_token)
            self._respond(500, {"error": str(e)})
        finally:
            conn.close()

    def _respond(self, status: int, body: dict):
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(payload))
        self.end_headers()
        self.wfile.write(payload)


def run_spark(user_id: int, chat_id: int, conn, cfg) -> dict:
    paper = _find_paper_for_spark(conn, cfg)
    if not paper:
        send_message(chat_id, "No papers available right now. Try again later.", cfg.telegram_bot_token)
        return {"ok": False, "reason": "no_papers"}

    idea, debug = synthesize_idea(
        title=paper["title"],
        abstract=paper["abstract"],
        model=cfg.default_model,
        api_key=cfg.openrouter_api_key,
    )

    if idea is None:
        msg = f"Could not generate an idea. Debug: {debug}"
        send_message(chat_id, msg, cfg.telegram_bot_token)
        return {"ok": False, "reason": "llm_failure"}

    if idea["novelty_score"] + idea["feasibility_score"] < 10:
        send_message(chat_id, "The idea didn't pass the quality gate. Try again later.", cfg.telegram_bot_token)
        return {"ok": False, "reason": "below_quality_gate"}

    idea_embedding = embed_text(
        idea["hypothesis"] + " " + idea["method"],
        model=cfg.embedding_model,
        api_key=cfg.openrouter_api_key,
    )

    idea_id = _store_spark_idea(conn, paper["id"], idea, idea_embedding, user_id)

    send_idea_message(
        chat_id=chat_id,
        idea_id=idea_id,
        title=paper["title"],
        url=paper["url"],
        idea=idea,
        bot_token=cfg.telegram_bot_token,
    )

    return {"ok": True, "idea_id": idea_id}


def _find_paper_for_spark(conn, cfg) -> dict | None:
    # Tier 1: Unprocessed papers in DB
    with conn.cursor() as cur:
        cur.execute(
            """SELECT id, title, abstract, url
               FROM papers
               WHERE NOT processed AND NOT skipped
               ORDER BY relevance_score DESC
               LIMIT 1"""
        )
        paper = cur.fetchone()
    if paper:
        return paper

    # Tier 2: Expanded arXiv fetch (7-day window)
    arxiv_papers = fetch_recent_papers(
        categories=cfg.arxiv_categories,
        max_results=cfg.arxiv_max_results,
        hours=168,
    )
    if arxiv_papers:
        # Keyword-only scoring (no embedding API) to avoid dimension mismatches
        # with seed corpus and to keep Tier 2 fast
        relevance_filter = RelevanceFilter(
            topics=cfg.allowed_topics,
            threshold=cfg.relevance_threshold,
        )
        scored = []
        for p in arxiv_papers:
            score, keyword_hits = relevance_filter.score(p.abstract)
            if keyword_hits:  # Any keyword match — user explicitly asked for an idea
                scored.append((score, keyword_hits, p))
        if scored:
            scored.sort(key=lambda x: x[0], reverse=True)
            best_score, best_hits, best_paper = scored[0]
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM papers WHERE id = %s", (best_paper.id,))
                if not cur.fetchone():
                    cur.execute(
                        """INSERT INTO papers (id, title, abstract, authors, categories,
                           url, published_at, relevance_score, keyword_hits)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                        (best_paper.id, best_paper.title, best_paper.abstract,
                         best_paper.authors, best_paper.categories, best_paper.url,
                         best_paper.published_at, best_score, best_hits),
                    )
                    conn.commit()
            return {
                "id": best_paper.id,
                "title": best_paper.title,
                "abstract": best_paper.abstract,
                "url": best_paper.url,
            }

    # Tier 3: Random high-scoring archived paper
    with conn.cursor() as cur:
        cur.execute(
            """SELECT id, title, abstract, url
               FROM papers
               WHERE NOT skipped
               ORDER BY relevance_score DESC
               LIMIT 10"""
        )
        top_papers = cur.fetchall()
    if top_papers:
        return random.choice(top_papers)

    # Tier 4: Nothing found
    return None


def _store_spark_idea(conn, paper_id: str, idea: dict, embedding: list[float], user_id: int) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO ideas
               (paper_id, hypothesis, method, dataset,
                novelty_score, feasibility_score, embedding, sent_at, on_demand_by)
               VALUES (%s,%s,%s,%s,%s,%s,%s::vector,NOW(),%s)
               RETURNING id""",
            (paper_id, idea["hypothesis"], idea["method"], idea["dataset"],
             idea["novelty_score"], idea["feasibility_score"], embedding, user_id),
        )
        idea_id = cur.fetchone()["id"]
        conn.commit()
    return idea_id
