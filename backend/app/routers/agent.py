from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from .. import db
from ..agent import memory
from ..agent.domain import DomainConfig, load_config, save_config
from ..agent.orchestrator import get_orchestrator
from ..agent.schemas import AgentRequest, AgentResponse
from ..deps import tenant

router = APIRouter(prefix="/api/v1", tags=["agent"])


class ApproveIn(BaseModel):
    answer: str = Field(min_length=10, max_length=5000, description="Teacher's verified answer; becomes trusted memory")
    teacher_id: str = Field(default="teacher", max_length=64)


class RejectIn(BaseModel):
    note: str = Field(default="", max_length=1000)
    teacher_id: str = Field(default="teacher", max_length=64)


def _esc(e: dict) -> dict:
    e["evidence"] = db.loads(e["evidence"], [])
    return e


@router.post("/agent/ask", response_model=AgentResponse, summary="Ask the agent (answer, clarify or escalate)")
def ask(req: AgentRequest, x_tenant_id: str | None = Header(default=None)):
    if x_tenant_id and x_tenant_id != req.tenant_id:
        raise HTTPException(403, "tenant_id in the body does not match the X-Tenant-ID header.")
    return get_orchestrator().ask(req)


@router.get("/escalations", summary="List escalations for human review")
def list_escalations(status: Literal["pending", "approved", "rejected", "resolved", "all"] = "pending", t: str = Depends(tenant)):
    cond = {"all": "", "resolved": " AND status!='pending'"}.get(status, " AND status=?")
    params = [t] + ([status] if cond.endswith("?") else [])
    return [_esc(e) for e in db.rows(f"SELECT * FROM escalations WHERE tenant_id=?{cond} ORDER BY COALESCE(resolved_at, created_at) DESC", params)]


@router.get("/escalations/{eid}")
def get_escalation(eid: int, t: str = Depends(tenant)):
    e = db.row("SELECT * FROM escalations WHERE id=? AND tenant_id=?", (eid, t))
    if not e:
        raise HTTPException(404, "Escalation not found.")
    return _esc(e)


@router.post("/escalations/{eid}/approve", summary="Teacher approves an answer; it is saved to trusted memory and indexed")
def approve(eid: int, body: ApproveIn, t: str = Depends(tenant)):
    try:
        return memory.approve(t, eid, body.answer, body.teacher_id)
    except memory.ApprovalError as e:
        raise HTTPException(404 if "not found" in str(e) else 409, str(e))


@router.post("/escalations/{eid}/reject", summary="Teacher rejects/closes an escalation; nothing enters trusted memory")
def reject(eid: int, body: RejectIn, t: str = Depends(tenant)):
    try:
        return memory.reject(t, eid, body.teacher_id, body.note)
    except memory.ApprovalError as e:
        raise HTTPException(404 if "not found" in str(e) else 409, str(e))


@router.get("/resolutions", summary="Teacher-approved solved doubts (trusted memory)")
def resolutions(t: str = Depends(tenant)):
    return db.rows("SELECT id, escalation_id, question, answer, subject_id, topic_id, approved_by, created_at FROM resolutions WHERE tenant_id=? AND status='approved' ORDER BY created_at DESC", (t,))


@router.get("/doubts", summary="A user's asked doubts with their current status")
def doubts(user_id: str, topic_id: str | None = None, t: str = Depends(tenant)):
    msgs = db.rows("SELECT * FROM messages WHERE tenant_id=? AND user_id=? ORDER BY created_at, id", (t, user_id))
    out, last_user = [], None
    for m in msgs:
        if m["role"] == "user":
            last_user = m
        elif last_user and m["payload"]:
            p = db.loads(m["payload"], {})
            if topic_id and last_user["topic_id"] != topic_id:
                continue
            esc = db.row("SELECT status, teacher_answer, teacher_note FROM escalations WHERE id=? AND tenant_id=?", (p.get("escalation_id"), t)) if p.get("escalation_id") else None
            out.append({"question": last_user["content"], "decision": p.get("decision"), "answer": p.get("answer"), "message": p.get("message"),
                        "escalation_id": p.get("escalation_id"), "escalation": esc, "topic_id": last_user["topic_id"], "created_at": m["created_at"],
                        "solved": p.get("decision") == "ANSWER" or bool(esc and esc["status"] == "approved")})
    return list(reversed(out))


@router.get("/config", response_model=DomainConfig, summary="Domain/agent policy configuration for the tenant")
def get_config(t: str = Depends(tenant)):
    return load_config(t)


@router.put("/config", response_model=DomainConfig)
def put_config(cfg: DomainConfig, t: str = Depends(tenant)):
    return save_config(t, cfg)


@router.get("/sessions/{session_id}/messages", summary="Conversation history for a session")
def session_messages(session_id: str, t: str = Depends(tenant)):
    out = []
    for m in db.rows("SELECT role, content, payload, created_at FROM messages WHERE tenant_id=? AND session_id=? ORDER BY created_at, id", (t, session_id)):
        out.append({"role": m["role"], "content": m["content"], "response": db.loads(m["payload"]) if m["payload"] else None, "created_at": m["created_at"]})
    return out
