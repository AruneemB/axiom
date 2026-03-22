import json
import hmac
from http.server import BaseHTTPRequestHandler

from lib.config import load_config
from lib.db import get_connection
from lib.telegram_client import send_message

COMMANDS = {"/start", "/status", "/topics", "/pause", "/resume", "/feedback"}


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
