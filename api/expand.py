import json
from http.server import BaseHTTPRequestHandler

from lib.config import load_config
from lib.db import get_connection
from lib.openrouter import expand_idea
from lib.telegram_client import send_message


class handler(BaseHTTPRequestHandler):

    def do_POST(self):
        cfg = load_config()

        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length))

        if body.get("secret") != cfg.cron_secret:
            self._respond(401, {"error": "unauthorized"})
            return

        user_id = body.get("user_id")
        chat_id = body.get("chat_id")
        idea_id = body.get("idea_id")

        if not all(isinstance(v, int) for v in (user_id, chat_id, idea_id)):
            self._respond(400, {"error": "invalid payload"})
            return

        conn = get_connection(cfg.database_url)
        try:
            result = run_expand(chat_id, idea_id, conn, cfg)
            self._respond(200, result)
        except Exception as e:
            import traceback
            print(f"[expand] UNHANDLED ERROR: {traceback.format_exc()}")
            try:
                send_message(
                    chat_id,
                    "Something went wrong during deep-dive generation. Please try again.",
                    cfg.telegram_bot_token,
                )
            except Exception as notify_err:
                print(f"[expand] failed to notify Telegram: {notify_err}")
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


def run_expand(chat_id: int, idea_id: int, conn, cfg) -> dict:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT i.id, i.hypothesis, i.method, i.dataset,
                   i.expanded_sketch, p.title, p.abstract
            FROM ideas i
            JOIN papers p ON i.paper_id = p.id
            WHERE i.id = %s
            """,
            (idea_id,),
        )
        row = cur.fetchone()

    if not row:
        send_message(chat_id, f"Idea #{idea_id} not found.", cfg.telegram_bot_token)
        return {"ok": False, "reason": "idea_not_found"}

    # Guard against duplicate execution (e.g. Telegram retrying the webhook)
    if row["expanded_sketch"]:
        send_message(chat_id, _format_expand(idea_id, row["expanded_sketch"]), cfg.telegram_bot_token)
        return {"ok": True, "cached": True}

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
        return {"ok": False, "reason": "llm_failure", "error": err}

    with conn.cursor() as cur:
        cur.execute(
            "UPDATE ideas SET expanded_sketch = %s, expanded_at = NOW() WHERE id = %s",
            (json.dumps(sketch), idea_id),
        )
    conn.commit()

    send_message(chat_id, _format_expand(idea_id, sketch), cfg.telegram_bot_token)
    return {"ok": True}


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
