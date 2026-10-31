"""Timestamped video-segment metadata: validate, upsert (idempotent) and index. Unverified timestamps are never cited as exact."""
from .. import db, vectorstore
from ..embeddings import text_hash
from .base import IngestError

STATUSES = {"verified", "unverified"}


def _clean(seg: dict, duration: float | None, i: int) -> dict:
    try:
        start, end = float(seg["start"]), float(seg["end"])
    except (KeyError, TypeError, ValueError):
        raise IngestError(f"Segment {i + 1}: numeric 'start' and 'end' (seconds) are required.")
    title, expl = str(seg.get("title", "")).strip(), str(seg.get("explanation", "")).strip()
    if not title or not expl:
        raise IngestError(f"Segment {i + 1}: 'title' and 'explanation' are required.")
    if not 0 <= start < end:
        raise IngestError(f"Segment {i + 1}: start must be >= 0 and less than end.")
    if duration and end > duration + 1:
        raise IngestError(f"Segment {i + 1}: end {end}s exceeds the video duration {duration}s.")
    status = str(seg.get("verification_status", "unverified")).lower()
    if status not in STATUSES:
        raise IngestError(f"Segment {i + 1}: verification_status must be one of {sorted(STATUSES)}.")
    lst = lambda k: [str(x).strip() for x in (seg.get(k) or []) if str(x).strip()]
    return {"title": title, "topic": str(seg.get("topic", "")), "subtopic": str(seg.get("subtopic", "")), "start": start, "end": end, "explanation": expl,
            "keywords": lst("keywords"), "questions": lst("questions"), "transcript_text": str(seg.get("transcript_text", "")), "verification": status}


def import_segments(tenant_id: str, resource_id: str, segments: list[dict]) -> dict:
    r = db.row("SELECT * FROM resources WHERE id=? AND tenant_id=? AND type='video'", (resource_id, tenant_id))
    if not r:
        raise IngestError("Video resource not found.")
    if not segments:
        raise IngestError("No segments supplied.")
    clean = [_clean(s, r["duration_s"], i) for i, s in enumerate(segments)]
    for c in clean:  # upsert keyed on (resource, start, end): re-import never duplicates
        h = text_hash(c["title"], c["topic"], c["subtopic"], c["explanation"], *c["keywords"], *c["questions"], c["transcript_text"], c["verification"])
        db.execute("""INSERT INTO video_segments(tenant_id,resource_id,title,topic,subtopic,start_s,end_s,explanation,keywords,questions,transcript_text,verification,content_hash)
                      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(resource_id,start_s,end_s) DO UPDATE SET title=excluded.title, topic=excluded.topic, subtopic=excluded.subtopic,
                      explanation=excluded.explanation, keywords=excluded.keywords, questions=excluded.questions, transcript_text=excluded.transcript_text,
                      verification=excluded.verification, content_hash=excluded.content_hash""",
                   (tenant_id, resource_id, c["title"], c["topic"], c["subtopic"], c["start"], c["end"], c["explanation"], db.dumps(c["keywords"]), db.dumps(c["questions"]), c["transcript_text"], c["verification"], h))
    return index_segments(tenant_id, resource_id)


def index_segments(tenant_id: str, resource_id: str) -> dict:
    """Embed only segments whose content changed since last indexing."""
    r = db.row("SELECT * FROM resources WHERE id=? AND tenant_id=?", (resource_id, tenant_id))
    todo = db.rows("SELECT * FROM video_segments WHERE resource_id=? AND tenant_id=? AND (indexed_hash IS NULL OR indexed_hash!=content_hash)", (resource_id, tenant_id))
    items = []
    for s in todo:
        kw, qs = db.loads(s["keywords"], []), db.loads(s["questions"], [])
        text = f"{s['title']}. {s['explanation']}" + (f" Keywords: {', '.join(kw)}." if kw else "") + (f" Related questions: {' '.join(qs)}" if qs else "") + (f"\n{s['transcript_text']}" if s["transcript_text"] else "")
        items.append({"id": f"{resource_id}:seg:{s['id']}", "text": text, "metadata": {
            "source_id": resource_id, "source_type": "video", "source_name": r["title"], "subject_id": r["subject_id"], "topic_id": r["topic_id"], "trust": "curated",
            "origin": "segment_metadata", "kind": "segment", "segment_title": s["title"], "ts_start": s["start_s"], "ts_end": s["end_s"],
            "ts_verified": s["verification"] == "verified", "youtube_id": r["youtube_id"]}})
    try:
        vectorstore.upsert(tenant_id, items)
    except vectorstore.VectorStoreError as e:
        raise IngestError(str(e))
    for s in todo:
        db.execute("UPDATE video_segments SET indexed_hash=content_hash WHERE id=?", (s["id"],))
    total = db.row("SELECT COUNT(*) n FROM video_segments WHERE resource_id=?", (resource_id,))["n"]
    return {"resource_id": resource_id, "segments_total": total, "segments_embedded": len(todo), "segments_reused": total - len(todo)}
