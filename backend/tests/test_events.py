"""Execution events: emitted by the real orchestrator/memory/ingestion code, streamed over SSE, persisted and queryable."""
import json

import pytest
from fastapi.testclient import TestClient

from app.main import app

T = "demo-university"
H = {"X-Tenant-ID": T}


@pytest.fixture(scope="module")
def c():
    with TestClient(app) as client:
        yield client


def stream(c, q, sid, **kw):
    out = {"event": [], "final": None, "run": None, "error": None}
    with c.stream("POST", "/api/v1/agent/ask/stream", json={"question": q, "tenant_id": T, "session_id": sid, **kw}, headers=H) as r:
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
        name = None
        for line in r.iter_lines():
            if line.startswith("event: "):
                name = line[7:]
            elif line.startswith("data: "):
                d = json.loads(line[6:])
                if name in ("event",):
                    out["event"].append(d)
                else:
                    out[name] = d
    return out


def test_answer_streams_real_agent_sequence(c):
    s = stream(c, "What is a race condition?", "ev-answer")
    ev = s["event"]
    assert s["run"]["run_id"] and s["final"]["decision"] == "ANSWER"
    agents = list(dict.fromkeys(e["agent"] for e in ev))
    assert agents[:5] == ["orchestrator", "understanding", "retrieval", "verification", "decision"] and "response" in agents
    tools = [e["data"]["tool"] for e in ev if e["type"] == "tool_called"]
    assert tools == ["search_solved_doubts", "search_knowledge_base"]
    ver = next(e for e in ev if e["type"] == "evidence_verified")
    assert ver["data"]["supporting"] >= 1 and ver["data"]["citations_available"] >= 1
    dec = next(e for e in ev if e["type"] == "decision_made")
    assert dec["data"]["decision"] == "ANSWER" and dec["data"]["confidence"] == s["final"]["confidence"]
    assert [e["seq"] for e in ev] == sorted(e["seq"] for e in ev) and ev[-1]["type"] == "run_completed"
    assert all("session_id" not in e and "user_id" not in json.dumps(e) for e in ev)


def test_clarify_events(c):
    ev = stream(c, "Explain it again.", "ev-clar")["event"]
    types = [e["type"] for e in ev]
    assert "clarification_requested" in types and next(e for e in ev if e["type"] == "decision_made")["data"]["decision"] == "CLARIFY"
    assert next(e for e in ev if e["agent"] == "verification")["status"] == "skipped"


def test_escalation_approval_memory_and_reuse_share_one_timeline(c):
    q = "How does the btrfs copy-on-write snapshot mechanism work?"
    s = stream(c, q, "ev-esc", user_id="stu-ev")
    assert s["final"]["decision"] == "ESCALATE"
    eid, run_id = s["final"]["escalation_id"], s["run"]["run_id"]
    assert any(e["type"] == "escalation_created" and e["escalation_id"] == eid for e in s["event"])
    assert next(e for e in s["event"] if e["agent"] == "memory")["status"] == "waiting"

    r = c.post(f"/api/v1/escalations/{eid}/approve", json={"answer": "Btrfs never overwrites blocks in place; snapshots share extents until modified.", "teacher_id": "t1"}, headers=H)
    assert r.status_code == 200 and r.json()["vector_ids"]
    got = c.get(f"/api/v1/events/runs/{run_id}", headers=H).json()
    types = [e["type"] for e in got["events"]]
    assert types.index("teacher_approval_received") < types.index("memory_saved") and got["summary"]["learned"]
    assert c.get(f"/api/v1/escalations/{eid}/events", headers=H).json()["run_id"] == run_id

    again = stream(c, q, "ev-fresh-session", user_id="stu-other")
    assert again["final"]["answered_from"] == "approved_resolution"
    assert any(e["type"] == "memory_retrieved" for e in again["event"])
    assert c.get(f"/api/v1/events/runs/{run_id}", headers=H).json()["summary"]["reused_later"]


def test_rejection_never_saves_memory(c):
    s = stream(c, "Explain the zfs ARC cache eviction policy in detail.", "ev-rej")
    eid = s["final"]["escalation_id"]
    assert eid and c.post(f"/api/v1/escalations/{eid}/reject", json={"note": "out of scope"}, headers=H).status_code == 200
    ev = c.get(f"/api/v1/escalations/{eid}/events", headers=H).json()["events"]
    assert "memory_saved" not in [e["type"] for e in ev] and "teacher_rejection_received" in [e["type"] for e in ev]


def test_runs_and_stats_endpoints(c):
    runs = c.get("/api/v1/events/runs", headers=H).json()
    assert runs and {"run_id", "decision", "failed", "escalation_id"} <= set(runs[0]) and "session_id" not in runs[0]
    st = c.get("/api/v1/admin/stats", headers=H).json()
    assert st["vectors"] > 0 and st["chunks"] > 0 and st["runs"]["completed"] >= 1


def test_ingestion_stage_events(c):
    cat = c.get("/api/v1/catalog", headers=H).json()
    rid = cat[0]["topics"][0]["resources"][0]["id"]
    c.post(f"/api/v1/resources/{rid}/reindex", headers=H)
    ev = c.get(f"/api/v1/ingestion/{rid}/events", headers=H).json()["events"]
    agents = [e["agent"] for e in ev if e["status"] in ("completed", "skipped", "failed")]
    assert agents[0] == "ingestion" and agents[-1] == "validation" and "chunking" in agents
    assert not any(e["status"] == "failed" for e in ev)
