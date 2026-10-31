"use client";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import Shell from "@/components/Shell";
import AgentTimeline from "@/components/AgentTimeline";
import { api, fmtTime } from "@/lib/api";
import { demoApi, type DemoStatus, type TestDef, type TestResult } from "@/lib/demo";
import { FULL_AGENTS, INGEST_AGENTS, type AgentEvent } from "@/lib/events";

export default function Page() {
  const [defs, setDefs] = useState<TestDef[]>([]);
  const [results, setResults] = useState<Record<string, TestResult>>({});
  const [st, setSt] = useState<DemoStatus | null>(null);
  const [running, setRunning] = useState<number | null>(null);
  const [all, setAll] = useState(false);
  const [err, setErr] = useState("");
  const [token, setToken] = useState("");

  const load = useCallback(() => Promise.all([demoApi<{ tests: TestDef[]; results: Record<string, TestResult> }>("/tests"), demoApi<DemoStatus>("/status")])
    .then(([t, s]) => { setDefs(t.tests); setResults(t.results); setSt(s); setErr(""); }).catch((e) => setErr(e.message)), []);
  useEffect(() => { setToken(sessionStorage.getItem("dl-admin-token") ?? ""); load(); }, [load]);

  async function run(n: number) {
    setRunning(n); setErr("");
    try { const r = await demoApi<TestResult>(`/tests/${n}/run`, { method: "POST" }); setResults((p) => ({ ...p, [n]: r })); }
    catch (e: any) { setErr(`Test ${n}: ${e.message}`); }
    finally { setRunning(null); }
  }
  async function runAll() { setAll(true); for (const d of defs) await run(d.id); setAll(false); }
  const passed = Object.values(results).filter((r) => r.status === "pass").length;

  return (
    <Shell>
      <p className="label">Jury demo</p>
      <h1 className="mt-1 text-3xl font-semibold tracking-tight">Demonstration scenarios</h1>
      <p className="mt-1 max-w-3xl text-muted">Each scenario runs the real agent, memory, ingestion and retrieval code against the Operating Systems knowledge base. Pass/fail is computed from the actual response, database, vector index and recorded events — nothing is pre-filled.</p>
      <div className="card mt-4 flex flex-wrap items-center gap-4 p-4 text-sm">
        <div><span className="label">Demo state</span><br /><b>{st?.state ?? "…"}</b>{st?.last_reset && <span className="text-muted"> · reset {new Date(st.last_reset.ts * 1000).toLocaleTimeString()}</span>}</div>
        <div><span className="label">Result</span><br /><b>{passed}/{defs.length || 10} passed</b></div>
        {st?.auth === "token" && <input type="password" className="input w-48" placeholder="Admin token" value={token} onChange={(e) => { setToken(e.target.value); sessionStorage.setItem("dl-admin-token", e.target.value); }} onBlur={load} />}
        <div className="ml-auto flex gap-2"><Link href="/admin" className="btn">Reset demo data (Admin)</Link><button className="btn btn-primary" onClick={runAll} disabled={running !== null || !defs.length}>{all ? "Running all…" : "Run all 10"}</button></div>
        <p className="w-full text-xs text-muted">Run in order (4 needs 3, 5 needs 4, 8 needs 7, 9 and 10 need earlier runs). For a clean, repeatable run, reset demo data first. Each question calls the LLM provider; when it is slow or down, the answer comes from the labelled local fallback and a scenario can take up to ~40 s.</p>
      </div>
      {err && <p className="mt-3 rounded-lg bg-red-50 p-3 text-sm text-red-800">{err}</p>}
      <div className="mt-4 space-y-4">{defs.map((d) => <TestCard key={d.id} d={d} r={results[d.id]} busy={running === d.id} disabled={running !== null} run={() => run(d.id)} />)}</div>
    </Shell>
  );
}

function Field({ l, children }: { l: string; children: React.ReactNode }) { return <div><p className="label">{l}</p><p className="mt-0.5 text-sm">{children}</p></div>; }

function TestCard({ d, r, busy, disabled, run }: { d: TestDef; r?: TestResult; busy: boolean; disabled: boolean; run: () => void }) {
  const [open, setOpen] = useState(false);
  const [timelines, setTimelines] = useState<Record<string, AgentEvent[]> | null>(null);
  const showHist = () => {
    setOpen(!open);
    if (!open && r) Promise.all(r.run_ids.map((id) => api<{ events: AgentEvent[] }>(`/api/v1/events/runs/${id}`).then((x) => [id, x.events] as const).catch(() => [id, []] as const))).then((x) => setTimelines(Object.fromEntries(x)));
  };
  useEffect(() => { setTimelines(null); setOpen(false); }, [r?.ran_at]);
  const a = r?.actual ?? {};
  const srcs: any[] = a.sources ?? a.turn2?.sources ?? a.probe?.sources ?? [];
  return (
    <div className={`card p-5 ${r?.status === "fail" ? "border-red-300" : r?.status === "pass" ? "border-accent/50" : ""}`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2"><span className="grid h-7 w-7 place-items-center rounded-full bg-bg text-sm font-semibold">{d.id}</span><p className="text-lg font-medium">{d.name}</p><span className="pill bg-slate-100 text-slate-700">{d.role}</span></div>
        <div className="flex items-center gap-2">
          {busy ? <span className="pill animate-pulse bg-accent-soft text-accent">Running…</span> : r ? <span className={`pill ${r.status === "pass" ? "bg-accent text-white" : "bg-red-600 text-white"}`}>{r.status === "pass" ? "PASS" : "FAIL"}</span> : <span className="pill bg-slate-100 text-slate-500">Not run</span>}
          <button className="btn text-xs" disabled={disabled} onClick={run}>{r ? "Re-run" : "Run"}</button>
        </div>
      </div>
      <div className="mt-3 grid gap-3 md:grid-cols-2">
        <Field l="Student question / admin action">{d.input}</Field><Field l="Expected final decision">{d.decision}</Field>
        <Field l="Expected agent workflow">{d.workflow}</Field><Field l="Expected citations / evidence">{d.evidence}</Field>
        <Field l="Expected database changes">{d.db}</Field>
      </div>
      {r && (
        <div className="mt-4 border-t border-line pt-4">
          <p className="label mb-1.5">Actual result · {r.ms} ms · {new Date(r.ran_at * 1000).toLocaleTimeString()}</p>
          <ul className="space-y-1">{r.checks.map((c, i) => <li key={i} className="flex gap-2 text-sm"><span className={c.ok ? "text-accent" : "text-red-700"}>{c.ok ? "✓" : "✕"}</span><span><span className={c.ok ? "" : "font-medium text-red-800"}>{c.name}</span>{c.detail && <span className="text-muted"> — {c.detail}</span>}</span></li>)}</ul>
          <div className="mt-3 flex flex-wrap gap-1.5 text-xs">{Object.keys(r.db_diff).length ? Object.entries(r.db_diff).map(([k, v]) => <span key={k} className="pill bg-slate-100 text-slate-700">{k.replaceAll("_", " ")} {v > 0 ? "+" : ""}{v}</span>) : <span className="text-muted">No database changes observed.</span>}</div>
          {(a.answer ?? a.turn2?.answer ?? a.probe?.answer) && <p className="mt-3 whitespace-pre-wrap rounded-lg bg-bg p-3 text-sm"><span className="label">Answer ({a.llm_mode ?? ""})</span><br />{a.answer ?? a.turn2?.answer ?? a.probe?.answer}</p>}
          {a.turn1?.clarification_question && <p className="mt-3 rounded-lg bg-amber-50 p-3 text-sm"><span className="label">Clarification asked</span><br />{a.turn1.clarification_question}</p>}
          {srcs.length > 0 && <div className="mt-2 flex flex-wrap gap-1.5">{srcs.map((s, i) => <span key={i} className="rounded-md border border-line bg-white px-2 py-1 text-xs">{s.source_type === "video" ? `▶ ${s.source_name.slice(0, 30)} · ${fmtTime(s.timestamp_start)}–${fmtTime(s.timestamp_end)} · ${s.timestamp_status}` : s.source_type === "pdf" ? `📄 ${s.filename} · p.${s.page}` : "✓ Teacher-approved resolution"}</span>)}</div>}
          {a.hits && <ul className="mt-2 space-y-1">{a.hits.map((h: any, i: number) => <li key={i} className="rounded-md border border-line bg-white p-2 text-xs"><b>{h.filename} · p.{h.page}</b> · similarity {h.similarity}<p className="text-muted">{h.excerpt}…</p></li>)}</ul>}
          {a.receipt?.vector_ids && <p className="mt-2 text-xs text-muted">Receipt: resolution #{a.receipt.resolution_id}, indexed={String(a.receipt.indexed)}, vectors {a.receipt.vector_ids.join(", ")}</p>}
          {(a.pages != null) && <p className="mt-2 text-xs text-muted">{a.pages} pages · {a.chunks} chunks · {a.vectors} vectors · status {a.status}</p>}
          {r.run_ids.length > 0 && (
            <div className="mt-3"><button className="text-sm text-accent hover:underline" onClick={showHist}>{open ? "Hide" : "Show"} actual execution history ({r.run_ids.length} run{r.run_ids.length > 1 ? "s" : ""})</button>
              {open && (timelines ? Object.entries(timelines).map(([id, ev]) => <div key={id} className="mt-2"><p className="mb-1 flex items-center gap-2 text-xs text-muted"><span className="font-mono">{id}</span><Link className="text-accent hover:underline" href={`/agents?run=${id}`}>Open in orchestration view ↗</Link></p><AgentTimeline events={ev} agents={FULL_AGENTS} /></div>) : <p className="mt-2 text-sm text-muted">Loading…</p>)}
            </div>
          )}
          {d.id === 7 && <IngestHistory />}
        </div>
      )}
    </div>
  );
}

function IngestHistory() {
  const [ev, setEv] = useState<AgentEvent[] | null>(null);
  useEffect(() => { api<{ events: AgentEvent[] }>("/api/v1/ingestion/demo-pdf-thrashing/events").then((x) => setEv(x.events)).catch(() => setEv([])); }, []);
  return ev?.length ? <div className="mt-3"><p className="label mb-1">Ingestion stages (recorded)</p><AgentTimeline events={ev} agents={INGEST_AGENTS} /></div> : null;
}
