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
                    """SELECT id, title, categories, url, fetched_at
                       FROM papers
                       WHERE NOT skipped
                       ORDER BY fetched_at DESC
                       LIMIT 20"""
                )
                rows = cur.fetchall()
            conn.close()

            papers = []
            for row in rows:
                papers.append({
                    "id": row["id"],
                    "title": row["title"],
                    "categories": row["categories"],
                    "url": row["url"],
                    "fetched_at": row["fetched_at"].isoformat() if row["fetched_at"] else None,
                })

            self._respond(200, {"papers": papers})
        except Exception as e:
            self._respond(500, {"error": str(e)})

    def _respond(self, status: int, body: dict):
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(payload))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(payload)
