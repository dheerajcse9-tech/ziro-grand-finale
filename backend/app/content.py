"""Content service: subjects, topics, resources (shared by the API routers and the seed loader)."""
import re
import uuid
from pathlib import Path

import httpx

from . import db
from .config import get_settings
from .ingestion.base import IngestError
from .ingestion.pdf import validate_pdf_bytes

YT_RE = re.compile(r"(?:youtu\.be/|youtube\.com/(?:watch\?(?:.*&)?v=|embed/|shorts/|live/))([A-Za-z0-9_-]{11})")


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def parse_youtube_id(url: str) -> str:
    m = YT_RE.search(url.strip())
    if not m:
        raise IngestError("Not a valid YouTube video URL.")
    return m.group(1)


def youtube_title(video_id: str) -> str | None:
    try:
        r = httpx.get("https://www.youtube.com/oembed", params={"url": f"https://www.youtube.com/watch?v={video_id}", "format": "json"}, timeout=6)
        return r.json().get("title") if r.status_code == 200 else None
    except Exception:
        return None


def create_subject(tenant_id: str, name: str, description: str = "", id: str | None = None) -> dict:
    sid = id or new_id("subj")
    db.execute("INSERT INTO subjects(id,tenant_id,name,description,created_at) VALUES(?,?,?,?,?)", (sid, tenant_id, name, description, db.now()))
    return db.row("SELECT * FROM subjects WHERE id=? AND tenant_id=?", (sid, tenant_id))


def create_topic(tenant_id: str, subject_id: str, name: str, description: str = "", sample_questions: list[str] | None = None, id: str | None = None) -> dict:
    if not db.row("SELECT 1 FROM subjects WHERE id=? AND tenant_id=?", (subject_id, tenant_id)):
        raise IngestError("Subject not found for this tenant.")
    tid = id or new_id("topic")
    pos = db.row("SELECT COUNT(*) n FROM topics WHERE subject_id=?", (subject_id,))["n"]
    db.execute("INSERT INTO topics(id,tenant_id,subject_id,name,description,position,sample_questions,created_at) VALUES(?,?,?,?,?,?,?,?)",
               (tid, tenant_id, subject_id, name, description, pos, db.dumps(sample_questions or []), db.now()))
    return get_topic(tenant_id, tid)


def get_topic(tenant_id: str, topic_id: str) -> dict | None:
    t = db.row("SELECT * FROM topics WHERE id=? AND tenant_id=?", (topic_id, tenant_id))
    if t:
        t["sample_questions"] = db.loads(t["sample_questions"], [])
    return t


def _check_topic(tenant_id: str, subject_id: str, topic_id: str) -> None:
    if not db.row("SELECT 1 FROM topics WHERE id=? AND subject_id=? AND tenant_id=?", (topic_id, subject_id, tenant_id)):
        raise IngestError("Topic not found under that subject for this tenant.")


def create_pdf_resource(tenant_id: str, subject_id: str, topic_id: str, title: str, data: bytes, filename: str,
                        origin: str = "uploaded", attribution: str = "", id: str | None = None) -> dict:
    _check_topic(tenant_id, subject_id, topic_id)
    validate_pdf_bytes(data, filename)
    rid = id or new_id("pdf")
    d = get_settings().upload_dir / "pdf"
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{rid}.pdf"
    path.write_bytes(data)
    db.execute("INSERT INTO resources(id,tenant_id,subject_id,topic_id,type,title,file_path,origin,attribution,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
               (rid, tenant_id, subject_id, topic_id, "pdf", title, str(path), origin, attribution, "pending", db.now(), db.now()))
    return db.row("SELECT * FROM resources WHERE id=?", (rid,))


def create_video_resource(tenant_id: str, subject_id: str, topic_id: str, url: str, title: str | None = None,
                          attribution: str = "", id: str | None = None, duration_s: float | None = None) -> dict:
    _check_topic(tenant_id, subject_id, topic_id)
    vid = parse_youtube_id(url)
    title = title or youtube_title(vid) or f"YouTube video {vid}"
    rid = id or new_id("vid")
    db.execute("INSERT INTO resources(id,tenant_id,subject_id,topic_id,type,title,url,youtube_id,origin,attribution,status,status_detail,created_at,updated_at,duration_s) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
               (rid, tenant_id, subject_id, topic_id, "video", title, f"https://www.youtube.com/watch?v={vid}", vid, "youtube", attribution,
                "no_transcript", "Video embedded; no transcript indexed yet, so the agent cannot cite it.", db.now(), db.now(), duration_s))
    return db.row("SELECT * FROM resources WHERE id=?", (rid,))


def public_resource(r: dict) -> dict:
    return {k: r[k] for k in ("id", "subject_id", "topic_id", "type", "title", "url", "youtube_id", "origin", "transcript_origin",
                              "attribution", "status", "status_detail", "chunk_count", "duration_s")} | {
        "file_url": f"/api/v1/resources/{r['id']}/file" if r["type"] == "pdf" else None}


def list_resources(tenant_id: str, topic_id: str | None = None) -> list[dict]:
    q, p = "SELECT * FROM resources WHERE tenant_id=?", [tenant_id]
    if topic_id:
        q, p = q + " AND topic_id=?", p + [topic_id]
    return [public_resource(r) for r in db.rows(q + " ORDER BY type DESC, created_at", p)]


def catalog(tenant_id: str) -> list[dict]:
    subjects = db.rows("SELECT * FROM subjects WHERE tenant_id=? ORDER BY created_at", (tenant_id,))
    for s in subjects:
        s["topics"] = db.rows("SELECT * FROM topics WHERE subject_id=? AND tenant_id=? ORDER BY position", (s["id"], tenant_id))
        for t in s["topics"]:
            t["sample_questions"] = db.loads(t["sample_questions"], [])
            t["resources"] = list_resources(tenant_id, t["id"])
    return subjects
