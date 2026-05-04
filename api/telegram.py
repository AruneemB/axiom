import json
import hmac
import os
import re
from http.server import BaseHTTPRequestHandler
from datetime import datetime, timezone

import httpx
from github import GithubException

from lib.config import load_config
from lib.db import get_connection
from lib.telegram_client import send_message, esc
from lib.chat import (
    get_or_create_session, get_conversation_context, store_message,
    generate_chat_response, check_rate_limits
)
from lib.security_validator import validate_issue_content, detect_pii, sanitize_content, validate_user_input
from lib.github_client import create_issue, format_issue_body, generate_issue_title
from lib.rate_limiter import check_burst_limit, check_global_rate_limit, record_violation, check_auto_suspend
from lib.audit_logger import (
    log_security_event, is_telegram_ip,
    EVT_BLOCKED_UNKNOWN, EVT_RATE_LIMITED,
    EVT_VALIDATION_FAILED, EVT_AUTO_SUSPENDED,
    EVT_BURST_BLOCKED, EVT_IP_REJECTED,
)

COMMANDS = {"/start", "/status", "/topics", "/pause", "/resume", "/feedback", "/spark", "/chat", "/context", "/report", "/expand"}


class handler(BaseHTTPRequestHandler):

    def do_POST(self):
        cfg = load_config()

        # Layer 1: Verify webhook secret header
        secret = self.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if not hmac.compare_digest(secret, cfg.telegram_webhook_secret):
            self.send_response(401)
            self.end_headers()
            return

        # Layer 1b: Optional IP allowlist (Telegram CIDR ranges) — fail-closed:
        # a missing or non-Telegram header is treated as a rejection.
        if cfg.telegram_ip_allowlist_enabled:
            forwarded_pre = self.headers.get("X-Forwarded-For", "")
            req_ip_pre = forwarded_pre.split(",")[0].strip() if forwarded_pre else ""
            if not req_ip_pre or not is_telegram_ip(req_ip_pre):
                self.send_response(403)
                self.end_headers()
                return

        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length))

        # Extract client IP for downstream audit logging
        forwarded = self.headers.get("X-Forwarded-For", "")
        req_ip = forwarded.split(",")[0].strip() if forwarded else "unknown"

        # Respond 200 immediately so Telegram doesn't retry
        self.send_response(200)
        self.end_headers()

        conn = get_connection(cfg.database_url)

        try:
            if "callback_query" in body:
                handle_callback(body["callback_query"], conn, cfg, req_ip)
            elif "message" in body:
                handle_message(body["message"], conn, cfg, req_ip)
        finally:
            conn.close()


def handle_message(msg: dict, conn, cfg, req_ip: str = "unknown"):
    user = msg.get("from", {})
    user_id = user.get("id")
    text = msg.get("text", "").strip()
    chat_id = msg["chat"]["id"]

    if not user_id or not text:
        return

    # Burst / flood protection — checked before whitelist so unknown users
    # can't trivially enumerate the service via rapid-fire probing.
    burst_ok, _ = check_burst_limit(user_id, conn)
    if not burst_ok:
        log_security_event(conn, EVT_BURST_BLOCKED, user_id=user_id, ip_addr=req_ip)
        record_violation(user_id, "burst_blocked", conn)
        _check_and_apply_auto_suspend(user_id, chat_id, conn, cfg)
        return  # Silent — don't help an attacker gauge limits

    # Handle /start — open registration, no password required
    if text.startswith("/start"):
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM allowed_users WHERE user_id = %s", (user_id,))
            already_allowed = cur.fetchone()

        if already_allowed:
            send_message(chat_id, "You already have access to Axiom.", cfg.telegram_bot_token)
            return

        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO allowed_users (user_id, username, first_name)
                   VALUES (%s, %s, %s) ON CONFLICT DO NOTHING""",
                (user_id, user.get("username"), user.get("first_name")),
            )
            conn.commit()
        send_message(
            chat_id,
            "Welcome to Axiom. You'll receive your first research ideas tomorrow morning.",
            cfg.telegram_bot_token,
        )
        return

    # Layer 2: Whitelist check for all other messages
    with conn.cursor() as cur:
        cur.execute("SELECT paused, pause_until FROM allowed_users WHERE user_id = %s", (user_id,))
        row = cur.fetchone()

    if not row:
        log_security_event(conn, EVT_BLOCKED_UNKNOWN, user_id=user_id, ip_addr=req_ip)
        return  # Silent ignore — do not reveal bot existence

    if row["paused"] and row["pause_until"] and row["pause_until"] > datetime.now(timezone.utc):
        return  # Suspended — silently drop

    # Universal input validation — applies before every command handler
    is_valid, val_msg = validate_user_input(text)
    if not is_valid:
        log_security_event(conn, EVT_VALIDATION_FAILED, user_id=user_id,
                           details=text[:30], ip_addr=req_ip)
        record_violation(user_id, "validation_failed", conn)
        _check_and_apply_auto_suspend(user_id, chat_id, conn, cfg)
        send_message(chat_id, val_msg, cfg.telegram_bot_token)
        return

    # Universal command rate limit (/chat, /report, /expand have their own sub-systems)
    command = text.split()[0] if text.startswith("/") else "text"
    if command not in ("/chat", "/report", "/expand"):
        allowed, rl_msg = check_global_rate_limit(user_id, command, conn)
        if not allowed:
            log_security_event(conn, EVT_RATE_LIMITED, user_id=user_id,
                               details=command, ip_addr=req_ip)
            record_violation(user_id, "rate_limit_command", conn)
            _check_and_apply_auto_suspend(user_id, chat_id, conn, cfg)
            send_message(chat_id, rl_msg, cfg.telegram_bot_token)
            return

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
    elif text.startswith("/chat"):
        handle_chat(user_id, chat_id, text, conn, cfg)
    elif text == "/context":
        handle_context(user_id, chat_id, conn, cfg)
    elif text.startswith("/report"):
        handle_report(user_id, chat_id, text, msg, conn, cfg)
    elif text.startswith("/expand"):
        handle_expand(user_id, chat_id, text, conn, cfg)


def _check_and_apply_auto_suspend(user_id: int, chat_id: int, conn, cfg) -> None:
    just_suspended = check_auto_suspend(user_id, conn)
    if just_suspended:
        log_security_event(conn, EVT_AUTO_SUSPENDED, user_id=user_id)
        send_message(
            chat_id,
            "Your account has been temporarily suspended for 1 hour due to repeated policy violations.",
            cfg.telegram_bot_token,
        )


def handle_callback(cb: dict, conn, cfg, req_ip: str = "unknown"):
    user_id = cb["from"]["id"]
    data = cb.get("data", "")
    callback_id = cb["id"]

    with conn.cursor() as cur:
        cur.execute("SELECT paused, pause_until FROM allowed_users WHERE user_id = %s", (user_id,))
        row = cur.fetchone()
    if not row:
        return
    if row["paused"] and row["pause_until"] and row["pause_until"] > datetime.now(timezone.utc):
        return  # Suspended — silently drop

    # Burst and rate limit for callback buttons
    burst_ok, _ = check_burst_limit(user_id, conn)
    if not burst_ok:
        log_security_event(conn, EVT_BURST_BLOCKED, user_id=user_id, ip_addr=req_ip)
        record_violation(user_id, "burst_blocked", conn)
        return

    allowed, _ = check_global_rate_limit(user_id, "callback", conn)
    if not allowed:
        log_security_event(conn, EVT_RATE_LIMITED, user_id=user_id,
                           details="callback", ip_addr=req_ip)
        record_violation(user_id, "rate_limit_command", conn)
        cb_chat_id = cb.get("message", {}).get("chat", {}).get("id")
        if cb_chat_id:
            _check_and_apply_auto_suspend(user_id, cb_chat_id, conn, cfg)
        return

    chat_id = cb.get("message", {}).get("chat", {}).get("id")

    # Expected data formats:
    #   "feedback:{idea_id}:{value}" where value is 1 or -1
    #   "expand:{idea_id}"
    if data.startswith("expand:"):
        parts = data.split(":")
        if len(parts) == 2 and parts[1].isdigit():
            handle_expand(user_id, chat_id, f"/expand {parts[1]}", conn, cfg)
    elif data.startswith("feedback:"):
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

    lines = ["`{}`  —  {}".format(esc(row["topic"]), esc(f"{row['weight']:.2f}")) for row in rows]
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

    # Fire off the heavy work to a separate endpoint so the webhook returns fast
    base_url = os.environ.get("VERCEL_URL", "")
    if base_url and not base_url.startswith("http"):
        base_url = f"https://{base_url}"
    if not base_url:
        base_url = os.environ.get("SPARK_BASE_URL", "https://axiom-aruneemb.vercel.app")

    try:
        httpx.post(
            f"{base_url}/api/spark",
            json={"user_id": user_id, "chat_id": chat_id, "secret": cfg.cron_secret},
            timeout=1,
        )
    except Exception:
        pass  # Expected — we don't wait for the response


def handle_chat(user_id: int, chat_id: int, text: str, conn, cfg):
    if not cfg.chat_enabled:
        send_message(chat_id, "Chat is currently disabled.", cfg.telegram_bot_token)
        return

    user_message = text.replace("/chat", "", 1).strip()
    if not user_message:
        usage = (
            "Send /chat followed by your message to discuss your latest research idea.\n"
            "Example: /chat How would I implement this with tick data?"
        )
        send_message(chat_id, usage, cfg.telegram_bot_token)
        return

    allowed, error_msg = check_rate_limits(user_id, None, conn)
    if not allowed:
        send_message(chat_id, error_msg, cfg.telegram_bot_token)
        return

    try:
        session_id = get_or_create_session(user_id, None, None, conn)
    except ValueError:
        send_message(chat_id, "No research ideas available yet. Wait for your first delivery or use /spark.", cfg.telegram_bot_token)
        return

    context = get_conversation_context(session_id, cfg.chat_context_window, conn)
    store_message(session_id, "user", user_message, 0, conn)

    try:
        response_text, tokens_used = generate_chat_response(
            context, user_message, cfg.chat_model, cfg.openrouter_api_key, cfg.openrouter_timeout
        )
    except Exception:
        send_message(chat_id, "Sorry, I couldn't generate a response. Please try again.", cfg.telegram_bot_token)
        return

    store_message(session_id, "assistant", response_text, tokens_used, conn)
    send_message(chat_id, response_text, cfg.telegram_bot_token)


def handle_context(user_id: int, chat_id: int, conn, cfg):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT id, message_count
            FROM conversation_sessions
            WHERE user_id = %s AND expires_at > NOW()
            ORDER BY updated_at DESC
            LIMIT 1
        """, (user_id,))
        session = cur.fetchone()

    if not session:
        send_message(chat_id, "No active chat session. Start one with /chat.", cfg.telegram_bot_token)
        return

    context = get_conversation_context(session["id"], cfg.chat_context_window, conn)

    msg = (
        f"*Active Chat Context*\n\n"
        f"Paper: {esc(context['title'])}\n"
        f"Hypothesis: {esc(context['hypothesis'])}\n"
        f"Method: {esc(context['method'])}\n"
        f"Dataset: {esc(context['dataset'])}\n"
        f"Scores: Novelty {context['novelty_score']}/10, Feasibility {context['feasibility_score']}/10\n"
        f"Messages in session: {session['message_count']}"
    )
    send_message(chat_id, msg, cfg.telegram_bot_token, parse_mode="MarkdownV2")


def handle_report(user_id: int, chat_id: int, text: str, msg_obj: dict, conn, cfg):
    if not cfg.github_token:
        send_message(chat_id, "GitHub integration is not configured.", cfg.telegram_bot_token)
        return

    description = text.replace("/report", "", 1).strip()
    if not description:
        usage = (
            "Send /report followed by your issue description.\n"
            "Example: /report The novelty scores seem inflated for NLP papers"
        )
        send_message(chat_id, usage, cfg.telegram_bot_token)
        return

    # Daily rate limit
    with conn.cursor() as cur:
        cur.execute("""
            SELECT COUNT(*) FROM github_submissions
            WHERE user_id = %s AND submitted_at > CURRENT_DATE
        """, (user_id,))
        count = cur.fetchone()["count"]
        if count >= cfg.max_github_issues_per_day:
            send_message(chat_id, f"Daily issue limit reached ({cfg.max_github_issues_per_day}/day). Try again tomorrow.", cfg.telegram_bot_token)
            return

    # Security validation
    is_valid, error_msg = validate_issue_content(description)
    if not is_valid:
        send_message(chat_id, error_msg, cfg.telegram_bot_token)
        return

    # PII check
    pii_types = detect_pii(description)
    if pii_types:
        send_message(chat_id, f"Your submission contains personal information ({', '.join(pii_types)}). Please remove it and try again.", cfg.telegram_bot_token)
        return

    # Sanitize
    sanitized_description = sanitize_content(description)

    # AI-powered title generation
    title = None
    try:
        # Prompt 05.8: Generate concise title via LLM
        system_prompt = "Generate a concise GitHub issue title (under 70 chars) for this user report. Return only the title, nothing else."
        headers = {"Authorization": f"Bearer {cfg.openrouter_api_key}", "Content-Type": "application/json"}
        payload = {
            "model": cfg.chat_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": sanitized_description}
            ]
        }
        with httpx.Client(timeout=10) as client:
            resp = client.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload)
            resp.raise_for_status()
            title = resp.json()["choices"][0]["message"]["content"].strip().strip('"')
    except Exception:
        title = generate_issue_title(sanitized_description)

    # Build context
    context_data = None
    with conn.cursor() as cur:
        cur.execute("""
            SELECT id FROM conversation_sessions
            WHERE user_id = %s AND expires_at > NOW()
            ORDER BY updated_at DESC LIMIT 1
        """, (user_id,))
        session = cur.fetchone()
        if session:
            context_data = get_conversation_context(session["id"], cfg.chat_context_window, conn)

    user_info = {
        "username": msg_obj.get("from", {}).get("username", "unknown"),
        "user_id": user_id,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

    body = format_issue_body(sanitized_description, context_data, user_info)

    try:
        issue = create_issue(
            title, body, cfg.github_issue_labels, [],
            cfg.github_repo_owner, cfg.github_repo_name, cfg.github_token
        )
    except GithubException:
        send_message(chat_id, "Failed to create issue. Please try again later.", cfg.telegram_bot_token)
        return

    # Record submission
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO github_submissions (user_id, issue_number, issue_url, title, description, context_data)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (user_id, issue["number"], issue["html_url"], title, sanitized_description, json.dumps(context_data)))
        conn.commit()

    send_message(chat_id, f"Issue #{issue['number']} created successfully.\n{issue['html_url']}", cfg.telegram_bot_token)


def handle_expand(user_id: int, chat_id: int, text: str, conn, cfg):
    from lib.openrouter import expand_idea

    if not cfg.expand_enabled:
        send_message(chat_id, "Deep-dive synthesis is currently disabled.", cfg.telegram_bot_token)
        return

    parts = text.split()
    if len(parts) < 2 or not parts[1].isdigit():
        send_message(chat_id, "Usage: /expand {idea_id}\nExample: /expand 42", cfg.telegram_bot_token)
        return

    idea_id = int(parts[1])

    with conn.cursor() as cur:
        cur.execute("""
            SELECT i.id, i.hypothesis, i.method, i.dataset,
                   i.expanded_sketch, i.expanded_at,
                   p.title, p.abstract
            FROM ideas i
            JOIN papers p ON i.paper_id = p.id
            WHERE i.id = %s
        """, (idea_id,))
        row = cur.fetchone()

    if not row:
        send_message(chat_id, f"Idea #{idea_id} not found.", cfg.telegram_bot_token)
        return

    if row["expanded_sketch"]:
        send_message(chat_id, _format_expand(idea_id, row["expanded_sketch"]), cfg.telegram_bot_token)
        return

    # Rate-limit only on cache miss — cached hits are read-only and don't consume quota
    allowed, rl_msg = check_global_rate_limit(
        user_id, "/expand", conn, override_limit=cfg.expand_rate_limit_per_hour
    )
    if not allowed:
        send_message(chat_id, rl_msg, cfg.telegram_bot_token)
        return

    send_message(chat_id, f"Generating deep-dive for idea #{idea_id}...", cfg.telegram_bot_token)

    sketch, err = expand_idea(
        title=row["title"],
        abstract=row["abstract"],
        hypothesis=row["hypothesis"],
        method=row["method"],
        dataset=row["dataset"],
        model=cfg.expand_model,
        api_key=cfg.openrouter_api_key,
        fallback_model=cfg.fallback_model,
        timeout=cfg.expand_timeout,
    )

    if sketch is None:
        send_message(chat_id, "Could not generate deep-dive. Please try again later.", cfg.telegram_bot_token)
        return

    with conn.cursor() as cur:
        cur.execute(
            "UPDATE ideas SET expanded_sketch = %s, expanded_at = NOW() WHERE id = %s",
            (json.dumps(sketch), idea_id),
        )
    conn.commit()

    send_message(chat_id, _format_expand(idea_id, sketch), cfg.telegram_bot_token)


def _format_expand(idea_id: int, sketch: dict) -> str:
    MAX_CODE = 1100
    MAX_TESTS = 900
    MAX_TIMELINE = 900
    MAX_RISKS = 600

    def _trunc(text: str, limit: int) -> str:
        return text if len(text) <= limit else text[:limit - 1] + "…"

    tests_lines = "\n".join(
        f"• {t.get('test', '')} — {t.get('rationale', '')} ({t.get('threshold', '')})"
        for t in sketch.get("statistical_tests", [])
    )

    timeline_lines = "\n".join(
        f"Phase {i + 1} – {p.get('phase', '')} ({p.get('weeks', '?')} wk): {p.get('tasks', '')}"
        for i, p in enumerate(sketch.get("timeline", []))
    )

    return (
        f"Deep-Dive: Idea #{idea_id}\n"
        f"\n[Pseudocode]\n{_trunc(sketch.get('pseudocode', ''), MAX_CODE)}"
        f"\n\n[Statistical Tests]\n{_trunc(tests_lines, MAX_TESTS)}"
        f"\n\n[Implementation Timeline]\n{_trunc(timeline_lines, MAX_TIMELINE)}"
        f"\n\n[Risk Factors]\n{_trunc(sketch.get('risk_factors', ''), MAX_RISKS)}"
    )
