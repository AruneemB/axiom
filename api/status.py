import json
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

from lib.config import load_config
from lib.db import get_connection


class handler(BaseHTTPRequestHandler):

    def do_GET(self):
        cfg = load_config()

        params = parse_qs(urlparse(self.path).query)
        auth_header = self.headers.get("Authorization", "")
        bearer_token = auth_header[7:].strip() if auth_header.lower().startswith("bearer ") else None
        key_param = params.get("key", [None])[0]

        # Public health check (no secret) — minimal response
        if cfg.cron_secret not in (bearer_token, key_param):
            self._respond(200, {"status": "active"})
            return

        try:
            self._respond(200, run_status(cfg))
        except Exception as e:
            import traceback
            print(f"[status] ERROR: {traceback.format_exc()}")
            self._respond(500, {"error": str(e)})

    def _respond(self, status: int, body: dict):
        payload = json.dumps(body, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(payload))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(payload)


def run_status(cfg) -> dict:
    conn = get_connection(cfg.database_url)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS n FROM papers")
            total = cur.fetchone()["n"]

            cur.execute("SELECT COUNT(*) AS n FROM papers WHERE NOT processed AND NOT skipped")
            available = cur.fetchone()["n"]

            cur.execute("SELECT COUNT(*) AS n FROM papers WHERE processed = TRUE")
            processed = cur.fetchone()["n"]

            cur.execute(
                "SELECT COUNT(*) AS n FROM papers WHERE skipped = TRUE AND skip_reason = 'below_relevance_threshold'"
            )
            skipped_relevance = cur.fetchone()["n"]

            cur.execute(
                "SELECT COUNT(*) AS n FROM papers WHERE skipped = TRUE AND skip_reason != 'below_relevance_threshold'"
            )
            skipped_other = cur.fetchone()["n"]

            cur.execute("SELECT MAX(published_at) AS latest FROM papers")
            latest_published = cur.fetchone()["latest"]

            cur.execute("SELECT COUNT(*) AS n FROM ideas")
            total_ideas = cur.fetchone()["n"]

            cur.execute("SELECT MAX(sent_at) AS last FROM ideas")
            last_deliver = cur.fetchone()["last"]

            cur.execute("SELECT COUNT(*) AS n FROM allowed_users")
            users_total = cur.fetchone()["n"]

            cur.execute(
                """SELECT COUNT(*) AS n FROM allowed_users
                   WHERE NOT paused OR (paused AND pause_until < NOW())"""
            )
            users_active = cur.fetchone()["n"]

        return {
            "status": "active",
            "papers": {
                "total": total,
                "available": available,
                "processed": processed,
                "skipped_relevance": skipped_relevance,
                "skipped_other": skipped_other,
                "latest_published": latest_published,
            },
            "ideas": {
                "total": total_ideas,
                "last_deliver": last_deliver,
            },
            "users": {
                "total": users_total,
                "active": users_active,
            },
            "config": {
                "arxiv_categories": cfg.arxiv_categories,
                "allowed_topics": cfg.allowed_topics,
                "relevance_threshold": cfg.relevance_threshold,
                "arxiv_max_results": cfg.arxiv_max_results,
                "citation_weight": cfg.citation_weight,
                "quality_gate_min": cfg.quality_gate_min,
            },
        }
    finally:
        conn.close()
