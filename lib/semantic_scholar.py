import re
import httpx

BATCH_URL = "https://api.semanticscholar.org/graph/v1/paper/batch"


def _arxiv_id_to_ss_id(arxiv_id: str) -> str:
    """Convert a DB paper ID (e.g. '2406.12345v1') to Semantic Scholar format ('ArXiv:2406.12345')."""
    base = re.sub(r'v\d+$', '', arxiv_id)
    return f"ArXiv:{base.replace('_', '/')}"


def fetch_citation_counts(
    arxiv_ids: list[str],
    api_key: str = None,
    timeout: int = 15,
) -> dict[str, int]:
    """Fetch citation counts from Semantic Scholar for a batch of arXiv paper IDs.

    Returns a dict mapping arxiv_id -> citation_count.
    Returns {} on any error so callers never need to handle exceptions (fail-open).
    """
    if not arxiv_ids:
        return {}

    ss_ids = [_arxiv_id_to_ss_id(aid) for aid in arxiv_ids]
    id_map = dict(zip(ss_ids, arxiv_ids))

    headers = {}
    if api_key:
        headers["x-api-key"] = api_key

    try:
        resp = httpx.post(
            BATCH_URL,
            json={"ids": ss_ids},
            params={"fields": "citationCount"},
            headers=headers,
            timeout=timeout,
        )
        if resp.status_code == 429:
            print("[semantic_scholar] rate limited, skipping citation enrichment")
            return {}
        if resp.status_code != 200:
            print(f"[semantic_scholar] API error {resp.status_code}, skipping")
            return {}

        results = {}
        for ss_id, item in zip(ss_ids, resp.json()):
            if item is None:
                continue
            citation_count = item.get("citationCount")
            if citation_count is not None:
                results[id_map[ss_id]] = citation_count
        return results
    except Exception as e:
        print(f"[semantic_scholar] fetch failed: {e}")
        return {}
