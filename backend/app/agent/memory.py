"""Persistent memory + human approval. Only teacher approval can create trusted solved-doubt memory."""
from .. import db, vectorstore
from .events import Recorder, run_for_escalation


def _rec(tenant_id: str, escalation_id: int) -> Recorder:
    """Continue the run that raised the escalation so the whole loop reads as one timeline."""
    return Recorder(tenant_id, run_for_escalation(tenant_id, escalation_id) or f"esc-{escalation_id}")


class ApprovalError(RuntimeError):
    pass


def _pending(tenant_id: str, escalation_id: int) -> dict:
    e = db.row("SELECT * FROM escalations WHERE id=? AND tenant_id=?", (escalation_id, tenant_id))
    if not e:
        raise ApprovalError("Escalation not found.")
    if e["status"] != "pending":
        raise ApprovalError(f"Escalation is already {e['status']}.")
    return e


def approve(tenant_id: str, escalation_id: int, answer: str, teacher_id: str) -> dict:
    """Save teacher-approved resolution, then index it for future retrieval (question vector + Q&A vector)."""
    answer = answer.strip()
    if len(answer) < 10:
        raise ApprovalError("The approved answer is too short.")
    e = _pending(tenant_id, escalation_id)
    rec = _rec(tenant_id, escalation_id)
    rec.emit("teacher_approval_received", "teacher", "completed", "Teacher approved the answer", escalation_id=escalation_id, teacher_id=teacher_id, answer_chars=len(answer), decision="approved")
    rec.emit("agent_started", "memory", "running", "Memory Agent", escalation_id=escalation_id)
    question = e["standalone_question"] or e["question"]
    rid = db.execute("INSERT INTO resolutions(tenant_id,escalation_id,question,answer,subject_id,topic_id,sources,approved_by,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                     (tenant_id, escalation_id, question, answer, e["subject_id"], e["topic_id"], e["evidence"], teacher_id, "approved", db.now()))
    meta = {"source_id": f"resolution-{rid}", "source_type": "resolution", "source_name": "Teacher-approved resolution",
            "subject_id": e["subject_id"], "topic_id": e["topic_id"], "trust": "teacher_approved", "origin": "teacher", "resolution_id": rid}
    try:
        vectorstore.upsert(tenant_id, [
            {"id": f"res-{rid}-q", "text": question, "metadata": {**meta, "kind": "question"}},
            {"id": f"res-{rid}-qa", "text": f"Q: {question}\nA: {answer}", "metadata": {**meta, "kind": "qa"}},
        ])
    except Exception as ex:  # keep SQLite and the index consistent: untrusted until indexed
        db.execute("DELETE FROM resolutions WHERE id=?", (rid,))
        rec.emit("agent_failed", "memory", "failed", "Memory Agent", escalation_id=escalation_id, error=f"Indexing failed; nothing saved: {ex}")
        raise ApprovalError(f"Could not index the resolution, nothing was saved: {ex}") from ex
    db.execute("UPDATE escalations SET status='approved', teacher_answer=?, teacher_id=?, resolved_at=? WHERE id=?", (answer, teacher_id, db.now(), escalation_id))
    vector_ids = [f"res-{rid}-q", f"res-{rid}-qa"]
    rec.emit("memory_saved", "memory", "completed", "Saved to trusted memory", escalation_id=escalation_id, resolution_id=rid, indexed=True, vector_ids=vector_ids, trust="teacher_approved",
             validation={"min_length_ok": True, "approved_by_human": True})
    return {"resolution_id": rid, "escalation_id": escalation_id, "indexed": True, "vector_ids": vector_ids, "trust": "teacher_approved"}


def reject(tenant_id: str, escalation_id: int, teacher_id: str, note: str = "") -> dict:
    _pending(tenant_id, escalation_id)
    rec = _rec(tenant_id, escalation_id)
    rec.emit("teacher_rejection_received", "teacher", "completed", "Teacher rejected / closed the doubt", escalation_id=escalation_id, teacher_id=teacher_id, decision="rejected", has_note=bool(note.strip()))
    rec.emit("agent_skipped", "memory", "skipped", "Memory Agent", escalation_id=escalation_id, reason="Rejected: nothing is written to trusted memory")
    db.execute("UPDATE escalations SET status='rejected', teacher_id=?, teacher_note=?, resolved_at=? WHERE id=?", (teacher_id, note.strip(), db.now(), escalation_id))
    return {"escalation_id": escalation_id, "status": "rejected"}
