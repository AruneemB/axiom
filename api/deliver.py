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

        # Verify cron secret (Bearer header or ?key= param)
        from urllib.parse import urlparse, parse_qs
        params = parse_qs(urlparse(self.path).query)
        auth_header = self.headers.get("Authorization", "")
        bearer_token = None
        if auth_header.lower().startswith("bearer "):
            bearer_token = auth_header[7:].strip()
        key_param = params.get("key", [None])[0]

        if cfg.cron_secret not in (bearer_token, key_param):
            self._respond(401, {"error": "unauthorized"})
            return

        try:
            print("[deliver] cron triggered, starting delivery run")
            result = run_deliver(cfg)
            print(f"[deliver] completed: sent={result.get('sent', 0)}")
            self._respond(200, result)
        except Exception as e:
            import traceback
            print(f"[deliver] FATAL: {e}")
            traceback.print_exc()
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
    try:
        sent_count = 0
        processed_papers = []
        skipped_details = {
            "llm_parse_error": 0,
            "below_quality_gate": 0,
            "duplicate_idea": 0
        }

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

        # Ensure TELEGRAM_CHAT_IDS owners are always registered so delivery
        # works even before they send /start for the first time.
        if not active_users and cfg.telegram_chat_ids:
            with conn.cursor() as cur:
                for uid in cfg.telegram_chat_ids:
                    cur.execute(
                        "INSERT INTO allowed_users (user_id) VALUES (%s) ON CONFLICT DO NOTHING",
                        (uid,),
                    )
                conn.commit()
            active_users = list(cfg.telegram_chat_ids)
            print(f"[deliver] bootstrapped {len(active_users)} owner(s) from TELEGRAM_CHAT_IDS")

        print(f"[deliver] found {len(papers)} papers, {len(active_users)} active users")

        if not papers or not active_users:
            print(f"[deliver] early exit: no papers or no active users")
            return {
                "sent": 0,
                "reason": "no papers or no active users",
                "stats": {
                    "papers_found": len(papers),
                    "active_users": len(active_users)
                }
            }

        # Select model (deep-dive on configured day)
        model = cfg.deepdive_model if datetime.utcnow().weekday() == cfg.deepdive_day \
                else cfg.default_model

        for paper in papers:
            if sent_count >= cfg.max_ideas_per_day:
                print(f"[deliver] reached max_ideas_per_day limit ({cfg.max_ideas_per_day})")
                break

            paper_id = paper["id"]
            title = paper["title"]
            abstract = paper["abstract"]
            url = paper["url"]

            print(f"[deliver] processing paper: {title[:60]}...")

            idea, _ = synthesize_idea(
                title=title,
                abstract=abstract,
                model=model,
                api_key=cfg.openrouter_api_key,
                fallback_model=cfg.fallback_model,
                timeout=cfg.openrouter_timeout,
            )

            if idea is None:
                print(f"[deliver] skipped (llm_parse_error): {paper_id}")
                mark_processed(conn, paper_id, skip_reason="llm_parse_error")
                skipped_details["llm_parse_error"] += 1
                continue

            # Quality gate
            if idea["novelty_score"] + idea["feasibility_score"] < cfg.quality_gate_min:
                print(f"[deliver] skipped (below_quality_gate): {paper_id} (score: {idea['novelty_score'] + idea['feasibility_score']})")
                mark_processed(conn, paper_id, skip_reason="below_quality_gate")
                skipped_details["below_quality_gate"] += 1
                continue

            # Dedup check against previously sent ideas
            try:
                idea_embedding = embed_text(
                    idea["hypothesis"] + " " + idea["method"],
                    model=cfg.embedding_model,
                    api_key=cfg.openrouter_api_key,
                )
            except Exception as e:
                print(f"[deliver] embedding failed, storing without: {e}")
                idea_embedding = None

            if idea_embedding is not None and is_duplicate(conn, idea_embedding, cfg.dedup_similarity_max):
                print(f"[deliver] skipped (duplicate_idea): {paper_id}")
                mark_processed(conn, paper_id, skip_reason="duplicate_idea")
                skipped_details["duplicate_idea"] += 1
                continue

            # Persist idea
            idea_id = store_idea(conn, paper_id, idea, idea_embedding)

            # Send to all active users
            for user_id in active_users:
                try:
                    send_idea_message(
                        chat_id=user_id,
                        idea_id=idea_id,
                        title=title,
                        url=url,
                        idea=idea,
                        bot_token=cfg.telegram_bot_token,
                    )
                    print(f"[deliver] sent to user {user_id}")
                except Exception as e:
                    print(f"[deliver] failed to send to user {user_id}: {e}")

            mark_processed(conn, paper_id)
            sent_count += 1
            processed_papers.append(paper_id)
            print(f"[deliver] successfully processed and sent idea {idea_id}")

        return {
            "sent": sent_count,
            "papers": processed_papers,
            "model": model,
            "details": {
                "skipped": skipped_details
            }
        }
    finally:
        conn.close()


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
