"""Seeds a tenant with the Operating Systems demo dataset (idempotent)."""
import json
from pathlib import Path

import fitz

from . import content, db
from .config import BACKEND_DIR
from .ingestion.pipeline import attach_transcript, index_resource
from .os_notes import CONTRADICTION_NOTES, INJECTION_NOTES, TOPICS

SEED_DIR = BACKEND_DIR / "seed"
SUBJECT_ID = "os"


def make_pdf(title: str, pages: list[str]) -> bytes:
    doc = fitz.open()
    for text in pages:
        page = doc.new_page()
        rect = fitz.Rect(54, 54, 541, 790)
        for size in (10.5, 10, 9.5, 9):
            if page.insert_textbox(rect, text, fontsize=size, fontname="helv") >= 0:
                break
    doc.set_metadata({"title": title, "author": "DoubtLoop demo (original sample notes)"})
    data = doc.tobytes()
    doc.close()
    return data


def seed_tenant(tenant_id: str, fixtures: bool = False) -> dict:
    if db.row("SELECT 1 FROM subjects WHERE tenant_id=?", (tenant_id,)):
        return {"seeded": False}
    content.create_subject(tenant_id, "Operating Systems", "Core operating systems concepts: processes, scheduling, deadlocks and memory.", id=SUBJECT_ID)
    for t in TOPICS:
        content.create_topic(tenant_id, SUBJECT_ID, t["name"], t["description"], t["questions"], id=t["id"])
        rid = f"{tenant_id}-pdf-{t['id']}"
        content.create_pdf_resource(tenant_id, SUBJECT_ID, t["id"], t["pdf_title"], make_pdf(t["pdf_title"], t["pages"]), "notes.pdf",
                                    origin="sample", attribution="Original sample notes written for this demo (not extracted from a published source).", id=rid)
        index_resource(rid)
    for v in json.loads((SEED_DIR / "videos.json").read_text()):
        rid = f"{tenant_id}-vid-{v['youtube_id']}"
        content.create_video_resource(tenant_id, SUBJECT_ID, v["topic_id"], f"https://www.youtube.com/watch?v={v['youtube_id']}", v["title"],
                                      attribution=f"{v['channel']} on YouTube. Embedded via YouTube; captions fetched from YouTube for indexing.", id=rid)
        attach_transcript(rid, json.loads((SEED_DIR / "transcripts" / f"{v['youtube_id']}.json").read_text()), "extracted")
    if fixtures:
        for key, f in (("injection", INJECTION_NOTES), ("conflict", CONTRADICTION_NOTES)):
            rid = f"{tenant_id}-pdf-{key}"
            content.create_pdf_resource(tenant_id, SUBJECT_ID, f["topic_id"], f["title"], make_pdf(f["title"], f["pages"]), "f.pdf", origin="sample", id=rid)
            index_resource(rid)
    return {"seeded": True}
