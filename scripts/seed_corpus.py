"""One-time script to seed the relevance corpus with high-quality papers."""
import argparse
from xml.etree import ElementTree as ET

import httpx

from lib.embeddings import embed_text
from lib.db import get_connection

ARXIV_API = "https://export.arxiv.org/api/query"


def main():
    parser = argparse.ArgumentParser(description="Seed the relevance corpus")
    parser.add_argument("--papers", required=True, help="Comma-separated arXiv IDs")
    parser.add_argument("--database-url", required=True, help="Neon connection string")
    args = parser.parse_args()

    paper_ids = [p.strip() for p in args.papers.split(",")]
    conn = get_connection(args.database_url)
    ns = {"atom": "http://www.w3.org/2005/Atom"}

    for arxiv_id in paper_ids:
        resp = httpx.get(ARXIV_API, params={"id_list": arxiv_id}, timeout=20)
        resp.raise_for_status()

        root = ET.fromstring(resp.text)
        entry = root.find("atom:entry", ns)
        if entry is None:
            print(f"  SKIP {arxiv_id}: not found")
            continue

        title = entry.find("atom:title", ns).text.strip().replace("\n", " ")
        abstract = entry.find("atom:summary", ns).text.strip().replace("\n", " ")

        embedding = embed_text(abstract)

        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO seed_corpus (title, abstract, embedding)
                   VALUES (%s, %s, %s::vector)""",
                (title, abstract, embedding),
            )
        conn.commit()
        print(f"  OK   {arxiv_id}: {title[:60]}")

    conn.close()
    print(f"Done. Seeded {len(paper_ids)} papers.")


if __name__ == "__main__":
    main()
