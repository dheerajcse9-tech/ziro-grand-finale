"""Live + historical agent execution events (SSE stream, run history, escalation/ingestion timelines) and admin statistics."""
import json
import logging
import queue
import threading

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import StreamingResponse

from .. import db, vectorstore
from ..agent import events as ev
from ..agent.orchestrator import get_orchestrator
from ..agent.schemas import AgentRequest
from ..deps import tenant

router = APIRouter(prefix="/api/v1", tags=["monitoring"])
log = logging.getLogger("doubtloop.stream")


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


@router.post("/agent/ask/stream", summary="Same as /agent/ask, but streams real execution events (SSE) and ends with a 'final' event")
def ask_stream(req: AgentRequest, x_tenant_id: str | None = Header(default=None)):
    if x_tenant_id and x_tenant_id != req.tenant_id:
        raise HTTPException(403, "tenant_id in the body does not match the X-Tenant-ID header.")
    q: queue.Queue = queue.Queue()
    rec = ev.Recorder(req.tenant_id, ev.new_run_id(), req.session_id, sink=lambda e: q.put(("event", e)))

    def work():
        try:
            q.put(("final", get_orchestrator().ask(req, rec).model_dump()))
        except Exception as e:  # surfaced as a failed agent + an error event; the request never hangs
            log.exception("streamed run failed")
            rec.emit("agent_failed", rec.current or "orchestrator", "failed", "Run failed", error=type(e).__name__)
            q.put(("error", {"message": "The agent run failed unexpectedly. See the failed step in the activity panel."}))
        finally:
            q.put(None)

    threading.Thread(target=work, daemon=True).start()

    def gen():
        yield _sse("run", {"run_id": rec.run_id})
        while True:
            try:
                item = q.get(timeout=15)
            except queue.Empty:
                yield ": keepalive\n\n"
                continue
            if item is None:
                return
            yield _sse(*item)

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _summary(tenant_id: str, run_id: str) -> dict:
    events = ev.run_events(tenant_id, run_id)
    first = next((e for e in events if e["type"] == "run_started"), None)
    done = next((e for e in reversed(events) if e["type"] == "run_completed"), None)
    esc = next((e["escalation_id"] for e in events if e["type"] == "escalation_created"), None)
    eid = next((e["escalation_id"] for e in events if e["escalation_id"]), None)
    return {"run_id": run_id, "started_at": events[0]["ts"] if events else None, "question": first["data"].get("question") if first else (f"Teacher action on ticket #{eid}" if eid else None),
            "decision": done and done["data"].get("decision"), "confidence": done and done["data"].get("confidence"), "llm_mode": done and done["data"].get("llm_mode"),
            "total_ms": done and done["data"].get("total_ms"), "failed": any(e["status"] == "failed" for e in events),
            "fallback": any(e["type"] == "llm_call" and e["data"].get("fallback") for e in events), "escalation_id": esc, "events": len(events),
            "learned": any(e["type"] == "memory_saved" for e in events), "reused_later": any(e["type"] == "memory_reused" for e in events),
            "teacher": next((e["data"].get("decision") for e in reversed(events) if e["agent"] == "teacher" and e["data"].get("decision")), None),
            "reused_memory": any(e["type"] == "memory_retrieved" for e in events), "complete": done is not None or first is None}


@router.get("/events/runs", summary="Recent agent runs (most recent first)")
def runs(limit: int = 25, t: str = Depends(tenant)):
    ids = db.rows("SELECT run_id FROM agent_events WHERE tenant_id=? AND run_id NOT LIKE 'ingest-%' GROUP BY run_id ORDER BY MAX(id) DESC LIMIT ?", (t, min(max(limit, 1), 100)))
    return [_summary(t, r["run_id"]) for r in ids]


@router.get("/events/runs/{run_id}", summary="All events of one run")
def run(run_id: str, t: str = Depends(tenant)):
    events = ev.run_events(t, run_id)
    if not events:
        raise HTTPException(404, "Run not found.")
    return {"summary": _summary(t, run_id), "events": events}


@router.get("/escalations/{eid}/events", summary="Agent investigation history for an escalation (the run that raised it, plus teacher/memory events)")
def escalation_events(eid: int, t: str = Depends(tenant)):
    rid = ev.run_for_escalation(t, eid)
    return {"run_id": rid, "events": ev.run_events(t, rid) if rid else []}


@router.get("/ingestion/{resource_id}/events", summary="Stage events of the latest ingestion run of a resource")
def ingestion_events(resource_id: str, t: str = Depends(tenant)):
    r = db.row("SELECT run_id FROM agent_events WHERE tenant_id=? AND session_id=? AND run_id LIKE 'ingest-%' ORDER BY id DESC LIMIT 1", (t, resource_id))
    return {"run_id": r and r["run_id"], "events": ev.run_events(t, r["run_id"]) if r else []}


@router.get("/admin/stats", summary="System statistics computed from the live database and vector store")
def stats(t: str = Depends(tenant)):
    one = lambda sql, p=(): (db.row(sql, p) or {}).get("n", 0)
    res = db.rows("SELECT status, COUNT(*) n, COALESCE(SUM(chunk_count),0) chunks FROM resources WHERE tenant_id=? GROUP BY status", (t,))
    runs_ = [_summary(t, r["run_id"]) for r in db.rows("SELECT run_id FROM agent_events WHERE tenant_id=? AND run_id NOT LIKE 'ingest-%' GROUP BY run_id ORDER BY MAX(id) DESC LIMIT 200", (t,))]
    done = [r for r in runs_ if r["complete"]]
    try:
        vectors = vectorstore.count(t)
    except Exception:
        vectors = None
    return {
        "subjects": one("SELECT COUNT(*) n FROM subjects WHERE tenant_id=?", (t,)), "topics": one("SELECT COUNT(*) n FROM topics WHERE tenant_id=?", (t,)),
        "resources": {r["status"]: r["n"] for r in res}, "pdfs": one("SELECT COUNT(*) n FROM resources WHERE tenant_id=? AND type='pdf'", (t,)),
        "videos": one("SELECT COUNT(*) n FROM resources WHERE tenant_id=? AND type='video'", (t,)), "chunks": sum(r["chunks"] for r in res), "vectors": vectors,
        "segments": one("SELECT COUNT(*) n FROM video_segments WHERE tenant_id=?", (t,)),
        "escalations": {r["status"]: r["n"] for r in db.rows("SELECT status, COUNT(*) n FROM escalations WHERE tenant_id=? GROUP BY status", (t,))},
        "trusted_resolutions": one("SELECT COUNT(*) n FROM resolutions WHERE tenant_id=? AND status='approved'", (t,)),
        "active_students": one("SELECT COUNT(DISTINCT user_id) n FROM messages WHERE tenant_id=? AND role='user'", (t,)),
        "runs": {"recent_window": len(runs_), "completed": len(done), "failed": sum(r["failed"] for r in runs_), "llm_fallbacks": sum(r["fallback"] for r in runs_),
                 "by_decision": {d: sum(1 for r in done if r["decision"] == d) for d in ("ANSWER", "CLARIFY", "ESCALATE")},
                 "avg_ms": int(sum(r["total_ms"] or 0 for r in done) / len(done)) if done else None},
    }


@router.get("/resources/{resource_id}/search", summary="Semantic search restricted to one resource (proves newly ingested material is retrievable; no LLM call)")
def resource_search(resource_id: str, q: str, k: int = 3, t: str = Depends(tenant)):
    if not db.row("SELECT 1 FROM resources WHERE id=? AND tenant_id=?", (resource_id, t)):
        raise HTTPException(404, "Resource not found.")
    try:
        hits = vectorstore.query(t, q, k=min(max(k, 1), 5), source_id=resource_id)
    except Exception as e:
        raise HTTPException(503, f"Search failed: {e}")
    return [{"similarity": h["similarity"], "page": h.get("page"), "ts_start": h.get("ts_start"), "heading": h.get("heading"), "excerpt": h["text"][:260]} for h in hits]
