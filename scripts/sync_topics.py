#!/usr/bin/env python3
"""
Sync topic_weights table with ALLOWED_TOPICS from config.

This ensures that all topics used for keyword matching have corresponding
entries in topic_weights, so feedback updates actually work.

Can be run standalone or imported and called from other scripts.
"""

from lib.config import load_config
from lib.db import get_connection


def sync_topic_weights(conn, topics: list[str]) -> dict:
    """
    Ensure all topics exist in topic_weights table.

    Returns:
        dict with 'inserted' count and 'total' count
    """
    inserted = 0

    with conn.cursor() as cur:
        for topic in topics:
            topic_lower = topic.lower().strip()
            cur.execute(
                """INSERT INTO topic_weights (topic)
                   VALUES (%s)
                   ON CONFLICT (topic) DO NOTHING""",
                (topic_lower,)
            )
            if cur.rowcount > 0:
                inserted += 1

        conn.commit()

        cur.execute("SELECT COUNT(*) as count FROM topic_weights")
        total = cur.fetchone()["count"]

    return {"inserted": inserted, "total": total}


def main():
    cfg = load_config()
    conn = get_connection(cfg.database_url)

    print(f"Syncing {len(cfg.allowed_topics)} topics from ALLOWED_TOPICS...")
    result = sync_topic_weights(conn, cfg.allowed_topics)

    print(f"✓ Inserted {result['inserted']} new topics")
    print(f"✓ Total topics in topic_weights: {result['total']}")

    conn.close()


if __name__ == "__main__":
    main()
