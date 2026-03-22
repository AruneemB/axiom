import json
from http.server import BaseHTTPRequestHandler

from lib.config import load_config
from lib.db import get_connection


class handler(BaseHTTPRequestHandler):

    def do_GET(self):
        try:
            cfg = load_config()
            conn = get_connection(cfg.database_url)
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT
                        (SELECT COUNT(*) FROM papers) AS total_papers,
                        (SELECT COUNT(*) FROM ideas) AS total_ideas,
                        (SELECT MAX(fetched_at) FROM papers) AS last_fetch,
                        (SELECT MAX(sent_at) FROM ideas) AS last_deliver"""
                )
                row = cur.fetchone()
            conn.close()

            body = {
                "status": "active",
                "total_papers": row["total_papers"],
                "total_ideas": row["total_ideas"],
                "last_fetch": row["last_fetch"].isoformat() if row["last_fetch"] else None,
                "last_deliver": row["last_deliver"].isoformat() if row["last_deliver"] else None,
            }
            self._respond(200, body)
        except Exception as e:
            self._respond(500, {"status": "error", "error": str(e)})

    def _respond(self, status: int, body: dict):
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(payload))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(payload)
