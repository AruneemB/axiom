import json
from datetime import datetime
from http.server import BaseHTTPRequestHandler

from lib.config import load_config
from lib.openrouter import synthesize_idea
from lib.embeddings import embed_text
from lib.telegram_client import send_idea_message
from lib.db import get_connection


class handler(BaseHTTPRequestHandler):

    def do_GET(self):
        cfg = load_config()

        from urllib.parse import urlparse, parse_qs
        params = parse_qs(urlparse(self.path).query)
        if params.get("key", [None])[0] != cfg.cron_secret:
            self._respond(401, {"error": "unauthorized"})
            return

        try:
            result = run_deliver(cfg)
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


def run_deliver(cfg) -> dict:
    conn = get_connection(cfg.database_url)
    sent_count = 0
    processed_papers = []

    with conn.cursor() as cur:
        # Fetch top unprocessed papers by relevance score
        cur.execute(
            """SELECT id, title, abstract, url
               FROM papers
               WHERE NOT processed AND NOT skipped
               ORDER BY relevance_score DESC
               LIMIT %s""",
            (cfg.max_ideas_per_day * 2,),  # fetch extra in case some fail quality gate
        )
        papers = cur.fetchall()

        # Fetch active authorized users
        cur.execute(
            """SELECT user_id FROM allowed_users
               WHERE NOT paused
               OR (paused AND pause_until < NOW())"""
        )
        active_users = [row["user_id"] for row in cur.fetchall()]

    if not papers or not active_users:
        conn.close()
        return {"sent": 0, "reason": "no papers or no active users"}

    # Select model (deep-dive on configured day)
    model = cfg.deepdive_model if datetime.utcnow().weekday() == cfg.deepdive_day \
            else cfg.default_model

    for paper in papers:
        if sent_count >= cfg.max_ideas_per_day:
            break

        paper_id = paper["id"]
        title = paper["title"]
        abstract = paper["abstract"]
        url = paper["url"]

        idea = synthesize_idea(
            title=title,
            abstract=abstract,
            model=model,
            api_key=cfg.openrouter_api_key,
        )

        if idea is None:
            mark_processed(conn, paper_id, skip_reason="llm_parse_error")
            continue

        # Quality gate
        if idea["novelty_score"] + idea["feasibility_score"] < cfg.quality_gate_min:
            mark_processed(conn, paper_id, skip_reason="below_quality_gate")
            continue

        # Dedup check against previously sent ideas
        idea_embedding = embed_text(idea["hypothesis"] + " " + idea["method"])
        if idea_embedding is not None and is_duplicate(conn, idea_embedding, cfg.dedup_similarity_max):
            mark_processed(conn, paper_id, skip_reason="duplicate_idea")
            continue

        # Persist idea
        idea_id = store_idea(conn, paper_id, idea, idea_embedding)

        # Send to all active users
        for user_id in active_users:
            send_idea_message(
                chat_id=user_id,
                idea_id=idea_id,
                title=title,
                url=url,
                idea=idea,
                bot_token=cfg.telegram_bot_token,
            )

        mark_processed(conn, paper_id)
        sent_count += 1
        processed_papers.append(paper_id)

    conn.close()
    return {"sent": sent_count, "papers": processed_papers, "model": model}


def mark_processed(conn, paper_id: str, skip_reason: str = None):
    with conn.cursor() as cur:
        if skip_reason:
            cur.execute(
                "UPDATE papers SET processed=TRUE, skipped=TRUE, skip_reason=%s WHERE id=%s",
                (skip_reason, paper_id),
            )
        else:
            cur.execute(
                "UPDATE papers SET processed=TRUE WHERE id=%s",
                (paper_id,),
            )
        conn.commit()


def is_duplicate(conn, embedding: list[float], threshold: float) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            """SELECT 1 FROM ideas
               WHERE embedding IS NOT NULL
               AND 1 - (embedding <=> %s::vector) > %s
               LIMIT 1""",
            (embedding, threshold),
        )
        return cur.fetchone() is not None


def store_idea(conn, paper_id: str, idea: dict, embedding: list[float] | None) -> int:
    with conn.cursor() as cur:
        if embedding is not None:
            cur.execute(
                """INSERT INTO ideas
                   (paper_id, hypothesis, method, dataset,
                    novelty_score, feasibility_score, embedding, sent_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s::vector,NOW())
                   RETURNING id""",
                (paper_id, idea["hypothesis"], idea["method"], idea["dataset"],
                 idea["novelty_score"], idea["feasibility_score"], embedding),
            )
        else:
            cur.execute(
                """INSERT INTO ideas
                   (paper_id, hypothesis, method, dataset,
                    novelty_score, feasibility_score, sent_at)
                   VALUES (%s,%s,%s,%s,%s,%s,NOW())
                   RETURNING id""",
                (paper_id, idea["hypothesis"], idea["method"], idea["dataset"],
                 idea["novelty_score"], idea["feasibility_score"]),
            )
        idea_id = cur.fetchone()["id"]
        conn.commit()
    return idea_id
