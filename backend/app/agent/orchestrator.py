"""Central agent orchestrator: understand -> retrieve (solved doubts + knowledge) -> evaluate evidence -> decide -> execute -> persist."""
import logging
import time

from .. import db
from . import textutil as tu
from .domain import DomainConfig, load_config
from .llm import LLMError, LLMProvider, LocalProvider, get_provider
from .policy import decide
from .schemas import AgentRequest, AgentResponse, Source, TraceStep
from .tools import ToolContext, call_tool

log = logging.getLogger("doubtloop.agent")
MAX_HISTORY = 6


def to_source(e: dict) -> Source:
    st = e["source_type"]
    ts = e.get("ts_start")
    return Source(
        source_type=st, source_id=e["source_id"], source_name=e["source_name"], page=e.get("page"),
        timestamp_start=ts, timestamp_end=e.get("ts_end"), youtube_id=e.get("youtube_id"),
        url=f"https://www.youtube.com/watch?v={e['youtube_id']}&t={int(ts or 0)}" if st == "video" and e.get("youtube_id") else None,
        trust=e.get("trust", "curated"), origin=e.get("origin"), excerpt=e["text"][:220].strip(), chunk_id=e.get("chunk_id"))


def dedupe_sources(items: list[Source]) -> list[Source]:
    seen, out = set(), []
    for s in items:
        k = (s.source_id, s.page, int((s.timestamp_start or 0) // 30))
        if k not in seen:
            seen.add(k); out.append(s)
    return out


class Orchestrator:
    def __init__(self, provider: LLMProvider | None = None):
        self.provider = provider or get_provider()
        self.local = LocalProvider()

    # ---- state helpers -------------------------------------------------
    @staticmethod
    def _load_state(tenant_id: str, session_id: str) -> dict:
        r = db.row("SELECT state FROM sessions WHERE session_id=? AND tenant_id=?", (session_id, tenant_id))
        return db.loads(r["state"], {}) if r else {}

    @staticmethod
    def _save_state(tenant_id: str, session_id: str, state: dict) -> None:
        db.execute("INSERT INTO sessions(session_id,tenant_id,state,updated_at) VALUES(?,?,?,?) ON CONFLICT(session_id,tenant_id) DO UPDATE SET state=excluded.state, updated_at=excluded.updated_at",
                   (session_id, tenant_id, db.dumps(state), db.now()))

    # ---- main loop -----------------------------------------------------
    def ask(self, req: AgentRequest) -> AgentResponse:
        trace: list[TraceStep] = []
        flags = {"degraded": False}
        cfg = load_config(req.tenant_id)
        ctx = ToolContext(req.tenant_id, cfg, req.session_id, req.user_id)
        state = self._load_state(req.tenant_id, req.session_id)
        pending, history = state.get("pending"), state.get("history", [])
        t_start = time.perf_counter()

        def step(name: str, detail: str = "", ok: bool = True, since: float | None = None):
            trace.append(TraceStep(step=name, ok=ok, detail=detail, ms=int((time.perf_counter() - (since or t_start)) * 1000)))

        def llm(task: str, *args):
            t = time.perf_counter()
            try:
                out = getattr(self.provider, task)(*args)
                step(f"llm.{task}", f"{self.provider.name}", since=t)
                return out
            except LLMError as e:
                flags["degraded"] = True
                step(f"llm.{task}", f"{e}; using local deterministic fallback", ok=False, since=t)
                return getattr(self.local, task)(*args)

        step("receive", f"question received ({len(req.question)} chars)" + (f"; continuing pending clarification (round {pending['rounds']})" if pending else ""))
        inj = tu.injection_hits(req.question)
        if inj:
            step("safety", "possible prompt-injection phrasing in the question; evidence-only policy remains in force", ok=False)

        # STEP 2: understand
        subj = db.row("SELECT name FROM subjects WHERE id=? AND tenant_id=?", (req.subject_id, req.tenant_id)) if req.subject_id else None
        topic = db.row("SELECT name FROM topics WHERE id=? AND tenant_id=?", (req.topic_id, req.tenant_id)) if req.topic_id else None
        u = llm("understand", req.question, history, pending, {"subject_name": subj and subj["name"], "topic_name": topic and topic["name"]}, cfg)
        question = u["standalone_question"][:2000]
        step("understand", f"intent={u['intent']}; ambiguous={u['ambiguous']}; standalone={question!r}")
        rounds = pending["rounds"] if pending else 0
        qterms = tu.terms(question)

        # STEP 3-4: retrieval via tools
        solved, kb, retrieval_error = [], [], None
        if u["ambiguous"] and cfg.clarification_enabled and rounds < cfg.thresholds.max_clarification_rounds:
            preview = []
            if qterms:  # cheap preview so the retrieved context survives the clarification round
                r = call_tool("search_knowledge_base", ctx, query=question, k=3, subject_id=req.subject_id)
                preview = [h["source_name"] for h in r.data] if r.ok else []
            return self._clarify(req, cfg, state, history, u, pending, preview, trace, flags, step)

        r_solved = call_tool("search_solved_doubts", ctx, query=question, k=3)
        step("tool.search_solved_doubts", f"{len(r_solved.data or [])} approved resolutions" if r_solved.ok else r_solved.error, ok=r_solved.ok)
        r_kb = call_tool("search_knowledge_base", ctx, query=question, k=cfg.top_k, subject_id=req.subject_id)
        step("tool.search_knowledge_base", f"{len(r_kb.data or [])} chunks retrieved" if r_kb.ok else r_kb.error, ok=r_kb.ok)
        if not r_kb.ok:
            retrieval_error = r_kb.error
        solved = r_solved.data if r_solved.ok else []
        kb = r_kb.data if r_kb.ok else []

        # STEP 5: evaluate evidence (deterministic filtering, then LLM/heuristic assessment)
        t = cfg.thresholds
        ev, quarantined = [], 0
        for h in kb:
            if h["similarity"] < t.min_relevance or tu.coverage(qterms, [h["text"]]) == 0:
                continue
            if tu.injection_hits(h["text"]):
                quarantined += 1
                continue
            ev.append(h)
        ev.sort(key=lambda h: -(h["similarity"] + (0.03 if req.topic_id and h.get("topic_id") == req.topic_id else 0)))
        ev = ev[:5]
        for i, e in enumerate(ev):
            e["ref"] = f"E{i + 1}"
        cands = [dict(s, ref=f"R{i + 1}") for i, s in enumerate(solved) if s["similarity"] >= t.reuse_similarity - 0.12][:2]
        step("evidence", f"{len(ev)} relevant chunks, {len(cands)} solved-doubt candidates" + (f", {quarantined} untrusted chunk(s) quarantined (injection patterns)" if quarantined else ""), ok=not quarantined)
        if ev or cands:
            a = llm("assess", question, ev, cands, cfg)
        else:
            a = {"supported": False, "coverage": 0.0, "supporting_ids": [], "contradiction": False, "contradiction_detail": None, "reuse_ids": []}
        supporting = [e for e in ev if e["ref"] in a["supporting_ids"]] if a["supported"] else []
        reuse_c = max((c for c in cands if c["ref"] in a["reuse_ids"]), key=lambda c: c["similarity"], default=None)
        step("assess", f"supported={a['supported']}; coverage={a['coverage']}; supporting={len(supporting)}; contradiction={a['contradiction']}; reuse={reuse_c['resolution_id'] if reuse_c else None}")

        # STEP 6: decide
        d = decide(cfg, ambiguous=False, clarify_rounds=rounds, retrieval_error=retrieval_error,
                   reuse_similarity=reuse_c["similarity"] if reuse_c else None, n_relevant=len(ev),
                   top_similarity=max((e["similarity"] for e in supporting), default=0.0), assessment=a, n_supporting=len(supporting))
        step("decide", f"{d.decision} ({d.code}); confidence={d.confidence}")

        # STEP 7: execute
        answer, sources, answered_from = None, [], "none"
        if d.decision == "ANSWER" and d.reuse:
            answer, answered_from = reuse_c["answer"], "approved_resolution"
            sources = [Source(source_type="resolution", source_id=f"resolution-{reuse_c['resolution_id']}", source_name="Teacher-approved resolution",
                              trust="teacher_approved", origin="teacher", excerpt=reuse_c["question"][:220], chunk_id=f"res-{reuse_c['resolution_id']}-q")]
            step("execute", f"reused teacher-approved resolution #{reuse_c['resolution_id']} (approved by {reuse_c['approved_by']})")
        elif d.decision == "ANSWER":
            c = llm("compose", question, supporting[:4], cfg)
            valid_refs = {e["ref"] for e in supporting}
            cited = [r for r in c["cited_ids"] if r in valid_refs] or [e["ref"] for e in supporting[:3]]
            if not c["answer"]:
                d = type(d)("ESCALATE", "insufficient_evidence", "Answer generation found the evidence insufficient.", d.confidence)
                step("execute", "composition refused: evidence insufficient -> escalating", ok=False)
            else:
                answer, answered_from = c["answer"], "evidence"
                sources = dedupe_sources([to_source(e) for e in supporting if e["ref"] in cited])
                step("execute", f"answer composed from {len(sources)} cited source(s)")

        resp = AgentResponse(decision=d.decision, answer=answer, confidence=d.confidence, sources=sources, reason=d.reason, reason_code=d.code,
                             answered_from=answered_from, session_id=req.session_id, llm_mode=self._mode(flags))
        if d.decision == "ESCALATE":
            weak = [h for h in kb if h not in ev][:2]
            evidence = [dict(to_source(h).model_dump(exclude_none=True), similarity=h["similarity"], relevant=h in ev) for h in ev + weak]
            r = call_tool("create_escalation", ctx, question=req.question, standalone_question=question, reason=f"{d.code}: {d.reason}",
                          subject_id=req.subject_id, topic_id=req.topic_id, evidence=evidence)
            step("tool.create_escalation", f"escalation #{r.data['escalation_id']}" if r.ok else r.error, ok=r.ok)
            if r.ok:
                resp.escalation_id = r.data["escalation_id"]
                resp.message = (f"I can't answer this reliably from the course materials, so I've sent it to your teacher (ticket #{resp.escalation_id}). "
                                "The verified answer will appear here once approved.")
            else:
                resp.message = f"I can't answer this reliably, and the escalation could not be saved: {r.error}"
        # STEP 9: preserve state
        history = (history + [{"role": "user", "content": question}, {"role": "assistant", "content": answer or resp.message or ""}])[-MAX_HISTORY:]
        state.update(pending=None, history=history)
        self._save_state(req.tenant_id, req.session_id, state)
        resp.trace = trace
        self._persist(req, resp, req.question)
        return resp

    def _clarify(self, req, cfg, state, history, u, pending, preview, trace, flags, step) -> AgentResponse:
        cq = u.get("clarification_question") or "Could you give more detail about what you want to know?"
        state["pending"] = {"original_question": (pending or {}).get("original_question") or req.question, "clarification_question": cq,
                            "rounds": (pending["rounds"] if pending else 0) + 1, "preview_sources": preview}
        history = (history + [{"role": "user", "content": req.question}, {"role": "assistant", "content": cq}])[-MAX_HISTORY:]
        state["history"] = history
        self._save_state(req.tenant_id, req.session_id, state)
        step("decide", "CLARIFY (ambiguous_question); original question and retrieval preview saved for the next turn")
        resp = AgentResponse(decision="CLARIFY", clarification_question=cq, reason=u.get("reason") or "The question is missing information needed to answer it.",
                             reason_code="ambiguous_question", session_id=req.session_id, llm_mode=self._mode(flags), trace=trace)
        self._persist(req, resp, req.question)
        return resp

    def _mode(self, flags: dict) -> str:
        if flags["degraded"]:
            return f"{self.provider.name}+local-fallback"
        return self.provider.name

    @staticmethod
    def _persist(req: AgentRequest, resp: AgentResponse, raw_question: str) -> None:
        now = db.now()
        db.execute("INSERT INTO messages(tenant_id,session_id,user_id,role,content,payload,subject_id,topic_id,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                   (req.tenant_id, req.session_id, req.user_id, "user", raw_question, None, req.subject_id, req.topic_id, now))
        text = resp.answer or resp.clarification_question or resp.message or ""
        db.execute("INSERT INTO messages(tenant_id,session_id,user_id,role,content,payload,subject_id,topic_id,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                   (req.tenant_id, req.session_id, req.user_id, "assistant", text, resp.model_dump_json(exclude={"trace"}), req.subject_id, req.topic_id, now + 0.001))


_instance: Orchestrator | None = None


def get_orchestrator() -> Orchestrator:
    global _instance
    if _instance is None:
        _instance = Orchestrator()
    return _instance
