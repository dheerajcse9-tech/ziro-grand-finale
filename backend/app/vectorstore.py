"""ChromaDB wrapper. Every read/write is tenant-scoped: tenant_id is a required argument and always in the filter."""
import threading
import time
from typing import Any

import chromadb

from .config import get_settings
from .embeddings import embed, embed_query

COLLECTION = "doubtloop_knowledge"
_client = None
_lock = threading.Lock()


class VectorStoreError(RuntimeError):
    pass


def _collection():
    global _client
    with _lock:
        try:
            if _client is None:
                get_settings().chroma_dir.mkdir(parents=True, exist_ok=True)
                _client = chromadb.PersistentClient(path=str(get_settings().chroma_dir))
            return _client.get_or_create_collection(COLLECTION, metadata={"hnsw:space": "cosine"})
        except Exception as e:
            raise VectorStoreError(f"Vector database unavailable: {e}") from e


def _where(tenant_id: str, filters: dict[str, Any]) -> dict:
    if not tenant_id:
        raise VectorStoreError("tenant_id is required")
    conds: list[dict] = [{"tenant_id": tenant_id}]
    for k, v in filters.items():
        if v is None:
            continue
        conds.append({k: {"$in": list(v)}} if isinstance(v, (list, tuple, set)) else {k: v})
    return conds[0] if len(conds) == 1 else {"$and": conds}


def upsert(tenant_id: str, items: list[dict], on_stage=None) -> None:
    """items: {id, text, embed_text?, metadata}. tenant_id is stamped into metadata here."""
    if not items:
        return
    try:
        t0 = time.perf_counter()
        vecs = embed([i.get("embed_text", i["text"]) for i in items])
        if on_stage:
            on_stage("embedded", vectors=len(vecs), dims=len(vecs[0]) if vecs else 0, ms=int((time.perf_counter() - t0) * 1000))
        t1 = time.perf_counter()
        _collection().upsert(
            ids=[i["id"] for i in items],
            documents=[i["text"] for i in items],
            embeddings=vecs,
            metadatas=[{**{k: v for k, v in i["metadata"].items() if v is not None}, "tenant_id": tenant_id} for i in items],
        )
        if on_stage:
            on_stage("stored", ms=int((time.perf_counter() - t1) * 1000))
    except VectorStoreError:
        raise
    except Exception as e:
        raise VectorStoreError(f"Vector write failed: {e}") from e


def delete_source(tenant_id: str, source_id: str, kind: str | None = None, keep_kind: str | None = None) -> None:
    """Delete a source's vectors; optionally only one kind, or everything except `keep_kind` (e.g. keep segment vectors)."""
    try:
        w = _where(tenant_id, {"source_id": source_id, "kind": kind})
        if keep_kind:
            w = {"$and": [w, {"kind": {"$ne": keep_kind}}]}
        _collection().delete(where=w)
    except VectorStoreError:
        raise
    except Exception as e:
        raise VectorStoreError(f"Vector delete failed: {e}") from e


def delete_tenant(tenant_id: str) -> None:
    _collection().delete(where=_where(tenant_id, {}))


def query(tenant_id: str, text: str, k: int = 6, **filters: Any) -> list[dict]:
    try:
        col = _collection()
        w = _where(tenant_id, filters)
        res = col.query(query_embeddings=[embed_query(text)], n_results=k, where=w, include=["documents", "metadatas", "distances"])
    except VectorStoreError:
        raise
    except Exception as e:
        raise VectorStoreError(f"Vector search failed: {e}") from e
    out = []
    for id_, doc, meta, dist in zip(res["ids"][0], res["documents"][0], res["metadatas"][0], res["distances"][0]):
        out.append({"chunk_id": id_, "text": doc, "similarity": round(1 - dist, 4), **meta})
    return out


def count(tenant_id: str) -> int:
    return len(_collection().get(where=_where(tenant_id, {}), include=[])["ids"])
