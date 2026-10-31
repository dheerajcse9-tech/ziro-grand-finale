import hashlib
import threading
from functools import lru_cache

from .config import get_settings

_model = None
_lock = threading.Lock()


class EmbeddingError(RuntimeError):
    pass


def _get_model():
    global _model
    with _lock:
        if _model is None:
            try:
                from sentence_transformers import SentenceTransformer
                _model = SentenceTransformer(get_settings().embedding_model)
            except Exception as e:  # network/model download failure
                raise EmbeddingError(f"Embedding model unavailable: {e}") from e
    return _model


def embed(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    return _get_model().encode(texts, normalize_embeddings=True, batch_size=32, show_progress_bar=False).tolist()


@lru_cache(maxsize=512)
def _embed_query_cached(text: str) -> tuple[float, ...]:
    return tuple(embed([text])[0])


def embed_query(text: str) -> list[float]:
    """Query embeddings are cached so identical questions never recompute."""
    return list(_embed_query_cached(text.strip()))


def text_hash(*parts: str) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(p.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()
