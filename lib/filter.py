from lib.embeddings import embed_text, cosine_similarity
from lib.db import get_connection


class RelevanceFilter:

    def __init__(self, topics: list[str], threshold: float, database_url: str = None,
                 api_key: str = None, embedding_model: str = None):
        self.topics = [t.lower().strip() for t in topics]
        self.threshold = threshold
        self._seed_embeddings = None
        self._database_url = database_url
        self._api_key = api_key
        self._embedding_model = embedding_model

    def score(self, abstract: str) -> tuple[float, list[str]]:
        abstract_lower = abstract.lower()

        # Stage 1: keyword hits
        keyword_hits = [t for t in self.topics if t in abstract_lower]
        if not keyword_hits:
            return 0.0, []

        # Stage 2: embedding similarity vs seed corpus
        if not self._api_key or not self._embedding_model:
            # No API key configured — keyword-only scoring
            return min(0.5 + len(keyword_hits) * 0.05, 0.9), keyword_hits

        embedding = embed_text(abstract, model=self._embedding_model, api_key=self._api_key)

        seed_embeddings = self._get_seed_embeddings()

        if not seed_embeddings:
            # No seed corpus yet — fall back to keyword-only scoring
            return min(0.5 + len(keyword_hits) * 0.05, 0.9), keyword_hits

        similarities = [cosine_similarity(embedding, s) for s in seed_embeddings]
        max_similarity = max(similarities)

        return max_similarity, keyword_hits

    def _get_seed_embeddings(self) -> list[list[float]]:
        if self._seed_embeddings is not None:
            return self._seed_embeddings

        if not self._database_url:
            return []

        conn = get_connection(self._database_url)
        with conn.cursor() as cur:
            cur.execute("SELECT embedding FROM seed_corpus")
            rows = cur.fetchall()
        conn.close()

        self._seed_embeddings = [list(row["embedding"]) for row in rows if row["embedding"]]
        return self._seed_embeddings
