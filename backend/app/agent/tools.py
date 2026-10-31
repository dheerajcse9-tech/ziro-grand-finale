"""Executable agent tools. Each performs a real operation (vector search / SQLite write); none return canned results."""
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from .. import db, vectorstore
from . import memory
from .domain import DomainConfig


@dataclass
class ToolContext:
    tenant_id: str
    config: DomainConfig
    session_id: str = ""
    user_id: str | None = None


@dataclass
class ToolResult:
    name: str
    ok: bool
    data: Any = None
    error: str | None = None
    ms: int = 0


def search_knowledge_base(ctx: ToolContext, query: str, k: int = 6, subject_id: str | None = None) -> list[dict]:
    """Semantic search over curated sources (PDF, video transcript) and approved resolutions (Q&A vectors), tenant-scoped."""
    types = [t for t in ctx.config.sources if t in ("pdf", "video", "resolution")]
    hits = vectorstore.query(ctx.tenant_id, query, k=k * 2, source_type=types, subject_id=subject_id)
    return [h for h in hits if h.get("kind") != "question"][:k]


def search_solved_doubts(ctx: ToolContext, query: str, k: int = 3) -> list[dict]:
    """Semantic search over teacher-approved resolutions. SQLite is the source of truth: only status='approved' rows count."""
    if "resolution" not in ctx.config.sources:
        return []
    out = []
    for h in vectorstore.query(ctx.tenant_id, query, k=k, source_type="resolution", kind="question"):
        r = db.row("SELECT * FROM resolutions WHERE id=? AND tenant_id=? AND status='approved'", (h["resolution_id"], ctx.tenant_id))
        if r:
            out.append({"resolution_id": r["id"], "question": r["question"], "answer": r["answer"], "similarity": h["similarity"],
                        "approved_by": r["approved_by"], "created_at": r["created_at"], "topic_id": r["topic_id"], "subject_id": r["subject_id"]})
    return out


def create_escalation(ctx: ToolContext, question: str, standalone_question: str, reason: str, subject_id: str | None = None,
                      topic_id: str | None = None, evidence: list[dict] | None = None) -> dict:
    """Persist an escalation for human review; identical pending questions in a session are not duplicated."""
    dup = db.row("SELECT id FROM escalations WHERE tenant_id=? AND session_id=? AND standalone_question=? AND status='pending'",
                 (ctx.tenant_id, ctx.session_id, standalone_question))
    if dup:
        return {"escalation_id": dup["id"], "duplicate": True}
    eid = db.execute("INSERT INTO escalations(tenant_id,session_id,user_id,question,standalone_question,subject_id,topic_id,reason,evidence,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                     (ctx.tenant_id, ctx.session_id, ctx.user_id, question, standalone_question, subject_id, topic_id, reason, db.dumps(evidence or []), "pending", db.now()))
    return {"escalation_id": eid, "duplicate": False}


def save_approved_resolution(ctx: ToolContext, escalation_id: int, answer: str, teacher_id: str) -> dict:
    return memory.approve(ctx.tenant_id, escalation_id, answer, teacher_id)


@dataclass
class ToolSpec:
    fn: Callable
    description: str
    human_only: bool = False


REGISTRY: dict[str, ToolSpec] = {
    "search_knowledge_base": ToolSpec(search_knowledge_base, "Semantic retrieval over PDFs, transcripts and approved resolutions"),
    "search_solved_doubts": ToolSpec(search_solved_doubts, "Semantic search over teacher-approved resolutions"),
    "create_escalation": ToolSpec(create_escalation, "Persist an escalation for a human teacher"),
    "save_approved_resolution": ToolSpec(save_approved_resolution, "Save a teacher-approved answer into trusted memory (human approval only)", human_only=True),
}


def call_tool(name: str, ctx: ToolContext, *, as_agent: bool = True, **kwargs) -> ToolResult:
    spec = REGISTRY.get(name)
    t0 = time.perf_counter()
    if not spec or name not in ctx.config.tools:
        return ToolResult(name, False, error=f"Tool '{name}' is not enabled for this tenant.")
    if spec.human_only and as_agent:
        return ToolResult(name, False, error=f"Tool '{name}' requires human approval and cannot be called by the agent.")
    try:
        data = spec.fn(ctx, **kwargs)
        return ToolResult(name, True, data=data, ms=int((time.perf_counter() - t0) * 1000))
    except Exception as e:
        return ToolResult(name, False, error=f"{type(e).__name__}: {e}", ms=int((time.perf_counter() - t0) * 1000))
