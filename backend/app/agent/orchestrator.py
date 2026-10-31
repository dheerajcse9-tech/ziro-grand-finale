"""Central agent orchestrator: understand -> retrieve (solved doubts + knowledge) -> evaluate evidence -> decide -> execute -> persist."""
import logging
import time

from .. import db
from . import textutil as tu
from .domain import DomainConfig, load_config
from .events import Recorder
from .llm import LLMError, LLMProvider, LocalProvider, get_provider
from .policy import decide
from .schemas import AgentRequest, AgentResponse, Source, TraceStep
from .tools import ToolContext, call_tool

log = logging.getLogger("doubtloop.agent")
MAX_HISTORY = 6


def to_source(e: dict) -> Source:
    st = e["source_type"]
    ts = e.get("ts_start")
    is_video = st == "video"
    return Source(
        source_type=st, source_id=e["source_id"], source_name=e["source_name"], page=e.get("page"), filename=e.get("filename"),
        heading=e.get("heading"), timestamp_start=ts, timestamp_end=e.get("ts_end"), timestamp_status=e.get("ts_status") if is_video else None,
        youtube_id=e.get("youtube_id"), url=f"https://www.youtube.com/watch?v={e['youtube_id']}&t={int(ts or 0)}" if is_video and e.get("youtube_id") else None,
        trust=e.get("trust", "curated"), origin=e.get("origin"), excerpt=e["text"][:220].strip(), chunk_id=e.get("chunk_id"))


def diversify(ranked: list[dict], n: int) -> list[dict]:
    """Top-n by rank, but guarantee every source type that has relevant candidates is represented (e.g. a PDF page next to lecture captions)."""
    top = ranked[:n]
    for st in dict.fromkeys(e["source_type"] for e in ranked):
        if all(e["source_type"] != st for e in top):
            best = next(e for e in ranked if e["source_type"] == st)
            counts = {t: sum(1 for e in top if e["source_type"] == t) for t in {e["source_type"] for e in top}}
            drop = next((i for i in range(len(top) - 1, -1, -1) if counts[top[i]["source_type"]] > 1), None)
            if drop is not None:
                top[drop] = best
    return sorted(top, key=ranked.index)


def is_pointer(e: dict) -> bool:
    """A lecture-segment chunk with no explanation/keywords/transcript only says *where* a topic is covered; it cannot support an answer."""
    return e.get("kind") == "segment" and not e.get("has_content")


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
    def ask(self, req: AgentRequest, rec: Recorder | None = None) -> AgentResponse:
        rec = rec or Recorder(req.tenant_id, session_id=req.session_id)
        trace: list[TraceStep] = []
        flags = {"degraded": False}
        cfg = load_config(req.tenant_id)
        ctx = ToolContext(req.tenant_id, cfg, req.session_id, req.user_id)
        state = self._load_state(req.tenant_id, req.session_id)
        pending, history = state.get("pending"), state.get("history", [])
        t_start = time.perf_counter()

        def step(name: str, detail: str = "", ok: bool = True, since: float | None = None):
            trace.append(TraceStep(step=name, ok=ok, detail=detail, ms=int((time.perf_counter() - (since or t_start)) * 1000)))

        agent_of = {"understand": "understanding", "assess": "verification", "compose": "response"}

        def llm(task: str, *args):
            t = time.perf_counter()
            if flags["degraded"] and self.provider is not self.local:  # Gemini already failed in this request: don't wait on it again
                step(f"llm.{task}", "skipped Gemini after earlier failure in this request; local deterministic logic", ok=False, since=t)
                rec.emit("llm_call", agent_of[task], "skipped", f"llm.{task}", provider=self.provider.name, fallback=True, note="Gemini skipped after an earlier failure in this request; local deterministic logic used")
                return getattr(self.local, task)(*args)
            try:
                out = getattr(self.provider, task)(*args)
                lc = getattr(self.provider, "last_call", None) or {}
                usage = (" (cached)" if lc.get("cached") else f" model={getattr(self.provider, 'model', '')} tokens in/out={lc.get('in')}/{lc.get('out')}") if lc else ""
                step(f"llm.{task}", f"{self.provider.name}{usage}", since=t)
                rec.emit("llm_call", agent_of[task], "completed", f"llm.{task}", provider=self.provider.name, model=getattr(self.provider, "model", None),
                         tokens_in=lc.get("in"), tokens_out=lc.get("out"), cached=bool(lc.get("cached")), ms=int((time.perf_counter() - t) * 1000), fallback=False)
                return out
            except Exception as e:  # LLMError or any malformed-provider failure: never crash the request, fall back to deterministic local logic
                flags["degraded"] = True
                msg = str(e) if isinstance(e, LLMError) else f"unexpected {type(e).__name__}"
                log.warning("llm.%s failed: %s", task, msg)
                step(f"llm.{task}", f"{msg}; using local deterministic fallback", ok=False, since=t)
                rec.emit("llm_call", agent_of[task], "failed", f"llm.{task}", provider=self.provider.name, error=msg, fallback=True, ms=int((time.perf_counter() - t) * 1000))
                return getattr(self.local, task)(*args)

        rec.emit("run_started", "orchestrator", "completed", "Doubt received", question=req.question[:160], llm=self.provider.name, continuing_clarification=bool(pending), subject_id=req.subject_id, topic_id=req.topic_id)
        step("receive", f"question received ({len(req.question)} chars)" + (f"; continuing pending clarification (round {pending['rounds']})" if pending else ""))
        inj = tu.injection_hits(req.question)
        if inj:
            step("safety", "possible prompt-injection phrasing in the question; evidence-only policy remains in force", ok=False)

        # STEP 2: understand
        subj = db.row("SELECT name FROM subjects WHERE id=? AND tenant_id=?", (req.subject_id, req.tenant_id)) if req.subject_id else None
        topic = db.row("SELECT name FROM topics WHERE id=? AND tenant_id=?", (req.topic_id, req.tenant_id)) if req.topic_id else None
        rec.emit("agent_started", "understanding", "running", "Query Understanding Agent")
        u = llm("understand", req.question, history, pending, {"subject_name": subj and subj["name"], "topic_name": topic and topic["name"]}, cfg)
        question = u["standalone_question"][:2000]
        step("understand", f"intent={u['intent']}; ambiguous={u['ambiguous']}; standalone={question!r}")
        rec.emit("agent_completed", "understanding", "completed", "Query Understanding Agent", intent=u["intent"], ambiguous=u["ambiguous"], standalone_question=question[:200],
                 subject=subj and subj["name"], topic=topic and topic["name"], degraded=flags["degraded"])
        rounds = pending["rounds"] if pending else 0
        qterms = tu.terms(question)

        # STEP 3-4: retrieval via tools
        solved, kb, retrieval_error = [], [], None
        if u["ambiguous"] and cfg.clarification_enabled and rounds < cfg.thresholds.max_clarification_rounds:
            preview = []
            rec.emit("agent_started", "retrieval", "running", "Knowledge Retrieval Agent", note="ambiguous question: preview only")
            if qterms:  # cheap preview so the retrieved context survives the clarification round
                r = call_tool("search_knowledge_base", ctx, query=question, k=3, subject_id=req.subject_id)
                preview = [h["source_name"] for h in r.data] if r.ok else []
                self._tool_event(rec, "retrieval", r)
            rec.emit("retrieval_completed", "retrieval", "completed", "Knowledge Retrieval Agent", preview_only=True, preview_sources=len(preview))
            rec.emit("agent_skipped", "verification", "skipped", "Evidence Verification Agent", reason="Waiting for the student to clarify before verifying evidence")
            return self._clarify(req, cfg, state, history, u, pending, preview, trace, flags, step, rec)

        rec.emit("agent_started", "retrieval", "running", "Knowledge Retrieval Agent")
        r_solved = call_tool("search_solved_doubts", ctx, query=question, k=3)
        self._tool_event(rec, "retrieval", r_solved)
        step("tool.search_solved_doubts", f"{len(r_solved.data or [])} approved resolutions" if r_solved.ok else r_solved.error, ok=r_solved.ok)
        r_kb = call_tool("search_knowledge_base", ctx, query=question, k=cfg.top_k * 2, subject_id=req.subject_id)  # wide candidate pool; hybrid re-ranking trims it
        step("tool.search_knowledge_base", f"{len(r_kb.data or [])} chunks retrieved" if r_kb.ok else r_kb.error, ok=r_kb.ok)
        self._tool_event(rec, "retrieval", r_kb)
        if not r_kb.ok:
            retrieval_error = r_kb.error
            rec.emit("agent_failed", "retrieval", "failed", "Knowledge Retrieval Agent", error=r_kb.error)
        else:
            by_type = {st: sum(1 for h in r_kb.data if h["source_type"] == st) for st in {h["source_type"] for h in r_kb.data}}
            rec.emit("retrieval_completed", "retrieval", "completed", "Knowledge Retrieval Agent", knowledge_chunks=len(r_kb.data), by_source_type=by_type,
                     approved_resolutions=len(r_solved.data or []) if r_solved.ok else 0)
        solved = r_solved.data if r_solved.ok else []
        kb = r_kb.data if r_kb.ok else []

        # STEP 5: evaluate evidence (deterministic filtering, then LLM/heuristic assessment)
        rec.emit("agent_started", "verification", "running", "Evidence Verification Agent")
        t = cfg.thresholds
        ev, quarantined = [], 0
        idf = tu.idf_weights(qterms, [h["text"] for h in kb])
        for h in kb:
            if h["similarity"] < t.min_relevance or tu.coverage(qterms, [h["text"]]) == 0:
                continue
            if tu.injection_hits(h["text"]):
                quarantined += 1
                continue
            ev.append(h)
        # hybrid rank: semantic similarity + IDF-weighted lexical coverage of the question's key terms (+ small active-topic boost)
        ev.sort(key=lambda h: -(h["similarity"] + 0.3 * tu.weighted_coverage(qterms, h["text"], idf) + 0.3 * tu.phrase_bonus(question, h["text"], h.get("heading")) + cfg.source_weights.get(h["source_type"], 0) + (cfg.topic_boost if req.topic_id and h.get("topic_id") == req.topic_id else 0)))
        pointers = [e for e in ev if is_pointer(e)][:2]
        ev = diversify([e for e in ev if not is_pointer(e)], 5)
        for i, e in enumerate(ev):
            e["ref"] = f"E{i + 1}"
        cands = [dict(s, ref=f"R{i + 1}") for i, s in enumerate(solved) if s["similarity"] >= t.reuse_similarity - 0.12][:2]
        step("evidence", f"{len(ev)} relevant chunks, {len(pointers)} lecture-segment pointers, {len(cands)} solved-doubt candidates" + (f", {quarantined} untrusted chunk(s) quarantined (injection patterns)" if quarantined else ""), ok=not quarantined)
        if ev or cands:
            a = llm("assess", question, ev, cands, cfg)
        else:
            a = {"supported": False, "coverage": 0.0, "supporting_ids": [], "contradiction": False, "contradiction_detail": None, "reuse_ids": []}
        supporting = [e for e in ev if e["ref"] in a["supporting_ids"]] if a["supported"] else []
        # keep only chunks whose (IDF-weighted) coverage is close to the best chunk of the same source type, so off-topic chunks are neither composed from nor cited
        wc = {e["ref"]: tu.weighted_coverage(qterms, e["text"], idf) + 0.5 * tu.phrase_bonus(question, e["text"], e.get("heading")) for e in supporting}
        best = {st: max(wc[e["ref"]] for e in supporting if e["source_type"] == st) for st in {e["source_type"] for e in supporting}}
        supporting = [e for e in supporting if wc[e["ref"]] >= 0.6 * best[e["source_type"]]]
        reuse_c = max((c for c in cands if c["ref"] in a["reuse_ids"]), key=lambda c: c["similarity"], default=None)
        cites = [{"type": e["source_type"], "name": e["source_name"], "page": e.get("page"), "filename": e.get("filename"), "ts_start": e.get("ts_start"),
                  "ts_status": e.get("ts_status"), "similarity": e["similarity"]} for e in supporting]
        rec.emit("evidence_verified", "verification", "completed", "Evidence Verification Agent", relevant_chunks=len(ev), lecture_pointers=len(pointers), solved_candidates=len(cands),
                 quarantined=quarantined, supported=a["supported"], supporting=len(supporting), coverage=a["coverage"], contradiction=a["contradiction"],
                 contradiction_detail=a.get("contradiction_detail"), citations_available=len(cites), supporting_sources=cites[:6], degraded=flags["degraded"],
                 min_relevance=t.min_relevance)
        step("assess", f"supported={a['supported']}; coverage={a['coverage']}; supporting={len(supporting)}; contradiction={a['contradiction']}; reuse={reuse_c['resolution_id'] if reuse_c else None}")

        # STEP 6: decide
        rec.emit("agent_started", "decision", "running", "Decision Agent")
        d = decide(cfg, ambiguous=False, clarify_rounds=rounds, retrieval_error=retrieval_error,
                   reuse_similarity=reuse_c["similarity"] if reuse_c else None, n_relevant=len(ev),
                   top_similarity=max((e["similarity"] for e in supporting), default=0.0), assessment=a, n_supporting=len(supporting))
        step("decide", f"{d.decision} ({d.code}); confidence={d.confidence}")
        rec.emit("decision_made", "decision", "completed", "Decision Agent", decision=d.decision, code=d.code, reason=d.reason, confidence=d.confidence,
                 reuse=bool(d.reuse), thresholds=t.model_dump(), rule="deterministic policy (confidence computed in code, not by the LLM)")

        # STEP 7: execute
        answer, sources, answered_from = None, [], "none"
        rec.emit("agent_started", "response", "running", "Response Generation Agent")
        if d.decision == "ANSWER" and d.reuse:
            answer, answered_from = reuse_c["answer"], "approved_resolution"
            sources = [Source(source_type="resolution", source_id=f"resolution-{reuse_c['resolution_id']}", source_name="Teacher-approved resolution",
                              trust="teacher_approved", origin="teacher", excerpt=reuse_c["question"][:220], chunk_id=f"res-{reuse_c['resolution_id']}-q")]
            step("execute", f"reused teacher-approved resolution #{reuse_c['resolution_id']} (approved by {reuse_c['approved_by']})")
            self._memory_reused(req, rec, reuse_c, sources)
        elif d.decision == "ANSWER":
            comp = sorted(supporting[:4], key=lambda e: (e["source_type"] == "video", -wc[e["ref"]]))  # written sources first (stable)
            c = llm("compose", question, comp, cfg)
            valid_refs = {e["ref"] for e in supporting}
            cited = [r for r in c["cited_ids"] if r in valid_refs] or [e["ref"] for e in supporting[:3]]
            if not c["answer"]:
                d = type(d)("ESCALATE", "insufficient_evidence", "Answer generation found the evidence insufficient.", d.confidence)
                step("execute", "composition refused: evidence insufficient -> escalating", ok=False)
                rec.emit("decision_made", "decision", "completed", "Decision Agent (revised)", decision="ESCALATE", code="insufficient_evidence", reason=d.reason, confidence=d.confidence, overridden=True)
            else:
                answer, answered_from = c["answer"], "evidence"
                # cited evidence first, then up to 2 relevant lecture segments as "watch this part" pointers
                corroborating = []  # best additional supporting chunk per source type, so answers cite both page and lecture
                for st in dict.fromkeys(e["source_type"] for e in supporting):
                    if not any(e["source_type"] == st and e["ref"] in cited for e in supporting):
                        corroborating.append(max((e for e in supporting if e["source_type"] == st), key=lambda e: wc[e["ref"]]))
                sources = dedupe_sources([to_source(e) for e in supporting if e["ref"] in cited] + [to_source(e) for e in corroborating] + [to_source(e) for e in pointers])
                step("execute", f"answer composed from {len(sources)} cited source(s)")
                rec.emit("agent_completed", "response", "completed", "Response Generation Agent", sources=len(sources), answered_from=answered_from, degraded=flags["degraded"],
                         citations=[{"type": x.source_type, "name": x.source_name, "page": x.page, "filename": x.filename, "ts_start": x.timestamp_start, "ts_status": x.timestamp_status} for x in sources])
                rec.emit("agent_skipped", "memory", "skipped", "Memory Agent", reason="Nothing to save: only teacher approval can write trusted memory")

        resp = AgentResponse(decision=d.decision, answer=answer, confidence=d.confidence, sources=sources, reason=d.reason, reason_code=d.code,
                             answered_from=answered_from, session_id=req.session_id, llm_mode=self._mode(flags), run_id=rec.run_id)
        if d.decision == "ESCALATE":
            weak = [h for h in kb if h not in ev][:2]
            evidence = [dict(to_source(h).model_dump(exclude_none=True), similarity=h["similarity"], relevant=h in ev) for h in ev + weak]
            r = call_tool("create_escalation", ctx, question=req.question, standalone_question=question, reason=f"{d.code}: {d.reason}",
                          subject_id=req.subject_id, topic_id=req.topic_id, evidence=evidence)
            step("tool.create_escalation", f"escalation #{r.data['escalation_id']}" if r.ok else r.error, ok=r.ok)
            self._tool_event(rec, "response", r, summary=f"escalation #{r.data['escalation_id']}" if r.ok else None)
            if r.ok:
                resp.escalation_id = r.data["escalation_id"]
                rec.emit("escalation_created", "response", "completed", "Escalated to teacher", escalation_id=resp.escalation_id, reason=d.reason, reason_code=d.code,
                         evidence_saved=len(evidence), duplicate=r.data.get("duplicate", False))
                rec.emit("agent_started", "teacher", "waiting", "Teacher review", escalation_id=resp.escalation_id, note="Waiting for a teacher to approve or reject")
                rec.emit("agent_waiting", "memory", "waiting", "Memory Agent", escalation_id=resp.escalation_id, reason="Waiting for teacher approval; nothing is saved until then")
                resp.message = (f"I can't answer this reliably from the course materials, so I've sent it to your teacher (ticket #{resp.escalation_id}). "
                                "The verified answer will appear here once approved.")
            else:
                rec.emit("agent_failed", "response", "failed", "Escalation could not be saved", error=r.error)
                resp.message = f"I can't answer this reliably, and the escalation could not be saved: {r.error}"
        # STEP 9: preserve state
        history = (history + [{"role": "user", "content": question}, {"role": "assistant", "content": answer or resp.message or ""}])[-MAX_HISTORY:]
        state.update(pending=None, history=history)
        self._save_state(req.tenant_id, req.session_id, state)
        resp.trace = trace
        self._persist(req, resp, req.question)
        rec.emit("run_completed", "orchestrator", "completed", "Run finished", decision=resp.decision, confidence=resp.confidence, llm_mode=resp.llm_mode, answered_from=resp.answered_from,
                 total_ms=int((time.perf_counter() - t_start) * 1000))
        return resp

    @staticmethod
    def _tool_event(rec: Recorder, agent: str, r, summary: str | None = None) -> None:
        data = r.data if r.ok else None
        hits = [{"type": h.get("source_type", "resolution"), "name": h.get("source_name") or (h.get("question") or "")[:60], "page": h.get("page"), "similarity": h.get("similarity")}
                for h in (data if isinstance(data, list) else [])[:5]]
        rec.emit("tool_called", agent, "completed" if r.ok else "failed", r.name, tool=r.name, ms=r.ms, count=len(data) if isinstance(data, list) else None,
                 top_results=hits, summary=summary, error=r.error)

    @staticmethod
    def _memory_reused(req: AgentRequest, rec: Recorder, c: dict, sources: list) -> None:
        rec.emit("agent_completed", "response", "completed", "Response Generation Agent", sources=len(sources), answered_from="approved_resolution", generated=False,
                 note="Teacher-approved answer reused verbatim; no LLM composition")
        esc = db.row("SELECT escalation_id FROM resolutions WHERE id=? AND tenant_id=?", (c["resolution_id"], req.tenant_id))
        rec.emit("memory_retrieved", "memory", "completed", "Memory Agent", resolution_id=c["resolution_id"], similarity=c["similarity"], approved_by=c["approved_by"], escalation_id=esc and esc["escalation_id"])
        if esc and esc["escalation_id"]:  # close the loop on the run where this knowledge was learned
            from .events import run_for_escalation
            origin = run_for_escalation(req.tenant_id, esc["escalation_id"])
            if origin:
                Recorder(req.tenant_id, origin).emit("memory_reused", "memory", "completed", "Learned knowledge reused in a later session", escalation_id=esc["escalation_id"],
                                                     resolution_id=c["resolution_id"], by_run=rec.run_id, similarity=c["similarity"])

    def _clarify(self, req, cfg, state, history, u, pending, preview, trace, flags, step, rec) -> AgentResponse:
        cq = u.get("clarification_question") or "Could you give more detail about what you want to know?"
        state["pending"] = {"original_question": (pending or {}).get("original_question") or req.question, "clarification_question": cq,
                            "rounds": (pending["rounds"] if pending else 0) + 1, "preview_sources": preview}
        history = (history + [{"role": "user", "content": req.question}, {"role": "assistant", "content": cq}])[-MAX_HISTORY:]
        state["history"] = history
        self._save_state(req.tenant_id, req.session_id, state)
        step("decide", "CLARIFY (ambiguous_question); original question and retrieval preview saved for the next turn")
        rec.emit("agent_started", "decision", "running", "Decision Agent")
        rec.emit("decision_made", "decision", "completed", "Decision Agent", decision="CLARIFY", code="ambiguous_question", reason=u.get("reason") or "Missing information", confidence=0.0,
                 rule="ambiguity flagged by query understanding; max clarification rounds not exceeded")
        rec.emit("clarification_requested", "response", "completed", "Clarifying question asked", question=cq, round=state["pending"]["rounds"])
        rec.emit("agent_skipped", "memory", "skipped", "Memory Agent", reason="Nothing to retrieve or save yet")
        resp = AgentResponse(decision="CLARIFY", clarification_question=cq, reason=u.get("reason") or "The question is missing information needed to answer it.",
                             reason_code="ambiguous_question", session_id=req.session_id, llm_mode=self._mode(flags), run_id=rec.run_id, trace=trace)
        self._persist(req, resp, req.question)
        rec.emit("run_completed", "orchestrator", "completed", "Run finished", decision="CLARIFY", confidence=0.0, llm_mode=resp.llm_mode, answered_from="none")
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
