"""
index_docs.py — Populate doc_chunks table from Axiom's GitHub markdown docs.

Fetches markdown files from the GitHub repo, splits them into heading-aligned
chunks, embeds each chunk via OpenRouter, and stores in Postgres for RAG retrieval.

Usage:
    python scripts/index_docs.py

Required env vars (same as the main app):
    OPENROUTER_API_KEY
    DATABASE_URL
    GITHUB_TOKEN
    GITHUB_REPO_OWNER
    GITHUB_REPO_NAME

Optional:
    EMBEDDING_MODEL   (default: openai/text-embedding-3-small)
"""

import os
import re
import sys
import time

# Allow imports from project root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from github import Github
from lib.db import get_connection
from lib.embeddings import embed_text

# Markdown files to index (paths relative to repo root)
DOC_PATHS = [
    "docs-axiom/AXIOM-SPEC.md",
    "docs-axiom/AXIOM-INSIGHTS.md",
    "docs-axiom/AXIOM-CHAT-AND-ISSUES.md",
    "docs-axiom/AXIOM-ROADMAP.md",
    "README.md",
    "ARCHITECTURE.md",
    "TECH-STACK.md",
]

MAX_CHUNK_CHARS = 800
OVERLAP_CHARS = 100
EMBED_DELAY_SECS = 0.3  # Throttle to avoid hitting rate limits


def fetch_doc(repo, path: str, repo_root: str) -> str | None:
    """Fetch file content — tries GitHub first, falls back to local file."""
    try:
        file_content = repo.get_contents(path)
        return file_content.decoded_content.decode("utf-8")
    except Exception:
        # Fall back to local file (docs may not be pushed to GitHub)
        local_path = os.path.join(repo_root, path.replace("/", os.sep))
        if os.path.exists(local_path):
            with open(local_path, encoding="utf-8") as f:
                return f.read()
        print(f"  [WARN] Could not fetch {path} from GitHub or local filesystem")
        return None


def chunk_markdown(source: str, text: str) -> list[dict]:
    """
    Split markdown into chunks aligned to H2/H3 headings.

    Each chunk carries:
      source  — file path
      heading — nearest heading above the chunk
      content — chunk text (stripped, max MAX_CHUNK_CHARS chars with overlap)
    """
    heading_re = re.compile(r"^(#{2,3})\s+(.+)$", re.MULTILINE)

    # Find all heading positions
    headings = [(m.start(), m.group(2).strip()) for m in heading_re.finditer(text)]
    # Add a sentinel at the end
    headings.append((len(text), None))

    chunks = []
    current_heading = "(introduction)"

    for i, (start, heading) in enumerate(headings[:-1]):
        end = headings[i + 1][0]
        section_text = text[start:end].strip()
        if heading:
            current_heading = heading

        # Strip the heading line itself from the body
        body = heading_re.sub("", section_text, count=1).strip()
        if not body:
            continue

        # Split into sliding windows if section is large
        if len(body) <= MAX_CHUNK_CHARS:
            chunks.append({
                "source": source,
                "heading": current_heading,
                "content": body,
            })
        else:
            pos = 0
            while pos < len(body):
                chunk_text = body[pos:pos + MAX_CHUNK_CHARS].strip()
                if chunk_text:
                    chunks.append({
                        "source": source,
                        "heading": current_heading,
                        "content": chunk_text,
                    })
                if pos + MAX_CHUNK_CHARS >= len(body):
                    break
                pos += MAX_CHUNK_CHARS - OVERLAP_CHARS

    return chunks


def index_docs():
    api_key = os.getenv("OPENROUTER_API_KEY", "")
    database_url = os.getenv("DATABASE_URL", "")
    github_token = os.getenv("GITHUB_TOKEN", "")
    repo_owner = os.getenv("GITHUB_REPO_OWNER", "")
    repo_name = os.getenv("GITHUB_REPO_NAME", "")
    embedding_model = os.getenv("EMBEDDING_MODEL", "openai/text-embedding-3-small")

    if not api_key:
        print("ERROR: OPENROUTER_API_KEY not set")
        sys.exit(1)
    if not database_url:
        print("ERROR: DATABASE_URL not set")
        sys.exit(1)
    if not github_token or not repo_owner or not repo_name:
        print("ERROR: GITHUB_TOKEN, GITHUB_REPO_OWNER, GITHUB_REPO_NAME must all be set")
        sys.exit(1)

    repo_root = os.path.join(os.path.dirname(__file__), "..")

    print(f"Connecting to GitHub repo: {repo_owner}/{repo_name}")
    g = Github(github_token)
    repo = g.get_repo(f"{repo_owner}/{repo_name}")

    # Collect all chunks
    all_chunks = []
    for path in DOC_PATHS:
        print(f"Fetching {path}...")
        text = fetch_doc(repo, path, repo_root)
        if text is None:
            continue
        chunks = chunk_markdown(path, text)
        print(f"  -> {len(chunks)} chunks")
        all_chunks.extend(chunks)

    print(f"\nTotal chunks to embed: {len(all_chunks)}")

    # Embed each chunk
    print(f"Embedding with model: {embedding_model}")
    for i, chunk in enumerate(all_chunks):
        embed_input = f"[{chunk['source']} / {chunk['heading']}]\n{chunk['content']}"
        try:
            chunk["embedding"] = embed_text(embed_input, embedding_model, api_key)
        except Exception as e:
            print(f"  [WARN] Failed to embed chunk {i} ({chunk['source']}): {e}")
            chunk["embedding"] = None
        if (i + 1) % 10 == 0:
            print(f"  Embedded {i + 1} of {len(all_chunks)}...")
        time.sleep(EMBED_DELAY_SECS)

    # Store in DB (full re-index: clear then insert)
    print("\nStoring in doc_chunks table...")
    conn = get_connection(database_url)
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM doc_chunks")
            inserted = 0
            for chunk in all_chunks:
                if chunk.get("embedding") is None:
                    continue
                vec_str = "[" + ",".join(str(x) for x in chunk["embedding"]) + "]"
                cur.execute(
                    "INSERT INTO doc_chunks (source, heading, content, embedding) "
                    "VALUES (%s, %s, %s, %s::vector)",
                    (chunk["source"], chunk["heading"], chunk["content"], vec_str),
                )
                inserted += 1
        conn.commit()
        print(f"Done. Inserted {inserted} chunks into doc_chunks.")
    except Exception as e:
        conn.rollback()
        print(f"ERROR: DB insert failed: {e}")
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    index_docs()
