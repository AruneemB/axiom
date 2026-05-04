import json
from http.server import BaseHTTPRequestHandler

import psycopg2

from lib.config import load_config
from lib.db import get_connection
from lib.openrouter import synthesize_idea
from lib.embeddings import embed_text
from lib.telegram_client import send_message, send_idea_message
from lib.arxiv import fetch_recent_papers
from lib.filter import RelevanceFilter
from scripts.sync_topics import sync_topic_weights


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
            # Ensure all topics from ALLOWED_TOPICS exist in topic_weights
            sync_topic_weights(conn, cfg.allowed_topics)
            result = run_spark(user_id, chat_id, conn, cfg)
            self._respond(200, result)
        except Exception as e:
            import traceback
            print(f"[spark] UNHANDLED ERROR: {traceback.format_exc()}")
            try:
                send_message(chat_id, "Something went wrong. Please try again in a moment.", cfg.telegram_bot_token)
            except Exception as notify_err:
                print(f"[spark] failed to notify Telegram: {notify_err}")
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
    paper, tier_results = _find_paper_for_spark(conn, cfg)
    if not paper:
        send_message(chat_id, "No papers available right now. Try again later.", cfg.telegram_bot_token)
        return {"ok": False, "reason": "no_papers", "tier_results": tier_results}

    idea, debug = synthesize_idea(
        title=paper["title"],
        abstract=paper["abstract"],
        model=cfg.default_model,
        api_key=cfg.openrouter_api_key,
        fallback_model=cfg.fallback_model,
        timeout=cfg.deliver_llm_timeout,
    )

    if idea is None:
        if "Max retries reached" in debug or "Primary failed" in debug:
            msg = "The AI model is taking a bit too long to think. Please try again in a moment."
        else:
            msg = "I couldn't generate an idea from this paper. Let's try another one later."
        
        send_message(chat_id, msg, cfg.telegram_bot_token)
        return {"ok": False, "reason": "llm_failure"}

    if idea["novelty_score"] + idea["feasibility_score"] < cfg.quality_gate_min:
        send_message(chat_id, "The idea didn't pass the quality gate. Try again later.", cfg.telegram_bot_token)
        return {"ok": False, "reason": "below_quality_gate"}

    try:
        idea_embedding = embed_text(
            idea["hypothesis"] + " " + idea["method"],
            model=cfg.embedding_model,
            api_key=cfg.openrouter_api_key,
        )
    except Exception as e:
        print(f"[spark] embedding failed, storing without: {e}")
        idea_embedding = None

    idea_id = _store_spark_idea(conn, paper["id"], idea, idea_embedding, user_id)

    # Mark paper as processed so it won't be selected again
    with conn.cursor() as cur:
        cur.execute("UPDATE papers SET processed=TRUE WHERE id=%s", (paper["id"],))
        conn.commit()

    send_idea_message(
        chat_id=chat_id,
        idea_id=idea_id,
        title=paper["title"],
        url=paper["url"],
        idea=idea,
        bot_token=cfg.telegram_bot_token,
    )

    return {"ok": True, "idea_id": idea_id}


def _find_paper_for_spark(conn, cfg) -> tuple[dict | None, dict]:
    tiers = {}

    # Tier 1: Unprocessed papers in DB (citation-boosted)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, title, abstract, url
                   FROM papers
                   WHERE NOT processed AND NOT skipped
                   ORDER BY (
                     relevance_score + %s * LN(GREATEST(COALESCE(citation_count, 0) + 1, 1))
                   ) DESC
                   LIMIT 1""",
                (cfg.citation_weight,),
            )
            paper = cur.fetchone()
        tiers["tier1_unprocessed"] = 1 if paper else 0
        print(f"[spark] Tier 1: {tiers['tier1_unprocessed']} unprocessed papers found")
        if paper:
            return paper, tiers
    except psycopg2.DatabaseError as e:
        conn.rollback()
        tiers["tier1_unprocessed"] = 0
        print(f"[spark] Tier 1 DB error, falling through: {e}")

    # Tier 1.5: Papers processed by deliver but not yet sparked on-demand (citation-boosted)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT p.id, p.title, p.abstract, p.url
                   FROM papers p
                   WHERE p.processed = TRUE AND p.skipped = FALSE
                     AND NOT EXISTS (
                       SELECT 1 FROM ideas i
                       WHERE i.paper_id = p.id AND i.on_demand_by IS NOT NULL
                     )
                   ORDER BY (
                     p.relevance_score + %s * LN(GREATEST(COALESCE(p.citation_count, 0) + 1, 1))
                   ) DESC
                   LIMIT 1""",
                (cfg.citation_weight,),
            )
            paper = cur.fetchone()
        tiers["tier1_5_processed_not_sparked"] = 1 if paper else 0
        print(f"[spark] Tier 1.5: {tiers['tier1_5_processed_not_sparked']} processed-not-sparked papers found")
        if paper:
            return paper, tiers
    except psycopg2.DatabaseError as e:
        conn.rollback()
        tiers["tier1_5_processed_not_sparked"] = 0
        print(f"[spark] Tier 1.5 DB error, falling through: {e}")

    # Tier 2: Expanded arXiv fetch (7-day window)
    print("[spark] Tier 2: fetching fresh arXiv papers (7-day window)")
    arxiv_papers = fetch_recent_papers(
        categories=cfg.arxiv_categories,
        max_results=cfg.arxiv_max_results,
        hours=168,
    )
    arxiv_raw_count = len(arxiv_papers) if arxiv_papers else 0
    if arxiv_papers:
        # Exclude papers that already have an on-demand idea
        # But allow re-evaluation of skipped papers and delivered papers
        with conn.cursor() as cur:
            arxiv_ids = [p.id for p in arxiv_papers]
            cur.execute(
                """SELECT p.id FROM papers p
                   WHERE p.id = ANY(%s)
                     AND (p.processed = TRUE
                          AND EXISTS (
                            SELECT 1 FROM ideas i
                            WHERE i.paper_id = p.id AND i.on_demand_by IS NOT NULL
                          ))""",
                (arxiv_ids,),
            )
            processed_ids = {row["id"] for row in cur.fetchall()}
        arxiv_papers = [p for p in arxiv_papers if p.id not in processed_ids]

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
        tiers["tier2_arxiv_fetched"] = arxiv_raw_count
        tiers["tier2_arxiv_keyword_matches"] = len(scored)
        print(
            f"[spark] Tier 2: arXiv returned {arxiv_raw_count} papers; "
            f"{len(arxiv_papers)} after dedup filter; {len(scored)} matched keywords"
        )
        if scored:
            scored.sort(key=lambda x: x[0], reverse=True)
            best_score, best_hits, best_paper = scored[0]
            with conn.cursor() as cur:
                # Check if paper already exists (as skipped)
                cur.execute("SELECT id FROM papers WHERE id = %s", (best_paper.id,))
                exists = cur.fetchone()

                if exists:
                    # Update the skipped paper with new score and marks it as available
                    cur.execute(
                        """UPDATE papers
                           SET relevance_score = %s, keyword_hits = %s, skipped = FALSE, skip_reason = NULL
                           WHERE id = %s""",
                        (best_score, best_hits, best_paper.id),
                    )
                else:
                    # Insert new paper
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
            }, tiers
    else:
        tiers["tier2_arxiv_fetched"] = arxiv_raw_count
        tiers["tier2_arxiv_keyword_matches"] = 0
        print(f"[spark] Tier 2: arXiv returned {arxiv_raw_count} papers; 0 matched keywords")

    # Tier 3: Re-evaluate skipped papers in DB against current topics
    print("[spark] Tier 3: re-evaluating skipped papers")
    with conn.cursor() as cur:
        cur.execute(
            """SELECT id, title, abstract, url
               FROM papers
               WHERE skipped = TRUE
               ORDER BY published_at DESC
               LIMIT 50"""
        )
        skipped_papers = cur.fetchall()

    if skipped_papers:
        relevance_filter = RelevanceFilter(
            topics=cfg.allowed_topics,
            threshold=cfg.relevance_threshold,
        )
        scored = []
        for p in skipped_papers:
            score, keyword_hits = relevance_filter.score(p["abstract"])
            if keyword_hits:
                scored.append((score, keyword_hits, p))
        tiers["tier3_skipped_reevaluated"] = len(skipped_papers)
        tiers["tier3_skipped_keyword_matches"] = len(scored)
        print(
            f"[spark] Tier 3: {len(skipped_papers)} skipped papers re-evaluated; "
            f"{len(scored)} matched keywords"
        )
        if scored:
            scored.sort(key=lambda x: x[0], reverse=True)
            best_score, best_hits, best_paper = scored[0]
            with conn.cursor() as cur:
                cur.execute(
                    """UPDATE papers
                       SET relevance_score = %s, keyword_hits = %s,
                           skipped = FALSE, skip_reason = NULL
                       WHERE id = %s""",
                    (best_score, best_hits, best_paper["id"]),
                )
                conn.commit()
            return best_paper, tiers
    else:
        tiers["tier3_skipped_reevaluated"] = 0
        tiers["tier3_skipped_keyword_matches"] = 0
        print("[spark] Tier 3: no skipped papers in DB to re-evaluate")

    # Tier 4: Nothing found
    print("[spark] Tier 4: exhausted all tiers — no paper found")
    return None, tiers


def _store_spark_idea(conn, paper_id: str, idea: dict, embedding: list[float] | None, user_id: int) -> int:
    with conn.cursor() as cur:
        if embedding is not None:
            cur.execute(
                """INSERT INTO ideas
                   (paper_id, hypothesis, method, dataset,
                    novelty_score, feasibility_score, embedding, sent_at, on_demand_by)
                   VALUES (%s,%s,%s,%s,%s,%s,%s::vector,NOW(),%s)
                   RETURNING id""",
                (paper_id, idea["hypothesis"], idea["method"], idea["dataset"],
                 idea["novelty_score"], idea["feasibility_score"], embedding, user_id),
            )
        else:
            cur.execute(
                """INSERT INTO ideas
                   (paper_id, hypothesis, method, dataset,
                    novelty_score, feasibility_score, sent_at, on_demand_by)
                   VALUES (%s,%s,%s,%s,%s,%s,NOW(),%s)
                   RETURNING id""",
                (paper_id, idea["hypothesis"], idea["method"], idea["dataset"],
                 idea["novelty_score"], idea["feasibility_score"], user_id),
            )
        idea_id = cur.fetchone()["id"]
        conn.commit()
    return idea_id
