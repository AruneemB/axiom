import json
import hmac
import random
from http.server import BaseHTTPRequestHandler

from lib.config import load_config
from lib.db import get_connection
from lib.telegram_client import send_message, send_idea_message
from lib.openrouter import synthesize_idea
from lib.embeddings import embed_text
from lib.arxiv import fetch_recent_papers
from lib.filter import RelevanceFilter

COMMANDS = {"/start", "/status", "/topics", "/pause", "/resume", "/feedback", "/spark"}


class handler(BaseHTTPRequestHandler):

    def do_POST(self):
        cfg = load_config()

        # Layer 1: Verify webhook secret header
        secret = self.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if not hmac.compare_digest(secret, cfg.telegram_webhook_secret):
            self.send_response(401)
            self.end_headers()
            return

        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length))

        conn = get_connection(cfg.database_url)

        try:
            if "callback_query" in body:
                handle_callback(body["callback_query"], conn, cfg)
            elif "message" in body:
                handle_message(body["message"], conn, cfg)
        finally:
            conn.close()

        self.send_response(200)
        self.end_headers()


def handle_message(msg: dict, conn, cfg):
    user = msg.get("from", {})
    user_id = user.get("id")
    text = msg.get("text", "").strip()
    chat_id = msg["chat"]["id"]

    if not user_id or not text:
        return

    # Handle /start authentication
    if text.startswith("/start"):
        parts = text.split(maxsplit=1)
        token = parts[1] if len(parts) > 1 else ""

        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM allowed_users WHERE user_id = %s", (user_id,))
            already_allowed = cur.fetchone()

        if already_allowed:
            send_message(chat_id, "You already have access to Axiom.", cfg.telegram_bot_token)
            return

        if hmac.compare_digest(token, cfg.bot_password):
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO allowed_users (user_id, username, first_name)
                       VALUES (%s, %s, %s) ON CONFLICT DO NOTHING""",
                    (user_id, user.get("username"), user.get("first_name")),
                )
                conn.commit()
            send_message(
                chat_id,
                "Access granted. Axiom will deliver your first ideas tomorrow morning.",
                cfg.telegram_bot_token,
            )
        else:
            send_message(chat_id, "Invalid token.", cfg.telegram_bot_token)
        return

    # Layer 2: Whitelist check for all other messages
    with conn.cursor() as cur:
        cur.execute("SELECT paused, pause_until FROM allowed_users WHERE user_id = %s", (user_id,))
        row = cur.fetchone()

    if not row:
        return  # Silent ignore — do not reveal bot existence

    if text == "/status":
        handle_status(chat_id, conn, cfg)
    elif text == "/topics":
        handle_topics(chat_id, conn, cfg)
    elif text == "/pause":
        handle_pause(user_id, chat_id, conn, cfg)
    elif text == "/resume":
        handle_resume(user_id, chat_id, conn, cfg)
    elif text == "/feedback":
        handle_feedback_summary(user_id, chat_id, conn, cfg)
    elif text == "/spark":
        handle_spark(user_id, chat_id, conn, cfg)


def handle_callback(cb: dict, conn, cfg):
    user_id = cb["from"]["id"]
    data = cb.get("data", "")
    callback_id = cb["id"]

    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM allowed_users WHERE user_id = %s", (user_id,))
        if not cur.fetchone():
            return

    # Expected data format: "feedback:{idea_id}:{value}" where value is 1 or -1
    if data.startswith("feedback:"):
        _, idea_id_str, value_str = data.split(":")
        idea_id = int(idea_id_str)
        value = int(value_str)

        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO idea_feedback (idea_id, user_id, feedback)
                   VALUES (%s, %s, %s)
                   ON CONFLICT (idea_id, user_id) DO UPDATE SET feedback = EXCLUDED.feedback""",
                (idea_id, user_id, value),
            )
            if value == 1:
                # Boost topic weights for keywords in this idea's paper
                cur.execute(
                    """UPDATE topic_weights tw
                       SET weight = LEAST(weight + 0.1, 3.0), updated_at = NOW()
                       FROM ideas i
                       JOIN papers p ON i.paper_id = p.id,
                            UNNEST(p.keyword_hits) AS kw
                       WHERE i.id = %s AND tw.topic = kw""",
                    (idea_id,),
                )
            else:
                cur.execute(
                    """UPDATE topic_weights tw
                       SET weight = GREATEST(weight - 0.05, 0.1), updated_at = NOW()
                       FROM ideas i
                       JOIN papers p ON i.paper_id = p.id,
                            UNNEST(p.keyword_hits) AS kw
                       WHERE i.id = %s AND tw.topic = kw""",
                    (idea_id,),
                )
            conn.commit()

    # Acknowledge the callback to remove the "loading" spinner in Telegram
    import httpx
    httpx.post(
        f"https://api.telegram.org/bot{cfg.telegram_bot_token}/answerCallbackQuery",
        json={"callback_query_id": callback_id},
    )


def handle_status(chat_id: int, conn, cfg):
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS count FROM papers WHERE fetched_at::date = CURRENT_DATE")
        fetched_today = cur.fetchone()["count"]
        cur.execute("SELECT COUNT(*) AS count FROM papers WHERE NOT processed AND NOT skipped")
        queued = cur.fetchone()["count"]
        cur.execute("SELECT COUNT(*) AS count FROM ideas WHERE sent_at::date = CURRENT_DATE")
        sent_today = cur.fetchone()["count"]

    msg = (
        f"*Axiom status*\n\n"
        f"Papers fetched today: {fetched_today}\n"
        f"Ideas in queue: {queued}\n"
        f"Ideas sent today: {sent_today}"
    )
    send_message(chat_id, msg, cfg.telegram_bot_token, parse_mode="MarkdownV2")


def handle_topics(chat_id: int, conn, cfg):
    with conn.cursor() as cur:
        cur.execute("SELECT topic, weight FROM topic_weights ORDER BY weight DESC LIMIT 15")
        rows = cur.fetchall()

    lines = [f"`{row['topic']}` — {row['weight']:.2f}" for row in rows]
    send_message(
        chat_id,
        "*Topic weights*\n\n" + "\n".join(lines),
        cfg.telegram_bot_token,
        parse_mode="MarkdownV2",
    )


def handle_pause(user_id: int, chat_id: int, conn, cfg):
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE allowed_users SET paused=TRUE, pause_until=NOW() + INTERVAL '24 hours' WHERE user_id=%s",
            (user_id,),
        )
        conn.commit()
    send_message(chat_id, "Delivery paused for 24 hours.", cfg.telegram_bot_token)


def handle_resume(user_id: int, chat_id: int, conn, cfg):
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE allowed_users SET paused=FALSE, pause_until=NULL WHERE user_id=%s",
            (user_id,),
        )
        conn.commit()
    send_message(chat_id, "Delivery resumed.", cfg.telegram_bot_token)


def handle_feedback_summary(user_id: int, chat_id: int, conn, cfg):
    with conn.cursor() as cur:
        cur.execute(
            """SELECT
                 SUM(CASE WHEN feedback = 1 THEN 1 ELSE 0 END) AS likes,
                 SUM(CASE WHEN feedback = -1 THEN 1 ELSE 0 END) AS dislikes
               FROM idea_feedback WHERE user_id = %s""",
            (user_id,),
        )
        row = cur.fetchone()

    likes = row["likes"] if row and row["likes"] else 0
    dislikes = row["dislikes"] if row and row["dislikes"] else 0
    send_message(
        chat_id,
        f"*Your feedback*\n\nLiked: {likes}  ·  Skipped: {dislikes}",
        cfg.telegram_bot_token,
        parse_mode="MarkdownV2",
    )


def handle_spark(user_id: int, chat_id: int, conn, cfg):
    # Rate limit: 1 spark per 10 minutes per user
    with conn.cursor() as cur:
        cur.execute(
            """SELECT 1 FROM ideas
               WHERE on_demand_by = %s AND sent_at > NOW() - INTERVAL '10 minutes'
               LIMIT 1""",
            (user_id,),
        )
        if cur.fetchone():
            send_message(chat_id, "Please wait a few minutes before sparking again.", cfg.telegram_bot_token)
            return

    send_message(chat_id, "Searching for a paper...", cfg.telegram_bot_token)

    paper = _find_paper_for_spark(conn, cfg)
    if not paper:
        send_message(chat_id, "No papers available right now. Try again later.", cfg.telegram_bot_token)
        return

    idea = synthesize_idea(
        title=paper["title"],
        abstract=paper["abstract"],
        model=cfg.default_model,
        api_key=cfg.openrouter_api_key,
    )

    if idea is None:
        send_message(chat_id, "Could not generate an idea. Try again later.", cfg.telegram_bot_token)
        return

    # Softened quality gate: 10 vs normal 13
    if idea["novelty_score"] + idea["feasibility_score"] < 10:
        send_message(chat_id, "The idea didn't pass the quality gate. Try again later.", cfg.telegram_bot_token)
        return

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
        relevance_filter = RelevanceFilter(
            topics=cfg.allowed_topics,
            threshold=cfg.relevance_threshold,
            database_url=cfg.database_url,
            api_key=cfg.openrouter_api_key,
            embedding_model=cfg.embedding_model,
        )
        scored = []
        for p in arxiv_papers:
            score, keyword_hits = relevance_filter.score(p.abstract)
            if score >= cfg.relevance_threshold:
                scored.append((score, keyword_hits, p))
        if scored:
            scored.sort(key=lambda x: x[0], reverse=True)
            best_score, best_hits, best_paper = scored[0]
            # Store in DB if not already present
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
