"""Demo data management: status, guarded reset of demo-generated activity, deterministic baseline.

Isolation model (the tenant also holds the real knowledge base, so deletion is by record kind, never by tenant wipe):
  demo-generated  = messages, sessions, agent events, escalations, resolutions (+ their 'resolution' vectors), resources with origin='demo-upload', demo state
  never touched   = subjects/topics, original resources + files, video segments, agent config, PDF/video vectors, eval history, original ingestion events
Vector deletion always carries tenant_id + an explicit filter (vectorstore.delete_where refuses unfiltered calls)."""
import logging
import secrets
import time
from pathlib import Path

from . import db, vectorstore
from .config import get_settings

log = logging.getLogger("doubtloop.demo")
DEMO_ORIGIN = "demo-upload"
CONFIRM_TTL_S = 120
_tokens: dict[str, float] = {}

DEMO_USERS = [("student", "demo-student", "Demo Student (demonstration data)"), ("teacher", "demo-teacher", "Demo Teacher (demonstration data)"),
              ("admin", "demo-admin", "Demo Admin (demonstration data)")]
BASELINE_QUESTIONS = [
    "Explain the difference between preemptive and non-preemptive CPU scheduling with examples.",
    "Explain that concept.",
    "How does the ext4 journaling file system recover after a crash?",
]
SEED_TICKET = {"question": "How does Linux's io_uring submission queue avoid system calls?", "topic_id": "os-process-management",
               "reason": "demo_seed: demonstration ticket pre-loaded by Demo Data Reset (it was not produced by an agent run, so it has no execution history)"}


def tenant_id() -> str:
    return get_settings().default_tenant_id


def state_get(t: str, key: str, default=None):
    r = db.row("SELECT value FROM demo_state WHERE tenant_id=? AND key=?", (t, key))
    return db.loads(r["value"], default) if r else default


def state_set(t: str, key: str, value) -> None:
    db.execute("INSERT INTO demo_state(tenant_id,key,value,updated_at) VALUES(?,?,?,?) ON CONFLICT(tenant_id,key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
               (t, key, db.dumps(value), db.now()))


def _n(sql: str, p=()) -> int:
    return (db.row(sql, p) or {}).get("n", 0)


def demo_resources(t: str) -> list[dict]:
    return db.rows("SELECT * FROM resources WHERE tenant_id=? AND origin=?", (t, DEMO_ORIGIN))


def demo_counts(t: str) -> dict:
    ids = [r["id"] for r in demo_resources(t)]
    return {
        "messages": _n("SELECT COUNT(*) n FROM messages WHERE tenant_id=?", (t,)), "sessions": _n("SELECT COUNT(*) n FROM sessions WHERE tenant_id=?", (t,)),
        "agent_events": _n("SELECT COUNT(*) n FROM agent_events WHERE tenant_id=? AND run_id NOT LIKE 'ingest-%'", (t,)),
        "escalations": _n("SELECT COUNT(*) n FROM escalations WHERE tenant_id=?", (t,)),
        "approved_answers": _n("SELECT COUNT(*) n FROM resolutions WHERE tenant_id=? AND status='approved'", (t,)),
        "memory_vectors": vectorstore.count_where(t, source_type="resolution"),
        "demo_uploaded_documents": len(ids), "demo_document_vectors": sum(vectorstore.count_where(t, source_id=i) for i in ids),
        "demo_students": _n("SELECT COUNT(DISTINCT user_id) n FROM messages WHERE tenant_id=? AND role='user'", (t,)),
    }


def preserved_counts(t: str) -> dict:
    return {
        "subjects": _n("SELECT COUNT(*) n FROM subjects WHERE tenant_id=?", (t,)), "topics": _n("SELECT COUNT(*) n FROM topics WHERE tenant_id=?", (t,)),
        "source_documents": _n("SELECT COUNT(*) n FROM resources WHERE tenant_id=? AND origin!=?", (t, DEMO_ORIGIN)),
        "video_segments": _n("SELECT COUNT(*) n FROM video_segments WHERE tenant_id=?", (t,)),
        "source_vectors": vectorstore.count_where(t, source_type=["pdf", "video"]) - sum(vectorstore.count_where(t, source_id=r["id"]) for r in demo_resources(t)),
        "source_files_on_disk": sum(1 for r in db.rows("SELECT file_path FROM resources WHERE tenant_id=? AND origin!=? AND file_path IS NOT NULL", (t, DEMO_ORIGIN)) if Path(r["file_path"]).exists()),
        "agent_config": _n("SELECT COUNT(*) n FROM agent_configs WHERE tenant_id=?", (t,)),
    }


def status(t: str) -> dict:
    last = state_get(t, "last_reset")
    c = demo_counts(t)
    return {"tenant_id": t, "last_reset": last, "counts": c, "pending_escalations": _n("SELECT COUNT(*) n FROM escalations WHERE tenant_id=? AND status='pending'", (t,)),
            "demo_users": db.rows("SELECT role,user_id,label FROM demo_users WHERE tenant_id=? ORDER BY rowid", (t,)), "baseline_questions": BASELINE_QUESTIONS,
            "preserved": preserved_counts(t), "auth": "token" if get_settings().admin_token else "local-only",
            "state": "never reset (live data from earlier use)" if not last else ("baseline + activity since reset" if c["messages"] or c["approved_answers"] else "clean baseline")}


def prepare(t: str) -> dict:
    now = time.time()
    for k in [k for k, v in _tokens.items() if v < now]:
        _tokens.pop(k, None)
    tok = secrets.token_urlsafe(16)
    _tokens[tok] = now + CONFIRM_TTL_S
    return {"confirmation_token": tok, "expires_in_s": CONFIRM_TTL_S, "will_delete": demo_counts(t), "will_preserve": preserved_counts(t),
            "will_restore": {"demo_users": [u[2] for u in DEMO_USERS], "pending_ticket": SEED_TICKET["question"], "sample_questions": BASELINE_QUESTIONS}}


class ResetError(RuntimeError):
    pass


def remove_demo_resources(t: str) -> list[str]:
    """Delete demo-uploaded documents (vectors, rows, files). Only rows with origin='demo-upload' are eligible."""
    removed = []
    for r in demo_resources(t):
        vectorstore.delete_source(t, r["id"])
        db.execute("DELETE FROM video_segments WHERE resource_id=? AND tenant_id=?", (r["id"], t))
        db.execute("DELETE FROM agent_events WHERE tenant_id=? AND session_id=? AND run_id LIKE 'ingest-%'", (t, r["id"]))
        db.execute("DELETE FROM resources WHERE id=? AND tenant_id=? AND origin=?", (r["id"], t, DEMO_ORIGIN))
        fp = Path(r["file_path"]) if r.get("file_path") else None
        if fp and fp.exists() and get_settings().upload_dir in fp.resolve().parents:
            fp.unlink()
        removed.append(r["id"])
    return removed


def reset(t: str, token: str, actor: str = "admin") -> dict:
    exp = _tokens.pop(token, 0)
    if not exp or exp < time.time():
        raise ResetError("Confirmation token is missing, expired or already used. Open the reset dialog again.")
    before_del, before_keep = demo_counts(t), preserved_counts(t)
    t0 = time.perf_counter()
    try:
        # 1) vectors first (idempotent, tenant+filter scoped). If anything later fails, SQLite still holds the data and a re-run completes the reset.
        deleted_vectors = vectorstore.delete_where(t, source_type="resolution")
        demo_ids = [r["id"] for r in demo_resources(t)]
        for rid in demo_ids:
            deleted_vectors += vectorstore.delete_where(t, source_id=rid)
        files = [r["file_path"] for r in demo_resources(t) if r.get("file_path")]
        # 2) one SQLite transaction: delete activity, restore baseline, write audit. Any exception rolls everything back.
        with db.conn() as c:
            q = lambda sql, p=(): c.execute(sql, p)
            keep0 = q("SELECT COUNT(*) FROM resources WHERE tenant_id=? AND origin!=?", (t, DEMO_ORIGIN)).fetchone()[0]
            seg0 = q("SELECT COUNT(*) FROM video_segments WHERE tenant_id=?", (t,)).fetchone()[0]
            marks = ",".join("?" * len(demo_ids)) or "''"
            q("DELETE FROM agent_events WHERE tenant_id=? AND (run_id NOT LIKE 'ingest-%'" + (f" OR session_id IN ({marks})" if demo_ids else "") + ")", (t, *demo_ids))
            q("DELETE FROM messages WHERE tenant_id=?", (t,))
            q("DELETE FROM sessions WHERE tenant_id=?", (t,))
            q("DELETE FROM resolutions WHERE tenant_id=?", (t,))
            q("DELETE FROM escalations WHERE tenant_id=?", (t,))
            if demo_ids:
                q(f"DELETE FROM video_segments WHERE tenant_id=? AND resource_id IN ({marks})", (t, *demo_ids))
            q("DELETE FROM resources WHERE tenant_id=? AND origin=?", (t, DEMO_ORIGIN))
            q("DELETE FROM demo_state WHERE tenant_id=?", (t,))
            q("DELETE FROM demo_users WHERE tenant_id=?", (t,))
            for role, uid, label in DEMO_USERS:
                q("INSERT INTO demo_users(tenant_id,role,user_id,label) VALUES(?,?,?,?)", (t, role, uid, label))
            subj = q("SELECT subject_id FROM topics WHERE id=? AND tenant_id=?", (SEED_TICKET["topic_id"], t)).fetchone()
            q("INSERT INTO escalations(tenant_id,session_id,user_id,question,standalone_question,subject_id,topic_id,reason,evidence,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
              (t, "demo-seed", "demo-student", SEED_TICKET["question"], SEED_TICKET["question"], subj[0] if subj else None, SEED_TICKET["topic_id"], SEED_TICKET["reason"], "[]", "pending", db.now()))
            if q("SELECT COUNT(*) FROM resources WHERE tenant_id=? AND origin!=?", (t, DEMO_ORIGIN)).fetchone()[0] != keep0 or q("SELECT COUNT(*) FROM video_segments WHERE tenant_id=?", (t,)).fetchone()[0] != seg0:
                raise ResetError("Safety check failed: source documents would have changed. Nothing was modified.")
        for f in files:
            fp = Path(f)
            if fp.exists() and get_settings().upload_dir in fp.resolve().parents:
                fp.unlink()
        after_keep = preserved_counts(t)
        if after_keep != before_keep:
            raise ResetError(f"Post-reset check: preserved data differs ({before_keep} -> {after_keep}).")
        result = {"ok": True, "tenant_id": t, "deleted": before_del, "deleted_vectors": deleted_vectors, "preserved_before": before_keep, "preserved_after": after_keep,
                  "restored": {"demo_users": len(DEMO_USERS), "pending_escalations": 1}, "ms": int((time.perf_counter() - t0) * 1000)}
        state_set(t, "last_reset", {"ts": db.now(), "actor": actor, "deleted": before_del})
        db.execute("INSERT INTO audit_log(tenant_id,action,actor,ok,detail,ts) VALUES(?,?,?,?,?,?)", (t, "demo_reset", actor, 1, db.dumps({k: result[k] for k in ("deleted", "deleted_vectors", "ms")}), db.now()))
        return result
    except Exception as e:
        log.warning("demo reset failed: %s", type(e).__name__)
        db.execute("INSERT INTO audit_log(tenant_id,action,actor,ok,detail,ts) VALUES(?,?,?,?,?,?)", (t, "demo_reset", actor, 0, db.dumps({"error": type(e).__name__}), db.now()))
        if isinstance(e, ResetError):
            raise
        raise ResetError(f"Reset failed and was rolled back where possible ({type(e).__name__}). Re-running the reset is safe.") from e
