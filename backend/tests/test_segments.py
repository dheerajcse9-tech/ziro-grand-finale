"""Segment-metadata ingestion. Records below are clearly labelled PLACEHOLDERS for testing, not real lecture data."""
from fastapi.testclient import TestClient

from app.main import app

H = {"X-Tenant-ID": "demo-university"}
SEG = {"title": "[PLACEHOLDER] Livelock vs deadlock", "start": 10, "end": 60, "explanation": "PLACEHOLDER: livelock means processes keep changing state in response to each other without making progress, unlike deadlock where they are blocked.",
       "keywords": ["livelock"], "questions": ["What is livelock?"], "verification_status": "verified"}


def test_segments_import_idempotent_reuse_and_citation_rules():
    with TestClient(app) as c:
        v = c.post("/api/v1/resources/video", headers=H, json={"subject_id": "os", "topic_id": "os-deadlocks", "url": "https://youtu.be/dQw4w9WgXcQ", "title": "PLACEHOLDER video", "duration_s": 100}).json()
        assert c.post(f"/api/v1/resources/{v['id']}/segments", headers=H, json=[{**SEG, "end": 500}]).status_code == 422  # beyond duration
        r1 = c.post(f"/api/v1/resources/{v['id']}/segments", headers=H, json=[SEG, {**SEG, "title": "[PLACEHOLDER] Starvation vs livelock", "start": 70, "end": 90, "verification_status": "unverified",
                    "explanation": "PLACEHOLDER: zorblax quintessence frobnication means a widget wibbles when the flange is unspooled.", "keywords": ["zorblax"], "questions": []}]).json()
        assert r1["segments_total"] == 2 and r1["segments_embedded"] == 2
        r2 = c.post(f"/api/v1/resources/{v['id']}/segments", headers=H, json=[SEG]).json()  # unchanged -> nothing re-embedded, no duplicates
        assert r2["segments_total"] == 2 and r2["segments_embedded"] == 0
        assert len(c.get(f"/api/v1/resources/{v['id']}/segments", headers=H).json()) == 2
        ask = lambda q, s: c.post("/api/v1/agent/ask", headers=H, json={"question": q, "tenant_id": "demo-university", "session_id": s}).json()
        a = ask("What is livelock and how does it differ from deadlock?", "seg1")
        vid = [s for s in a["sources"] if s["source_id"] == v["id"]]
        assert a["decision"] == "ANSWER" and vid and vid[0]["timestamp_start"] == 10 and "t=10" in vid[0]["url"]  # verified -> exact link
        b = ask("What does zorblax quintessence frobnication mean?", "seg2")
        ub = [s for s in b["sources"] if s["source_id"] == v["id"]]
        # user-supplied/unverified timestamps are still linkable but explicitly flagged, never presented as verified
        assert ub and ub[0]["timestamp_start"] == 70 and "t=70" in ub[0]["url"] and ub[0]["timestamp_status"] == "unverified"
        assert vid[0]["timestamp_status"] == "verified"
