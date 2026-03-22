"""Backfill missing embeddings for papers in the database."""
import argparse

from lib.embeddings import embed_text
from lib.db import get_connection


def main():
    parser = argparse.ArgumentParser(description="Backfill paper embeddings")
    parser.add_argument("--database-url", required=True, help="Neon connection string")
    parser.add_argument("--openrouter-api-key", required=True, help="OpenRouter API key")
    parser.add_argument("--embedding-model", default="openai/text-embedding-3-small",
                        help="Embedding model (default: openai/text-embedding-3-small)")
    args = parser.parse_args()

    conn = get_connection(args.database_url)

    with conn.cursor() as cur:
        cur.execute("SELECT id, abstract FROM papers WHERE embedding IS NULL")
        rows = cur.fetchall()

    print(f"Found {len(rows)} papers with missing embeddings.")

    for i, row in enumerate(rows, 1):
        embedding = embed_text(row["abstract"], model=args.embedding_model, api_key=args.openrouter_api_key)
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE papers SET embedding = %s::vector WHERE id = %s",
                (embedding, row["id"]),
            )
        conn.commit()

        if i % 10 == 0:
            print(f"  Progress: {i}/{len(rows)} papers updated")

    conn.close()
    print(f"Done. Updated {len(rows)} embeddings.")


if __name__ == "__main__":
    main()
