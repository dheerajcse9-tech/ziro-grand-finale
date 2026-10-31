"""Live end-to-end check against a running backend. Usage: live_check.py phase1 | phase2 (restart the server in between)."""
import sys
import httpx

API, T = "http://localhost:8000/api/v1", "demo-university"
c = httpx.Client(headers={"X-Tenant-ID": T}, timeout=120)
Q_UNKNOWN = "How does the ext4 journaling file system recover after a crash?"
ANSWER = "ext4 journals metadata first; after a crash the kernel replays committed journal transactions to restore consistency."


def ask(q, sid):
    r = c.post(f"{API}/agent/ask", json={"question": q, "tenant_id": T, "session_id": sid, "topic_id": "os-deadlocks", "subject_id": "os", "user_id": "live1"})
    r.raise_for_status()
    r = r.json()
    print(f"  {r['decision']:9} {r['reason_code']:26} conf={r['confidence']:<5} from={r['answered_from']:<18} esc={r['escalation_id']} src={[(s['source_type'], s.get('page'), s.get('timestamp_start')) for s in r['sources']]}")
    return r


if sys.argv[1] == "phase1":
    print("1 answerable"); ask("What is a safe state in deadlock avoidance?", "live-a")
    print("2 ambiguous -> clarify -> reply"); ask("Explain it again.", "live-b"); ask("I mean the Banker's algorithm", "live-b")
    print("3 unknown -> escalation"); eid = ask(Q_UNKNOWN, "live-c")["escalation_id"]
    print("  pending ids:", [e["id"] for e in c.get(f"{API}/escalations").json()])
    print("4 approve", eid, c.post(f"{API}/escalations/{eid}/approve", json={"answer": ANSWER, "teacher_id": "prof"}).json())
else:
    print("6 similar question after restart"); r = ask("After a crash, how does ext4 journaling restore the filesystem?", "live-d")
    assert r["decision"] == "ANSWER" and r["answered_from"] == "approved_resolution" and r["answer"] == ANSWER
    print("  resolutions persisted:", len(c.get(f"{API}/resolutions").json()), "| PASS: reused after restart without new escalation")
