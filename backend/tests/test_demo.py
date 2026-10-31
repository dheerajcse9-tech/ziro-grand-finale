"""Demo reset safety + the full jury scenario suite against the real stack (local-demo LLM mode, isolated temp DB)."""
import pytest
from fastapi.testclient import TestClient

from app import db, vectorstore
from app.main import app

T = "demo-university"
H = {"X-Tenant-ID": T}


@pytest.fixture(scope="module")
def c():
    with TestClient(app) as client:
        yield client


def do_reset(c):
    p = c.post("/api/v1/demo/reset/prepare", headers=H)
    assert p.status_code == 200, p.text
    r = c.post("/api/v1/demo/reset", json={"confirmation_token": p.json()["confirmation_token"], "confirm": True}, headers=H)
    assert r.status_code == 200, r.text
    return p.json(), r.json()


def test_reset_requires_confirmation_and_demo_tenant(c):
    p = c.post("/api/v1/demo/reset/prepare", headers=H).json()
    assert c.post("/api/v1/demo/reset", json={"confirmation_token": p["confirmation_token"], "confirm": False}, headers=H).status_code == 400
    assert c.post("/api/v1/demo/reset", json={"confirmation_token": "bogus", "confirm": True}, headers=H).status_code == 409
    assert c.get("/api/v1/demo/status", headers={"X-Tenant-ID": "other-tenant"}).status_code == 403
    assert c.post("/api/v1/demo/reset/prepare", headers={"X-Tenant-ID": "eval-tenant"}).status_code == 403
    # a valid token is single-use
    ok = c.post("/api/v1/demo/reset", json={"confirmation_token": p["confirmation_token"], "confirm": True}, headers=H)
    assert ok.status_code == 200
    assert c.post("/api/v1/demo/reset", json={"confirmation_token": p["confirmation_token"], "confirm": True}, headers=H).status_code == 409


def test_admin_token_enforced_when_configured(c, monkeypatch):
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), "admin_token", "s3cret")
    assert c.get("/api/v1/demo/status", headers=H).status_code == 401
    assert c.get("/api/v1/demo/status", headers={**H, "X-Admin-Token": "wrong"}).status_code == 401
    r = c.get("/api/v1/demo/status", headers={**H, "X-Admin-Token": "s3cret"})
    assert r.status_code == 200 and "s3cret" not in r.text


def test_reset_deletes_demo_activity_but_preserves_source_knowledge(c):
    keep0 = c.get("/api/v1/demo/status", headers=H).json()["preserved"]
    assert keep0["source_documents"] >= 10 and keep0["source_vectors"] > 100 and keep0["source_files_on_disk"] >= 5
    # generate real activity: an answered doubt, an escalation approved into memory, a demo PDF upload
    for n in (1, 3, 4, 7):
        assert c.post(f"/api/v1/demo/tests/{n}/run", headers=H).status_code == 200
    st = c.get("/api/v1/demo/status", headers=H).json()
    assert st["counts"]["approved_answers"] == 1 and st["counts"]["memory_vectors"] == 2 and st["counts"]["demo_uploaded_documents"] == 1
    prep, res = do_reset(c)
    assert prep["will_delete"]["approved_answers"] == 1 and res["deleted"]["memory_vectors"] == 2
    after = c.get("/api/v1/demo/status", headers=H).json()
    assert after["preserved"] == keep0 == res["preserved_after"]  # source docs, files, segments, source vectors, config untouched
    assert after["counts"]["messages"] == 0 and after["counts"]["agent_events"] == 0 and after["counts"]["approved_answers"] == 0
    assert after["counts"]["memory_vectors"] == 0 and after["counts"]["demo_uploaded_documents"] == 0 and after["counts"]["demo_document_vectors"] == 0
    assert after["counts"]["escalations"] == 1 and after["pending_escalations"] == 1
    assert [u["role"] for u in after["demo_users"]] == ["student", "teacher", "admin"] and all("demonstration data" in u["label"] for u in after["demo_users"])
    assert db.row("SELECT 1 FROM audit_log WHERE action='demo_reset' AND ok=1")
    # the seeded ticket is honestly labelled and has no fake execution history
    esc = c.get("/api/v1/escalations?status=pending", headers=H).json()
    assert esc[0]["reason"].startswith("demo_seed") and c.get(f"/api/v1/escalations/{esc[0]['id']}/events", headers=H).json()["events"] == []
    # original knowledge still answers
    r = c.post("/api/v1/agent/ask", json={"question": "What is a race condition?", "tenant_id": T, "session_id": "after-reset"}, headers=H).json()
    assert r["decision"] == "ANSWER" and any(s["source_type"] == "pdf" for s in r["sources"])


def test_reset_is_idempotent_and_unfiltered_vector_delete_refused(c):
    _, a = do_reset(c)
    s1 = c.get("/api/v1/demo/status", headers=H).json()
    _, b = do_reset(c)
    s2 = c.get("/api/v1/demo/status", headers=H).json()
    assert s1["counts"] == s2["counts"] and s1["preserved"] == s2["preserved"] and b["deleted"]["escalations"] == 1
    with pytest.raises(vectorstore.VectorStoreError):
        vectorstore.delete_where(T)
    with pytest.raises(vectorstore.VectorStoreError):
        vectorstore.delete_where(T, source_id=None)


def test_failed_reset_rolls_back_database(c, monkeypatch):
    from app import demo
    do_reset(c)
    c.post("/api/v1/demo/tests/1/run", headers=H)
    before = c.get("/api/v1/demo/status", headers=H).json()["counts"]
    monkeypatch.setattr(demo, "SEED_TICKET", {**demo.SEED_TICKET, "question": None})  # NOT NULL violation inside the transaction
    p = c.post("/api/v1/demo/reset/prepare", headers=H).json()
    r = c.post("/api/v1/demo/reset", json={"confirmation_token": p["confirmation_token"], "confirm": True}, headers=H)
    assert r.status_code == 409 and "rolled back" in r.json()["detail"]
    assert c.get("/api/v1/demo/status", headers=H).json()["counts"]["messages"] == before["messages"] > 0  # nothing half-deleted
    assert db.row("SELECT 1 FROM audit_log WHERE action='demo_reset' AND ok=0")
    monkeypatch.undo()
    do_reset(c)


def test_full_jury_suite_passes_end_to_end(c):
    do_reset(c)
    defs = c.get("/api/v1/demo/tests", headers=H).json()["tests"]
    assert [d["id"] for d in defs] == list(range(1, 11))
    fails = []
    for n in range(1, 11):
        res = c.post(f"/api/v1/demo/tests/{n}/run", headers=H)
        assert res.status_code == 200, res.text
        j = res.json()
        if j["status"] != "pass":
            fails.append((n, [k for k in j["checks"] if not k["ok"]]))
    assert not fails, fails
    stored = c.get("/api/v1/demo/tests", headers=H).json()["results"]
    assert len(stored) == 10 and all(v["status"] == "pass" for v in stored.values())
    do_reset(c)
