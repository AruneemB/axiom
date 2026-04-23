import httpx
import numpy as np

OPENROUTER_BASE = "https://openrouter.ai/api/v1"


def embed_text(text: str, model: str, api_key: str) -> list[float]:
    response = httpx.post(
        f"{OPENROUTER_BASE}/embeddings",
        headers={
            "Authorization": f"Bearer {api_key}",
            "HTTP-Referer": "https://axiom.app",
            "X-Title": "Axiom",
        },
        json={
            "model": model,
            "input": text,
        },
        timeout=30,
    )
    response.raise_for_status()
    return response.json()["data"][0]["embedding"]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    a_arr = np.array(a)
    b_arr = np.array(b)
    return float(np.dot(a_arr, b_arr) / (np.linalg.norm(a_arr) * np.linalg.norm(b_arr)))


def retrieve_doc_chunks(
    query: str,
    conn,
    api_key: str,
    model: str,
    top_k: int = 3,
) -> list[dict]:
    """Return the top-k doc_chunks most similar to query, ordered by cosine similarity."""
    embedding = embed_text(query, model, api_key)
    vec_str = "[" + ",".join(str(x) for x in embedding) + "]"
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT source, heading, content,
                   1 - (embedding <=> %s::vector) AS similarity
            FROM doc_chunks
            ORDER BY embedding <=> %s::vector
            LIMIT %s
            """,
            (vec_str, vec_str, top_k),
        )
        rows = cur.fetchall()
    return [
        {
            "source": r["source"],
            "heading": r["heading"],
            "content": r["content"],
            "similarity": float(r["similarity"]),
        }
        for r in rows
    ]
