"""Resource indexing pipeline: extract -> chunk -> embed -> store, with honest status tracking."""
import json
import logging

from .. import db, vectorstore
from ..agent.events import Recorder, new_run_id
from ..embeddings import text_hash
from .base import IngestError
from .chunking import chunk_pdf, chunk_transcript
from .pdf import PdfConnector, pdf_stats
from .transcript import StoredTranscriptConnector

log = logging.getLogger("doubtloop.ingest")
CONNECTORS = {"pdf": (PdfConnector(), chunk_pdf), "video": (StoredTranscriptConnector(), chunk_transcript)}


def set_status(rid: str, status: str, detail: str = "", **extra) -> None:
    sets = ", ".join(["status=?", "status_detail=?", "updated_at=?"] + [f"{k}=?" for k in extra])
    db.execute(f"UPDATE resources SET {sets} WHERE id=?", [status, detail, db.now(), *extra.values(), rid])


def index_resource(resource_id: str, force: bool = False) -> dict:
    r = db.row("SELECT * FROM resources WHERE id=?", (resource_id,))
    if not r:
        raise IngestError("Resource not found.")
    connector, chunker = CONNECTORS[r["type"]]
    set_status(resource_id, "processing")
    rec = Recorder(r["tenant_id"], new_run_id("ingest"), session_id=resource_id)  # session_id column holds the resource id for ingestion runs
    stage = ["ingestion"]

    def mark(agent: str, title: str, status: str = "completed", **d):
        stage[0] = agent
        rec.emit("stage_started" if status == "running" else "stage_completed", agent, status, title, **d)
    mark("ingestion", "Document Ingestion Agent", resource=r["title"], resource_type=r["type"], filename=r.get("filename"), force=force)
    try:
        mark("extraction", "Text Extraction Agent", "running")
        segs = connector.extract(r)
        mark("extraction", "Text Extraction Agent", segments=len(segs), characters=sum(len(x.text) for x in segs))
        mark("chunking", "Chunking Agent", "running")
        chunks = chunker(segs)
        if not chunks:
            raise IngestError("No text chunks were produced.")
        mark("chunking", "Chunking Agent", chunks=len(chunks))
        h = text_hash(*[c.text for c in chunks])
        if not force and r["content_hash"] == h and r["chunk_count"] == len(chunks):
            # unchanged content: do not re-embed. Verify vectors still exist.
            set_status(resource_id, "indexed", "Unchanged; embeddings reused.", chunk_count=len(chunks), content_hash=h)
            rec.emit("stage_skipped", "embedding", "skipped", "Embedding Agent", reason="Content unchanged; existing embeddings reused")
            rec.emit("stage_skipped", "indexing", "skipped", "Knowledge Indexing Agent", reason="Content unchanged")
            mark("validation", "Validation and completion", outcome="indexed", chunks=len(chunks), reused=True)
            return db.row("SELECT * FROM resources WHERE id=?", (resource_id,))
        vectorstore.delete_source(r["tenant_id"], resource_id, keep_kind="segment")
        items = []
        for i, c in enumerate(chunks):
            items.append({
                "id": f"{resource_id}:{i}",
                "text": c.text,
                "metadata": {
                    "source_id": resource_id, "source_type": r["type"], "source_name": r["title"],
                    "subject_id": r["subject_id"], "topic_id": r["topic_id"], "trust": "curated",
                    "origin": r["transcript_origin"] if r["type"] == "video" else r["origin"],
                    "kind": "chunk", "page": c.page, "heading": c.heading, "filename": r.get("filename"), "ts_start": c.start, "ts_end": c.end, "youtube_id": r["youtube_id"], "ts_status": "caption" if r["type"] == "video" else None,
                },
            })
        mark("embedding", "Embedding Agent", "running")

        def on_stage(name: str, **d):
            if name == "embedded":
                mark("embedding", "Embedding Agent", **d)
                mark("indexing", "Knowledge Indexing Agent", "running")
            else:
                mark("indexing", "Knowledge Indexing Agent", store="ChromaDB", **d)
        vectorstore.upsert(r["tenant_id"], items, on_stage=on_stage)
        detail = f"{len(chunks)} chunks indexed."
        if r["type"] == "pdf":
            st = pdf_stats(r["file_path"])
            detail = (f"{len(chunks)} chunks indexed from {st['pages']} pages. {st['images']} embedded images (diagrams, charts, worked-example figures) "
                      "are not text-searchable and were not OCR'd.")
        set_status(resource_id, "indexed", detail, chunk_count=len(chunks), content_hash=h)
        mark("validation", "Validation and completion", outcome="indexed", chunks=len(chunks), vectors_in_store=vectorstore.count(r["tenant_id"]), detail=detail)
    except Exception as e:  # never claim indexed on failure
        msg = str(e) if isinstance(e, (IngestError, vectorstore.VectorStoreError)) else f"Unexpected error: {e}"
        log.warning("indexing %s failed: %s", resource_id, msg)
        rec.emit("stage_failed", stage[0], "failed", "Ingestion failed", error=msg)
        set_status(resource_id, "failed" if r["type"] == "pdf" or r["transcript_origin"] else "no_transcript", msg)
    return db.row("SELECT * FROM resources WHERE id=?", (resource_id,))


def attach_transcript(resource_id: str, segments: list[dict], origin: str) -> dict:
    """Persist a parsed transcript for a video resource and index it."""
    from ..config import get_settings
    r = db.row("SELECT * FROM resources WHERE id=?", (resource_id,))
    if not r or r["type"] != "video":
        raise IngestError("Video resource not found.")
    d = get_settings().upload_dir / "transcripts"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{resource_id}.json"
    p.write_text(json.dumps(segments, ensure_ascii=False))
    db.execute("UPDATE resources SET file_path=?, transcript_origin=? WHERE id=?", (str(p), origin, resource_id))
    return index_resource(resource_id)
