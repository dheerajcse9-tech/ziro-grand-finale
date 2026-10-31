"""Structured execution events. Emitted by the real orchestrator/memory/ingestion code, persisted to SQLite (audit + monitoring)
and optionally pushed to a live sink (SSE). No event is synthesised: every one is recorded at the point the operation happens."""
import logging
import threading
import time
import uuid
from typing import Any, Callable

from .. import db

log = logging.getLogger("doubtloop.events")
_lock = threading.Lock()


def new_run_id(prefix: str = "run") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


class Recorder:
    def __init__(self, tenant_id: str, run_id: str | None = None, session_id: str | None = None, sink: Callable[[dict], None] | None = None):
        self.tenant_id, self.run_id, self.session_id, self.sink = tenant_id, run_id or new_run_id(), session_id, sink
        self.t0 = time.perf_counter()
        self.current: str | None = None  # agent currently running (used to attribute an unexpected failure)
        try:
            r = db.row("SELECT MAX(seq) m FROM agent_events WHERE tenant_id=? AND run_id=?", (tenant_id, self.run_id))
            self.seq = (r["m"] or 0) if r else 0
        except Exception:
            self.seq = 0

    def emit(self, type: str, agent: str, status: str = "completed", title: str = "", escalation_id: int | None = None, **data: Any) -> dict:
        """status: running | completed | failed | waiting | skipped."""
        with _lock:
            self.seq += 1
            ev = {"run_id": self.run_id, "seq": self.seq, "ts": db.now(), "t_ms": int((time.perf_counter() - self.t0) * 1000),
                  "type": type, "agent": agent, "status": status, "title": title, "escalation_id": escalation_id, "data": data}
        if status == "running":
            self.current = agent
        try:
            db.execute("INSERT INTO agent_events(tenant_id,run_id,session_id,seq,ts,t_ms,type,agent,status,title,escalation_id,data) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                       (self.tenant_id, self.run_id, self.session_id, ev["seq"], ev["ts"], ev["t_ms"], type, agent, status, title, escalation_id, db.dumps(data)))
        except Exception as e:  # observability must never break the agent
            log.warning("could not persist event %s: %s", type, e)
        if self.sink:
            try:
                self.sink(ev)
            except Exception:
                pass
        return ev


def load(row: dict) -> dict:
    return {**row, "data": db.loads(row.get("data"), {})}


def run_events(tenant_id: str, run_id: str) -> list[dict]:
    return [load(r) for r in db.rows("SELECT run_id,seq,ts,t_ms,type,agent,status,title,escalation_id,data FROM agent_events WHERE tenant_id=? AND run_id=? ORDER BY seq", (tenant_id, run_id))]


def run_for_escalation(tenant_id: str, escalation_id: int) -> str | None:
    r = db.row("SELECT run_id FROM agent_events WHERE tenant_id=? AND type='escalation_created' AND escalation_id=? ORDER BY id DESC LIMIT 1", (tenant_id, escalation_id))
    return r["run_id"] if r else None
