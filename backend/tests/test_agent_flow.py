"""End-to-end agent workflow against the real retrieval stack (local-demo LLM mode, isolated temp DB)."""
import pytest
from fastapi.testclient import TestClient

from app.agent.domain import DomainConfig
from app.agent.tools import ToolContext, call_tool
from app.main import app

T = "demo-university"
H = {"X-Tenant-ID": T}


@pytest.fixture(scope="module")
def c():
    with TestClient(app) as client:
        yield client


def ask(c, q, sid, tenant=T, **kw):
    r = c.post("/api/v1/agent/ask", json={"question": q, "tenant_id": tenant, "session_id": sid, **kw}, headers={"X-Tenant-ID": tenant})
    assert r.status_code == 200, r.text
    return r.json()


def test_answer_with_page_citation(c):
    r = ask(c, "What is the convoy effect in FCFS scheduling?", "s-answer")
    assert r["decision"] == "ANSWER" and r["answered_from"] == "evidence" and r["confidence"] > 0.5
    pdf = [s for s in r["sources"] if s["source_type"] == "pdf"]
    assert pdf and pdf[0]["page"] == 1 and "CPU Scheduling" in pdf[0]["source_name"]


def test_video_citation_has_timestamps(c):
    r = ask(c, "What are the four necessary conditions for deadlock?", "s-video")
    assert r["decision"] == "ANSWER"
    v = [s for s in r["sources"] if s["source_type"] == "video"]
    assert v and v[0]["timestamp_end"] > v[0]["timestamp_start"] >= 0 and f"t={int(v[0]['timestamp_start'])}" in v[0]["url"]


def test_clarify_then_continue_same_workflow(c):
    r = ask(c, "Explain it again.", "s-clar")
    assert r["decision"] == "CLARIFY" and r["clarification_question"]
    r2 = ask(c, "I mean the thrashing in virtual memory", "s-clar")
    assert r2["decision"] == "ANSWER" and any(s["source_type"] == "pdf" for s in r2["sources"])
    assert any("Explain it again" in st["detail"] for st in r2["trace"] if st["step"] == "understand")


def test_escalate_approve_reuse_and_persistence(c):
    q = "How does the ext4 journaling file system recover after a crash?"
    r = ask(c, q, "s-esc", user_id="stu1")
    assert r["decision"] == "ESCALATE" and r["escalation_id"] and not r["answer"] and not r["sources"]
    eid = r["escalation_id"]
    assert ask(c, q, "s-esc", user_id="stu1")["escalation_id"] == eid  # no duplicate ticket
    assert eid in [e["id"] for e in c.get("/api/v1/escalations", headers=H).json()]
    assert c.get("/api/v1/resolutions", headers=H).json() == []  # unapproved is never trusted memory
    assert ask(c, "ext4 journaling crash recovery explained", "s-other")["decision"] == "ESCALATE"
    ans = "ext4 writes metadata changes to a journal first; after a crash the kernel replays committed journal transactions, so the file system returns to a consistent state."
    assert c.post(f"/api/v1/escalations/{eid}/approve", headers=H, json={"answer": ans, "teacher_id": "prof"}).status_code == 200
    assert c.post(f"/api/v1/escalations/{eid}/approve", headers=H, json={"answer": ans}).status_code == 409
    before = len(c.get("/api/v1/escalations?status=all", headers=H).json())
    r2 = ask(c, "After a crash, how does ext4 journaling restore the filesystem?", "s-reuse")
    assert r2["decision"] == "ANSWER" and r2["answered_from"] == "approved_resolution" and r2["answer"] == ans
    assert r2["sources"][0]["trust"] == "teacher_approved"
    assert len(c.get("/api/v1/escalations?status=all", headers=H).json()) == before
    d = c.get("/api/v1/doubts", headers=H, params={"user_id": "stu1"}).json()
    assert d[0]["escalation"]["status"] == "approved" and d[0]["solved"]


def test_reject_does_not_create_memory(c):
    r = ask(c, "Explain the quantum entanglement of photons", "s-rej")
    eid = r["escalation_id"]
    assert c.post(f"/api/v1/escalations/{eid}/reject", headers=H, json={"note": "off-topic"}).status_code == 200
    n = len(c.get("/api/v1/resolutions", headers=H).json())
    assert ask(c, "Explain the quantum entanglement of photons", "s-rej2")["decision"] == "ESCALATE"
    assert len(c.get("/api/v1/resolutions", headers=H).json()) == n


def test_tenant_isolation(c):
    r = ask(c, "What is the convoy effect in FCFS scheduling?", "s-iso", tenant="other-school")
    assert r["decision"] == "ESCALATE" and r["reason_code"] == "no_evidence"
    eid = ask(c, "Some unknown thing about zebras", "s-iso2", tenant="other-school")["escalation_id"]
    assert c.post(f"/api/v1/escalations/{eid}/approve", headers=H, json={"answer": "A long enough answer here."}).status_code == 404
    assert c.get("/api/v1/escalations", headers={"X-Tenant-ID": "other-school"}).json()[0]["id"] == eid
    assert c.post("/api/v1/agent/ask", headers=H, json={"question": "x", "tenant_id": "other-school", "session_id": "z"}).status_code == 403


def test_agent_cannot_call_human_only_tool_and_validation(c):
    ctx = ToolContext(T, DomainConfig(), "s")
    res = call_tool("save_approved_resolution", ctx, escalation_id=1, answer="x" * 20, teacher_id="agent")
    assert not res.ok and "human approval" in res.error
    assert c.post("/api/v1/agent/ask", json={"question": "", "tenant_id": T, "session_id": "s"}).status_code == 422
