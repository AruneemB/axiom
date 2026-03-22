import numpy as np

_model = None
_model_attempted = False


def _get_model():
    global _model, _model_attempted
    if _model is not None:
        return _model
    if _model_attempted:
        return None
    _model_attempted = True
    try:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer("all-MiniLM-L6-v2")
    except ImportError:
        _model = None
    return _model


def embed_text(text: str) -> list[float] | None:
    model = _get_model()
    if model is None:
        return None
    embedding = model.encode(text, normalize_embeddings=True)
    return embedding.tolist()


def cosine_similarity(a: list[float], b: list[float]) -> float:
    a_arr = np.array(a)
    b_arr = np.array(b)
    return float(np.dot(a_arr, b_arr) / (np.linalg.norm(a_arr) * np.linalg.norm(b_arr)))
