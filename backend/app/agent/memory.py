"""Persistent memory + human approval. Only teacher approval can create trusted solved-doubt memory."""
from .. import db, vectorstore


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
        raise ApprovalError(f"Could not index the resolution, nothing was saved: {ex}") from ex
    db.execute("UPDATE escalations SET status='approved', teacher_answer=?, teacher_id=?, resolved_at=? WHERE id=?", (answer, teacher_id, db.now(), escalation_id))
    return {"resolution_id": rid, "escalation_id": escalation_id, "indexed": True}


def reject(tenant_id: str, escalation_id: int, teacher_id: str, note: str = "") -> dict:
    _pending(tenant_id, escalation_id)
    db.execute("UPDATE escalations SET status='rejected', teacher_id=?, teacher_note=?, resolved_at=? WHERE id=?", (teacher_id, note.strip(), db.now(), escalation_id))
    return {"escalation_id": escalation_id, "status": "rejected"}
