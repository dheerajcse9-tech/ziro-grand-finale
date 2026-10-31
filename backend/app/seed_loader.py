"""Seeds a tenant from backend/seed/os_dataset.json (idempotent, per item). PDFs and caption files are read from git-ignored
local folders (seed/pdfs, seed/transcripts); anything missing is reported and skipped, never fabricated."""
import json
import logging

from . import content, db
from .config import BACKEND_DIR
from .ingestion.pipeline import attach_transcript, index_resource
from .ingestion.segments import import_segments

log = logging.getLogger("doubtloop.seed")
SEED_DIR = BACKEND_DIR / "seed"


def _exists(table: str, tenant_id: str, id_: str) -> bool:
    return bool(db.row(f"SELECT 1 FROM {table} WHERE id=? AND tenant_id=?", (id_, tenant_id)))


def seed_tenant(tenant_id: str, fixtures: bool = False) -> dict:
    ds = json.loads((SEED_DIR / "os_dataset.json").read_text())
    sid = ds["subject"]["id"]
    report = {"pdfs": [], "videos": [], "segments": 0, "missing_pdfs": [], "missing_captions": []}
    if not _exists("subjects", tenant_id, sid):
        content.create_subject(tenant_id, ds["subject"]["name"], ds["subject"]["description"], id=sid)
    for t in ds["topics"]:
        if not _exists("topics", tenant_id, t["id"]):
            content.create_topic(tenant_id, sid, t["name"], t["description"], t["questions"], id=t["id"])
        pdf, rid = t["pdf"], f"{tenant_id}-pdf-{t['id']}"
        path = SEED_DIR / "pdfs" / pdf["filename"]
        if _exists("resources", tenant_id, rid):
            continue
        if not path.exists():
            report["missing_pdfs"].append(pdf["filename"])
            log.warning("seed PDF missing: %s", path)
            continue
        content.create_pdf_resource(tenant_id, sid, t["id"], pdf["title"], path.read_bytes(), pdf["filename"], origin="course_pdf",
                                    attribution=f"Course PDF supplied by the course team (file: {pdf['filename']}).", id=rid)
        index_resource(rid)
        report["pdfs"].append(rid)
    for v in ds["videos"]:
        rid = f"{tenant_id}-vid-{v['youtube_id']}"
        if not _exists("resources", tenant_id, rid):
            content.create_video_resource(tenant_id, sid, v["topic_id"], f"https://www.youtube.com/watch?v={v['youtube_id']}", v["title"],
                                          attribution=f"{v['channel']} on YouTube (embedded via YouTube).", id=rid, duration_s=v.get("duration_s"))
            cap = SEED_DIR / "transcripts" / f"{v['youtube_id']}.json"
            if cap.exists():
                attach_transcript(rid, json.loads(cap.read_text()), "extracted")
            else:
                report["missing_captions"].append(v["youtube_id"])
            report["videos"].append(rid)
        r = import_segments(tenant_id, rid, v["segments"])
        report["segments"] += r["segments_total"]
    if fixtures:
        from .evaluation.fixtures import CONFLICT, INJECTION, make_pdf
        for key, f in (("injection", INJECTION), ("conflict", CONFLICT)):
            rid = f"{tenant_id}-pdf-{key}"
            if not _exists("resources", tenant_id, rid):
                content.create_pdf_resource(tenant_id, sid, f["topic_id"], f["title"], make_pdf(f["title"], f["pages"]), f"{key}.pdf", origin="fixture", id=rid)
                index_resource(rid)
    return report
