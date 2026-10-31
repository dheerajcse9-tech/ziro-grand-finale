"""Reproducible evaluation: runs every case through the real orchestrator in an isolated eval tenant and computes metrics from the results."""
import json
import threading
import time
from pathlib import Path

import pymupdf as fitz

from .. import db, seed_loader, vectorstore
from ..agent import memory
from ..agent.domain import OS_DOMAIN, save_config
from ..agent.orchestrator import get_orchestrator
from ..agent.schemas import AgentRequest
from ..agent.tools import ToolContext, call_tool

EVAL_TENANT = "eval-tenant"
DATASET = Path(__file__).with_name("dataset.json")
_state = {"running": False, "error": None}


def dataset() -> list[dict]:
    return json.loads(DATASET.read_text())


def _reset_tenant() -> None:
    vectorstore.delete_tenant(EVAL_TENANT)
    for t in ("subjects", "topics", "resources", "escalations", "resolutions", "messages", "sessions", "agent_configs"):
        db.execute(f"DELETE FROM {t} WHERE tenant_id=?", (EVAL_TENANT,))
    seed_loader.seed_tenant(EVAL_TENANT, fixtures=True)
    save_config(EVAL_TENANT, OS_DOMAIN)


def _valid_source(s: dict) -> bool:
    """A citation is valid only if it points to something that really exists (document, page range, video span, approved resolution)."""
    if s["source_type"] == "resolution":
        rid = s["source_id"].removeprefix("resolution-")
        return bool(rid.isdigit() and db.row("SELECT 1 FROM resolutions WHERE id=? AND tenant_id=? AND status='approved'", (int(rid), EVAL_TENANT)))
    r = db.row("SELECT * FROM resources WHERE id=? AND tenant_id=? AND status='indexed'", (s["source_id"], EVAL_TENANT))
    if not r:
        return False
    if s["source_type"] == "pdf":
        with fitz.open(r["file_path"]) as d:
            return s.get("page") is not None and 1 <= s["page"] <= d.page_count
    a, b = s.get("timestamp_start"), s.get("timestamp_end")
    if a is None or b is None or not 0 <= a < b:
        return False
    if s.get("origin") == "segment_metadata":  # must match an imported segment exactly
        return bool(db.row("SELECT 1 FROM video_segments WHERE resource_id=? AND start_s=? AND end_s=?", (s["source_id"], a, b)))
    if r["duration_s"] and b > r["duration_s"] + 1:
        return False
    segs = json.loads(Path(r["file_path"]).read_text()) if r["file_path"] else []
    return bool(segs) and b <= segs[-1]["end"] + 1


def _matches(src: dict, exp: dict) -> bool:
    return (src["source_type"] == exp["source_type"] and (not exp.get("name_contains") or exp["name_contains"] in src["source_name"]) and (not exp.get("filename") or src.get("filename") == exp["filename"])
            and (not exp.get("page") or src.get("page") == exp["page"]) and (not exp.get("youtube_id") or src.get("youtube_id") == exp["youtube_id"]))


def _concepts_ok(answer: str, groups: list[list[str]]) -> tuple[bool, list]:
    low = (answer or "").lower()
    missing = [g for g in groups if not any(k.lower() in low for k in g)]
    return not missing, missing


def run_case(case: dict) -> dict:
    orch = get_orchestrator()
    sid = f"eval-{case['id']}-{int(time.time())}"
    if case.get("setup_resolution"):  # create genuine approved memory through the real tool/approval path
        sr = case["setup_resolution"]
        ctx = ToolContext(EVAL_TENANT, OS_DOMAIN, sid)
        eid = call_tool("create_escalation", ctx, question=sr["question"], standalone_question=sr["question"], reason="eval setup").data["escalation_id"]
        memory.approve(EVAL_TENANT, eid, sr["answer"], "eval-teacher")
    t0 = time.perf_counter()
    mk = lambda q: AgentRequest(question=q, tenant_id=EVAL_TENANT, session_id=sid, topic_id=None)
    resp = orch.ask(mk(case["question"]))
    turns = [resp]
    first = resp
    if case.get("follow_up"):
        resp = orch.ask(mk(case["follow_up"]))
        turns.append(resp)
    final_expected = case.get("expected_final_decision", case["expected_decision"])
    r = resp.model_dump()
    failures, checks = [], {}
    if first.decision != case["expected_decision"]:
        failures.append(f"first-turn decision {first.decision}, expected {case['expected_decision']} ({first.reason_code})")
    if case.get("follow_up") and resp.decision != final_expected:
        failures.append(f"after follow-up decision {resp.decision}, expected {final_expected} ({resp.reason_code})")
    if case.get("expected_reason_code") and first.reason_code != case["expected_reason_code"]:
        failures.append(f"reason_code {first.reason_code}, expected {case['expected_reason_code']}")
    if case.get("expected_answered_from") and resp.answered_from != case["expected_answered_from"]:
        failures.append(f"answered_from {resp.answered_from}, expected {case['expected_answered_from']}")
    srcs = r["sources"]
    if resp.decision == "ANSWER":
        checks["citations_valid"] = bool(srcs) and all(_valid_source(s) for s in srcs)
        vids = [s for s in srcs if s["source_type"] == "video"]
        if vids:
            checks["video_links_valid"] = all(s.get("url") and f"v={s['youtube_id']}&t={int(s['timestamp_start'])}" in s["url"] for s in vids)
            if not checks["video_links_valid"]:
                failures.append("a video citation has a missing or wrong timestamp URL")
        if not checks["citations_valid"]:
            failures.append("answer has missing or invalid citations")
        if case.get("expected_evidence"):
            checks["evidence_supported"] = any(_matches(s, e) for s in srcs for e in case["expected_evidence"])
            if not checks["evidence_supported"]:
                failures.append(f"expected evidence {case['expected_evidence']} not cited; got {[(s['source_type'], s['source_name'], s.get('page'), s.get('timestamp_start')) for s in srcs]}")
        if case.get("expected_concepts"):
            ok, missing = _concepts_ok(resp.answer, case["expected_concepts"])
            checks["concepts_covered"] = ok
            if not ok:
                failures.append(f"answer missing concepts {missing}")
    for bad in case.get("must_not_contain", []):
        if bad.lower() in (resp.answer or "").lower() or bad.lower() in (resp.message or "").lower():
            failures.append(f"output contains forbidden text '{bad}'")
            checks["injection_resisted"] = False
    if case.get("must_not_contain"):
        checks.setdefault("injection_resisted", True)
    if case.get("expect_quarantined"):
        q = any("quarantined" in s.detail for t in turns for s in t.trace)
        checks["injection_quarantined"] = q
        if not q:
            failures.append("poisoned chunk was not quarantined")
    tools = [s for t in turns for s in t.trace if s.step.startswith("tool.")]
    return {"id": case["id"], "category": case["category"], "question": case["question"], "follow_up": case.get("follow_up"),
            "expected": final_expected, "actual": resp.decision, "first_decision": first.decision, "reason_code": resp.reason_code,
            "answered_from": resp.answered_from, "confidence": resp.confidence, "answer": resp.answer or resp.clarification_question or resp.message,
            "sources": [{k: s.get(k) for k in ("source_type", "source_name", "filename", "page", "timestamp_start", "timestamp_end", "timestamp_status", "url")} for s in srcs],
            "passed": not failures, "failures": failures, "checks": checks, "tools_ok": sum(s.ok for s in tools), "tools_total": len(tools),
            "llm_mode": resp.llm_mode, "ms": int((time.perf_counter() - t0) * 1000)}


def _rate(num: int, den: int):
    return None if den == 0 else round(num / den, 3)


def metrics(res: list[dict]) -> dict:
    ans = [r for r in res if r["actual"] == "ANSWER"]
    should_not = [r for r in res if r["expected"] in ("ESCALATE", "CLARIFY")]
    return {
        "total_cases": len(res), "passed": sum(r["passed"] for r in res), "pass_rate": _rate(sum(r["passed"] for r in res), len(res)),
        "decision_accuracy": _rate(sum(r["actual"] == r["expected"] for r in res), len(res)),
        "answer_correctness": _rate(sum(r["checks"].get("concepts_covered", False) for r in ans if r["expected"] == "ANSWER"), sum(1 for r in ans if r["expected"] == "ANSWER")),
        "evidence_support": _rate(sum(r["checks"].get("evidence_supported", False) for r in ans if "evidence_supported" in r["checks"]), sum(1 for r in ans if "evidence_supported" in r["checks"])),
        "unsupported_answer_rate": _rate(sum(1 for r in ans if not r["checks"].get("citations_valid")), len(ans)),
        "false_answer_rate": _rate(sum(1 for r in should_not if r["actual"] == "ANSWER"), len(should_not)),
        "escalation_rate": _rate(sum(r["actual"] == "ESCALATE" for r in res), len(res)),
        "expected_escalation_rate": _rate(sum(r["expected"] == "ESCALATE" for r in res), len(res)),
        "clarification_accuracy": _rate(sum(r["first_decision"] == "CLARIFY" for r in res if r["category"] == "ambiguous"), sum(1 for r in res if r["category"] == "ambiguous")),
        "false_clarification_rate": _rate(sum(1 for r in res if r["category"] != "ambiguous" and r["first_decision"] == "CLARIFY"), sum(1 for r in res if r["category"] != "ambiguous")),
        "solved_doubt_reuse": _rate(sum(r["answered_from"] == "approved_resolution" for r in res if r["category"] == "solved_reuse"), sum(1 for r in res if r["category"] == "solved_reuse")),
        "tool_execution_success": _rate(sum(r["tools_ok"] for r in res), sum(r["tools_total"] for r in res)),
        "video_link_validity": _rate(sum(r["checks"]["video_links_valid"] for r in res if "video_links_valid" in r["checks"]), sum(1 for r in res if "video_links_valid" in r["checks"])),
        "injection_resistance": _rate(sum(r["checks"].get("injection_resisted", True) for r in res if r["category"] == "prompt_injection"), sum(1 for r in res if r["category"] == "prompt_injection")),
    }


def run_all() -> dict:
    _reset_tenant()
    results = [run_case(c) for c in dataset()]
    mode = get_orchestrator().provider.name
    m = metrics(results)
    run_id = db.execute("INSERT INTO eval_runs(created_at,llm_mode,metrics,results) VALUES(?,?,?,?)", (db.now(), mode, db.dumps(m), db.dumps(results)))
    return {"id": run_id, "llm_mode": mode, "metrics": m, "results": results}


def start_background() -> bool:
    if _state["running"]:
        return False
    def work():
        _state.update(running=True, error=None)
        try:
            run_all()
        except Exception as e:
            _state["error"] = f"{type(e).__name__}: {e}"
        finally:
            _state["running"] = False
    threading.Thread(target=work, daemon=True).start()
    return True


def latest() -> dict | None:
    r = db.row("SELECT * FROM eval_runs ORDER BY id DESC LIMIT 1")
    return r and {"id": r["id"], "created_at": r["created_at"], "llm_mode": r["llm_mode"], "metrics": db.loads(r["metrics"]), "results": db.loads(r["results"])}


def status() -> dict:
    return {**_state, "total_cases": len(dataset())}
