"""Run the user's retrieval-validation questions through the real agent and check citations against ground truth.
Expectations come from the actual PDFs (page numbers read from the documents) and the supplied segment tables."""
import json, sys
from app import db
from app.agent.orchestrator import Orchestrator
from app.agent.schemas import AgentRequest

T = "demo-university"
PM, CPU, SYN, DL, MEM = "Process-Management.pdf", "CPU-Scheduling-and-Algorithm-.pdf", "synchronization.pdf", "Deadlocks.pdf", "Memory-management-.pdf"
V1, V2, V3, V4, V5 = "2dJdHMpCLIg", "zFnrUVqtiOY", "3Eaw1SSIqRg", "rWFH6PLOIEI", "eESIFJz7mJw"
TOPICS = ["os-process-management", "os-cpu-scheduling", "os-process-synchronization", "os-process-synchronization", "os-deadlocks", "os-deadlocks", "os-memory-management", "os-memory-management", "os-memory-management", "os-memory-management", None, None, None]
USE_TOPIC = "--no-topic" not in sys.argv
# (question, acceptable PDF (filename, pages), acceptable video ids, expected decision)
CASES = [
 ("What are the five states in a process lifecycle?", [(PM, {2})], {V1}, "ANSWER"),
 ("What is the difference between preemptive and non-preemptive scheduling?", [(CPU, {2})], {V2}, "ANSWER"),
 ("What is the difference between independent and cooperative processes?", [(SYN, {1}), (PM, {7})], {V3}, "ANSWER"),
 ("What is a race condition?", [(SYN, {1})], {V3}, "ANSWER"),
 ("What are the four necessary conditions for deadlock?", [(DL, {2}), (CPU, {17})], {V4}, "ANSWER"),
 ("Explain mutual exclusion and hold and wait.", [(DL, {2, 9}), (CPU, {17}), (SYN, {2})], {V4}, "ANSWER"),
 ("What is the degree of multiprogramming?", [(PM, {4, 5}), (MEM, {2})], {V5}, "ANSWER"),
 ("Explain paging and segmentation.", [(MEM, {5, 6, 7, 8})], set(), "ANSWER"),
 ("What is the difference between FIFO and LRU page replacement?", [(MEM, {9, 10, 11})], set(), "ANSWER"),
 ("Explain virtual memory.", [(MEM, {4, 5})], set(), "ANSWER"),
 ("What is the capital of France?", [], set(), "ESCALATE"),
 ("How does the ext4 journaling file system recover after a crash?", [], set(), "ESCALATE"),
 ("Explain how TCP congestion control works", [], set(), "ESCALATE"),
]
orch, out, ok_all = Orchestrator(), [], 0
for i, (q, pdfs, vids, exp) in enumerate(CASES):
    r = orch.ask(AgentRequest(question=q, tenant_id=T, session_id=f"val-{i}-{abs(hash(q)) % 10**6}", subject_id="os" if USE_TOPIC and TOPICS[i] else None, topic_id=TOPICS[i] if USE_TOPIC else None))
    src = r.sources
    pdf_ok = (not pdfs) or any(s.filename == f and s.page in pg for s in src if s.source_type == "pdf" for f, pg in pdfs)
    vid_ok = (not vids) or any(s.youtube_id in vids for s in src if s.source_type == "video")
    url_ok = all(s.url and f"v={s.youtube_id}&t={int(s.timestamp_start)}" in s.url for s in src if s.source_type == "video")
    passed = r.decision == exp and pdf_ok and vid_ok and url_ok
    ok_all += passed
    out.append({"q": q, "expected": exp, "decision": r.decision, "reason": r.reason_code, "confidence": r.confidence, "pdf_ok": pdf_ok, "video_ok": vid_ok, "url_ok": url_ok, "passed": passed,
                "answer": (r.answer or r.message or "")[:300], "sources": [(s.source_type, s.filename or s.source_name[:30], s.page, s.timestamp_start, s.timestamp_status) for s in src]})
    print(f"[{'PASS' if passed else 'FAIL'}] {q}\n   -> {r.decision} ({r.reason_code}) conf={r.confidence} pdf_ok={pdf_ok} video_ok={vid_ok} url_ok={url_ok}")
    for s in out[-1]["sources"]: print("      ", s)
    if "-v" in sys.argv: print("      ANSWER:", out[-1]["answer"].replace("\n", " "))
print(f"\n{ok_all}/{len(CASES)} passed")
json.dump(out, open("data/retrieval_validation%s.json" % ("" if USE_TOPIC else "_no_topic"), "w"), indent=1)
