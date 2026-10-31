"use client";
import { Suspense, useCallback, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import Shell from "@/components/Shell";
import AgentTimeline, { STATUS_TONE, StatusDot } from "@/components/AgentTimeline";
import { api } from "@/lib/api";
import { agentStatus, FULL_AGENTS, type AgentEvent, type Status } from "@/lib/events";

type RunSummary = { run_id: string; started_at: number; question: string | null; decision: string | null; confidence: number | null; llm_mode: string | null; total_ms: number | null; failed: boolean; fallback: boolean; escalation_id: number | null; events: number; learned: boolean; reused_later: boolean; teacher: string | null; reused_memory: boolean; complete: boolean };

export default function Page() {
  return <Suspense fallback={<p className="p-8 text-sm text-muted">Loading…</p>}><Agents /></Suspense>;
}

type Node = { label: string; status: Status; note?: string };

/** Derives every node's status from recorded events of the selected run; nothing here is hard-coded as "done". */
function flow(s: RunSummary, ev: AgentEvent[]): { main: Node[]; outcome: Node[]; loop: Node[] } {
  const st = (a: string) => agentStatus(ev, a);
  const has = (t: string) => ev.some((e) => e.type === t);
  const d = s.decision;
  const clar = d === "CLARIFY";
  const main: Node[] = [
    { label: "Student query", status: has("run_started") ? "completed" : "pending" },
    { label: "Orchestrator", status: s.complete ? "completed" : has("run_started") ? "running" : "pending" },
    { label: "Knowledge retrieval", status: st("retrieval"), note: clar ? "preview only" : undefined },
    { label: "Evidence verification", status: st("verification") },
    { label: "Decision agent", status: st("decision"), note: d ?? undefined },
  ];
  const outcome: Node[] = (["ANSWER", "CLARIFY", "ESCALATE"] as const).map((k) => ({ label: k, status: !d ? "pending" : d === k ? (s.failed && k === "ESCALATE" && !s.escalation_id ? "failed" : "completed") : "skipped" }));
  const esc = d === "ESCALATE";
  const rejected = s.teacher === "rejected", approved = s.teacher === "approved";
  const loop: Node[] = esc ? [
    { label: "Teacher review", status: approved || rejected ? "completed" : "waiting" },
    { label: "Approval", status: approved ? "completed" : rejected ? "skipped" : "waiting", note: rejected ? "rejected" : undefined },
    { label: "Trusted memory update", status: ev.some((e) => e.agent === "memory" && e.status === "failed") ? "failed" : s.learned ? "completed" : rejected ? "skipped" : "waiting", note: rejected ? "nothing saved" : undefined },
    { label: "Future retrieval", status: s.reused_later ? "completed" : s.learned ? "waiting" : "skipped", note: s.reused_later ? "reused by a later session" : s.learned ? "awaiting a similar question" : undefined },
  ] : [];
  return { main, outcome, loop };
}

function NodeBox({ n }: { n: Node }) {
  return (
    <div className={`flex min-w-[8.5rem] items-center gap-2 rounded-lg border bg-white px-3 py-2 transition-colors ${n.status === "running" ? "border-accent" : n.status === "failed" ? "border-red-300" : "border-line"}`}>
      <StatusDot s={n.status} />
      <div><p className="text-sm font-medium leading-tight">{n.label}</p><p className={`text-[11px] ${STATUS_TONE[n.status].text}`}>{n.note ? `${STATUS_TONE[n.status].label} · ${n.note}` : STATUS_TONE[n.status].label}</p></div>
    </div>
  );
}
const Arrow = () => <span className="select-none text-muted" aria-hidden>→</span>;
const Row = ({ nodes }: { nodes: Node[] }) => <div className="flex flex-wrap items-center gap-2">{nodes.map((n, i) => <span key={n.label} className="flex items-center gap-2">{i > 0 && <Arrow />}<NodeBox n={n} /></span>)}</div>;

function Agents() {
  const sp = useSearchParams();
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [sel, setSel] = useState<string | null>(sp.get("run"));
  const [detail, setDetail] = useState<{ summary: RunSummary; events: AgentEvent[] } | null>(null);
  const [err, setErr] = useState("");

  const loadRuns = useCallback(() => api<RunSummary[]>("/api/v1/events/runs?limit=30").then((r) => { setRuns(r); setErr(""); setSel((s) => s ?? r[0]?.run_id ?? null); }).catch((e) => setErr(e.message)), []);
  useEffect(() => { loadRuns(); const t = setInterval(loadRuns, 4000); return () => clearInterval(t); }, [loadRuns]);
  const loadDetail = useCallback(() => { if (sel) api<{ summary: RunSummary; events: AgentEvent[] }>(`/api/v1/events/runs/${sel}`).then(setDetail).catch((e) => setErr(e.message)); }, [sel]);
  useEffect(() => { setDetail(null); loadDetail(); const t = setInterval(loadDetail, 2500); return () => clearInterval(t); }, [loadDetail]);

  const f = detail ? flow(detail.summary, detail.events) : null;
  return (
    <Shell wide>
      <p className="label">Orchestration view</p>
      <h1 className="mt-1 text-3xl font-semibold tracking-tight">Agent activity</h1>
      <p className="mt-1 max-w-3xl text-muted">Every node below is derived from execution events recorded by the backend while it ran — tool calls, verification results, decisions, teacher actions and memory writes. Nothing is simulated.</p>
      <div className="mt-3 flex flex-wrap gap-2 text-xs">{(["running", "completed", "failed", "waiting", "skipped"] as Status[]).map((s) => <span key={s} className="flex items-center gap-1.5"><StatusDot s={s} />{STATUS_TONE[s].label}</span>)}</div>
      {err && <p className="mt-3 rounded-lg bg-red-50 p-3 text-sm text-red-800">Could not load events: {err}</p>}
      <div className="mt-5 grid gap-5 lg:grid-cols-[320px_minmax(0,1fr)]">
        <div className="card max-h-[75vh] overflow-y-auto">
          <p className="label border-b border-line p-3">Recent runs</p>
          {runs.map((r) => (
            <button key={r.run_id} onClick={() => setSel(r.run_id)} className={`block w-full border-b border-line p-3 text-left text-sm ${sel === r.run_id ? "bg-accent-soft" : "hover:bg-bg"}`}>
              <p className="line-clamp-2 font-medium">{r.question ?? "(continued run)"}</p>
              <p className="mt-1 flex flex-wrap items-center gap-1.5 text-[11px]">
                <span className={`pill !py-0 ${r.decision === "ANSWER" ? "bg-accent-soft text-accent" : r.decision === "CLARIFY" ? "bg-amber-100 text-amber-800" : r.decision ? "bg-slate-200 text-slate-700" : "bg-slate-100 text-slate-500"}`}>{r.decision ?? (r.complete ? "—" : "running")}</span>
                {r.learned && <span className="pill !py-0 bg-accent-soft text-accent">learned</span>}
                {r.escalation_id && !r.learned && !r.teacher && <span className="pill !py-0 bg-amber-100 text-amber-800">awaiting teacher</span>}
                {r.failed && <span className="pill !py-0 bg-red-100 text-red-800">failure</span>}
                {r.fallback && <span className="pill !py-0 bg-slate-100 text-slate-600">local fallback</span>}
                {r.total_ms != null && <span className="text-muted">{r.total_ms} ms</span>}
              </p>
            </button>
          ))}
          {!runs.length && !err && <p className="p-4 text-sm text-muted">No runs yet. Ask a question in the student workspace and it will appear here.</p>}
        </div>
        <div className="min-w-0 space-y-4">
          {!detail || !f ? <div className="card p-8 text-center text-sm text-muted">{sel ? "Loading run…" : "Select a run."}</div> : (
            <>
              {!detail.events.some((e) => e.type === "run_started") && <p className="rounded-lg bg-amber-50 p-3 text-sm text-amber-900">This timeline only holds teacher / memory events: the original agent run for this ticket was raised before execution events were recorded.</p>}
              <div className="card space-y-3 p-4">
                <p className="text-sm"><span className="label">Question</span><br />{detail.summary.question ?? "—"}</p>
                <Row nodes={f.main} />
                <div className="flex flex-wrap items-center gap-2"><Arrow /><span className="text-xs text-muted">outcome</span>{f.outcome.map((n) => <NodeBox key={n.label} n={n} />)}</div>
                {f.loop.length > 0 && <div><p className="label mb-1.5">Self-learning loop (human in the loop)</p><Row nodes={f.loop} /></div>}
                {detail.summary.reused_memory && <p className="text-sm text-accent">This run was answered from teacher-approved memory — knowledge learned in an earlier session.</p>}
              </div>
              <div className="card p-4"><p className="label mb-2">Execution events · {detail.events.length}</p><AgentTimeline events={detail.events} agents={FULL_AGENTS} /></div>
            </>
          )}
        </div>
      </div>
    </Shell>
  );
}
