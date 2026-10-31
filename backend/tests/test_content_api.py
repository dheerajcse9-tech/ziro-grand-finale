import io
import time

import fitz
from fastapi.testclient import TestClient

from app.main import app

H = {"X-Tenant-ID": "demo-university"}


def _pdf(text: str) -> bytes:
    d = fitz.open(); p = d.new_page(); p.insert_text((72, 72), text); b = d.tobytes(); d.close(); return b


def test_tenant_required():
    with TestClient(app) as c:
        assert c.get("/api/v1/catalog").status_code == 400


def test_catalog_has_four_topics_with_resources():
    with TestClient(app) as c:
        cat = c.get("/api/v1/catalog", headers=H).json()
        assert [t["name"] for t in cat[0]["topics"]] == ["Process Management", "CPU Scheduling", "Deadlocks", "Memory Management"]
        assert all(any(r["type"] == "pdf" for r in t["resources"]) and any(r["type"] == "video" for r in t["resources"]) for t in cat[0]["topics"])


def test_pdf_upload_validation_and_indexing():
    with TestClient(app) as c:
        bad = c.post("/api/v1/resources/pdf", headers=H, data={"subject_id": "os", "topic_id": "os-deadlocks"}, files={"file": ("x.pdf", b"not a pdf", "application/pdf")})
        assert bad.status_code == 422
        good = c.post("/api/v1/resources/pdf", headers=H, data={"subject_id": "os", "topic_id": "os-deadlocks", "title": "T"},
                      files={"file": ("n.pdf", _pdf("Livelock is when processes keep changing state without progress. " * 3), "application/pdf")})
        assert good.status_code == 200
        r = c.get("/api/v1/resources", headers=H, params={"topic_id": "os-deadlocks"}).json()
        mine = [x for x in r if x["title"] == "T"][0]
        assert mine["status"] == "indexed" and mine["chunk_count"] >= 1
        empty = c.post("/api/v1/resources/pdf", headers=H, data={"subject_id": "os", "topic_id": "os-deadlocks"}, files={"file": ("e.pdf", _pdf(" "), "application/pdf")})
        rid = empty.json()["id"]
        st = [x for x in c.get("/api/v1/resources", headers=H).json() if x["id"] == rid][0]
        assert st["status"] == "failed" and "extractable" in st["status_detail"]


def test_video_without_transcript_is_not_indexed_then_manual_transcript():
    with TestClient(app) as c:
        v = c.post("/api/v1/resources/video", headers=H, json={"subject_id": "os", "topic_id": "os-deadlocks", "url": "https://youtu.be/dQw4w9WgXcQ", "title": "Test vid"}).json()
        assert v["status"] == "no_transcript" and v["chunk_count"] == 0
        r = c.post(f"/api/v1/resources/{v['id']}/transcript", headers=H, json={"text": "[00:05] livelock example\n[00:40] more text about livelock"}).json()
        assert r["status"] == "indexed" and r["transcript_origin"] == "manual"
