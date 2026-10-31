"use client";
import { useCallback, useEffect, useState } from "react";
import Shell from "@/components/Shell";
import Link from "next/link";
import AgentTimeline from "@/components/AgentTimeline";
import { api, type Resource, type Subject } from "@/lib/api";
import { INGEST_AGENTS, type AgentEvent } from "@/lib/events";

const badge = (s: string) => s === "indexed" ? "bg-accent-soft text-accent" : s === "failed" ? "bg-red-100 text-red-800" : s === "no_transcript" ? "bg-slate-200 text-slate-700" : "bg-amber-100 text-amber-800";

export default function Admin() {
  const [cat, setCat] = useState<Subject[]>([]);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const load = useCallback(() => api<Subject[]>("/api/v1/catalog").then(setCat).catch((e) => setMsg({ ok: false, text: e.message })), []);
  useEffect(() => { load(); }, [load]);
  const resources = cat.flatMap((s) => s.topics.flatMap((t) => t.resources.map((r) => ({ ...r, topic: t.name, subject: s.name }))));
  const busy = resources.some((r) => r.status === "pending" || r.status === "processing");
  useEffect(() => { if (!busy) return; const t = setInterval(load, 2000); return () => clearInterval(t); }, [busy, load]);
  const run = async (fn: () => Promise<unknown>, ok: string) => { try { await fn(); setMsg({ ok: true, text: ok }); await load(); } catch (e: any) { setMsg({ ok: false, text: e.message }); } };

  return (
    <Shell>
      <p className="label">Admin · content management</p>
      <h1 className="mt-1 text-3xl font-semibold tracking-tight">Course content</h1>
      {msg && <p className={`mt-4 rounded-lg p-3 text-sm ${msg.ok ? "bg-accent-soft text-accent" : "bg-red-50 text-red-800"}`}>{msg.text}</p>}
      <Stats />
      <div className="mt-6 grid gap-4 lg:grid-cols-2">
        <SubjectForm run={run} />
        <TopicForm cat={cat} run={run} />
        <VideoForm cat={cat} run={run} />
        <PdfForm cat={cat} run={run} />
      </div>
      <h2 className="mt-10 text-lg font-semibold tracking-tight">Resources & processing status</h2>
      <div className="card mt-3 overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-line text-xs text-muted"><tr><th className="p-3">Resource</th><th>Topic</th><th>Origin</th><th>Status</th><th className="pr-3 text-right">Actions</th></tr></thead>
          <tbody className="divide-y divide-line">
            {resources.map((r) => <Row key={r.id} r={r} run={run} />)}
          </tbody>
        </table>
      </div>
      <RunMonitor />
      <PolicyEditor />
    </Shell>
  );
}

type Run = (fn: () => Promise<unknown>, ok: string) => Promise<void>;
function Row({ r, run }: { r: Resource & { topic: string }; run: Run }) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [segOpen, setSegOpen] = useState(false);
  const [segs, setSegs] = useState("");
  const [pipe, setPipe] = useState(false);
  const live = r.status === "pending" || r.status === "processing";
  const upload = (f: File | undefined) => { if (!f) return; const fd = new FormData(); fd.append("file", f); run(() => api(`/api/v1/resources/${r.id}/transcript/file`, { method: "POST", body: fd }), "Transcript uploaded and processed."); };
  return (
    <>
      <tr className="align-top">
        <td className="p-3"><p className="font-medium">{r.type === "video" ? "▶" : "📄"} {r.title}</p><p className="text-xs text-muted">{r.status_detail}</p></td>
        <td>{r.topic}</td>
        <td className="text-xs text-muted">{r.type === "video" ? `video; transcript: ${r.transcript_origin ?? "none"}` : r.origin}</td>
        <td><span className={`pill ${badge(r.status)}`}>{r.status.replace("_", " ")}{r.status === "indexed" ? ` · ${r.chunk_count}` : ""}</span></td>
        <td className="space-x-1 whitespace-nowrap pr-3 text-right">
          {r.type === "video" && <><button className="btn text-xs" onClick={() => run(() => api(`/api/v1/resources/${r.id}/transcript/fetch`, { method: "POST" }), "Transcript fetch attempted — check status.")}>Fetch captions</button>
            <button className="btn text-xs" onClick={() => setOpen(!open)}>Add transcript</button>
            <button className="btn text-xs" onClick={() => setSegOpen(!segOpen)}>Import segments</button></>}
          <button className="btn text-xs" onClick={() => setPipe(!pipe)}>Pipeline</button>
          <button className="btn text-xs" onClick={() => run(() => api(`/api/v1/resources/${r.id}/reindex`, { method: "POST" }), "Reindex finished — check status.")}>Reindex</button>
        </td>
      </tr>
      {(pipe || live) && <tr><td colSpan={5} className="bg-bg p-3"><Pipeline rid={r.id} status={r.status} /></td></tr>}
      {segOpen && <tr><td colSpan={5} className="bg-bg p-3">
        <p className="mb-1 text-xs text-muted">JSON array of segments: <code>{`{title, start, end, explanation, topic?, subtopic?, keywords?, questions?, transcript_text?, verification_status: "verified"|"unverified"}`}</code>. Unverified timestamps are never shown to students as exact citations. Re-importing updates in place.</p>
        <textarea className="input min-h-28 font-mono text-xs" value={segs} onChange={(e) => setSegs(e.target.value)} />
        <button className="btn btn-primary mt-2 text-xs" disabled={!segs.trim()} onClick={() => run(async () => { const res: any = await api(`/api/v1/resources/${r.id}/segments`, { method: "POST", json: JSON.parse(segs) }); setSegs(""); setSegOpen(false); alert(`Segments: ${res.segments_total} total, ${res.segments_embedded} newly embedded, ${res.segments_reused} reused`); }, "Segments imported and indexed.")}>Validate & index</button>
      </td></tr>}
      {open && <tr><td colSpan={5} className="bg-bg p-3">
        <p className="mb-1 text-xs text-muted">Paste timestamped lines (<code>[01:25] text</code>), SRT/VTT, or JSON <code>[{`{start,end,text}`}]</code> — or upload a file.</p>
        <textarea className="input min-h-24 font-mono text-xs" value={text} onChange={(e) => setText(e.target.value)} />
        <div className="mt-2 flex items-center gap-2"><button className="btn btn-primary text-xs" disabled={!text.trim()} onClick={() => run(async () => { await api(`/api/v1/resources/${r.id}/transcript`, { method: "POST", json: { text } }); setText(""); setOpen(false); }, "Transcript indexed.")}>Save & index</button>
          <input type="file" accept=".txt,.srt,.vtt,.json" className="text-xs" onChange={(e) => upload(e.target.files?.[0])} /></div>
      </td></tr>}
    </>
  );
}

function Box({ title, children }: { title: string; children: React.ReactNode }) { return <div className="card space-y-2 p-4"><p className="font-medium">{title}</p>{children}</div>; }

function SubjectForm({ run }: { run: Run }) {
  const [name, setName] = useState(""); const [d, setD] = useState("");
  return <Box title="Add subject"><input className="input" placeholder="Name" value={name} onChange={(e) => setName(e.target.value)} /><input className="input" placeholder="Description" value={d} onChange={(e) => setD(e.target.value)} />
    <button className="btn btn-primary" disabled={!name.trim()} onClick={() => run(async () => { await api("/api/v1/subjects", { method: "POST", json: { name, description: d } }); setName(""); setD(""); }, "Subject added.")}>Add subject</button></Box>;
}
function TopicForm({ cat, run }: { cat: Subject[]; run: Run }) {
  const [s, setS] = useState(""); const [name, setName] = useState("");
  return <Box title="Add topic"><select className="input" value={s} onChange={(e) => setS(e.target.value)}><option value="">Select subject…</option>{cat.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}</select>
    <input className="input" placeholder="Topic name" value={name} onChange={(e) => setName(e.target.value)} />
    <button className="btn btn-primary" disabled={!s || !name.trim()} onClick={() => run(async () => { await api("/api/v1/topics", { method: "POST", json: { subject_id: s, name } }); setName(""); }, "Topic added.")}>Add topic</button></Box>;
}
function Pick({ cat, v, set }: { cat: Subject[]; v: { s: string; t: string }; set: (x: { s: string; t: string }) => void }) {
  const topics = cat.find((x) => x.id === v.s)?.topics ?? [];
  return <div className="grid grid-cols-2 gap-2"><select className="input" value={v.s} onChange={(e) => set({ s: e.target.value, t: "" })}><option value="">Subject…</option>{cat.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}</select>
    <select className="input" value={v.t} onChange={(e) => set({ ...v, t: e.target.value })}><option value="">Topic…</option>{topics.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}</select></div>;
}
function VideoForm({ cat, run }: { cat: Subject[]; run: Run }) {
  const [p, setP] = useState({ s: "", t: "" }); const [url, setUrl] = useState(""); const [title, setTitle] = useState("");
  return <Box title="Add YouTube video"><Pick cat={cat} v={p} set={setP} /><input className="input" placeholder="https://www.youtube.com/watch?v=…" value={url} onChange={(e) => setUrl(e.target.value)} /><input className="input" placeholder="Title (optional — fetched from YouTube if empty)" value={title} onChange={(e) => setTitle(e.target.value)} />
    <button className="btn btn-primary" disabled={!p.t || !url.trim()} onClick={() => run(async () => { await api("/api/v1/resources/video", { method: "POST", json: { subject_id: p.s, topic_id: p.t, url, title: title || null } }); setUrl(""); setTitle(""); }, "Video embedded. It is not citable until a transcript is indexed.")}>Add video</button></Box>;
}
function PdfForm({ cat, run }: { cat: Subject[]; run: Run }) {
  const [p, setP] = useState({ s: "", t: "" }); const [file, setFile] = useState<File | null>(null); const [title, setTitle] = useState("");
  return <Box title="Upload PDF notes"><Pick cat={cat} v={p} set={setP} /><input className="input" placeholder="Title" value={title} onChange={(e) => setTitle(e.target.value)} /><input type="file" accept="application/pdf,.pdf" className="text-sm" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
    <button className="btn btn-primary" disabled={!p.t || !file} onClick={() => run(async () => { const fd = new FormData(); fd.append("file", file!); fd.append("subject_id", p.s); fd.append("topic_id", p.t); fd.append("title", title); await api("/api/v1/resources/pdf", { method: "POST", body: fd }); setFile(null); setTitle(""); }, "PDF uploaded; processing started.")}>Upload & index</button></Box>;
}

function PolicyEditor() {
  const [cfg, setCfg] = useState<any>(null); const [msg, setMsg] = useState("");
  useEffect(() => { api("/api/v1/config").then(setCfg).catch(() => {}); }, []);
  if (!cfg) return null;
  const th = (k: string, v: number) => setCfg({ ...cfg, thresholds: { ...cfg.thresholds, [k]: v } });
  const toggle = (key: "sources" | "tools", v: string) => setCfg({ ...cfg, [key]: cfg[key].includes(v) ? cfg[key].filter((x: string) => x !== v) : [...cfg[key], v] });
  return (
    <section className="mt-10">
      <h2 className="text-lg font-semibold tracking-tight">Agent policy · {cfg.name}</h2>
      <p className="text-sm text-muted">The Operating Systems tutor is just this configuration plus its knowledge base — the agent engine itself is domain-independent.</p>
      <div className="card mt-3 grid gap-5 p-5 lg:grid-cols-2">
        <div className="space-y-3 lg:col-span-2"><p className="label">Instructions</p><textarea className="input min-h-20" value={cfg.instructions} onChange={(e) => setCfg({ ...cfg, instructions: e.target.value })} /></div>
        <div className="space-y-2"><p className="label">Confidence & evidence thresholds</p>
          {Object.entries(cfg.thresholds).map(([k, v]) => <label key={k} className="flex items-center justify-between gap-3 text-sm"><span>{k.replaceAll("_", " ")}</span><input type="number" step="0.01" className="input w-24" value={v as number} onChange={(e) => th(k, Number(e.target.value))} /></label>)}</div>
        <div className="space-y-3">
          <div><p className="label mb-1">Knowledge sources</p>{["pdf", "video", "resolution"].map((s) => <label key={s} className="mr-4 text-sm"><input type="checkbox" checked={cfg.sources.includes(s)} onChange={() => toggle("sources", s)} /> {s}</label>)}</div>
          <div><p className="label mb-1">Tools</p>{["search_knowledge_base", "search_solved_doubts", "create_escalation", "save_approved_resolution"].map((s) => <label key={s} className="block text-sm"><input type="checkbox" checked={cfg.tools.includes(s)} onChange={() => toggle("tools", s)} /> {s}</label>)}</div>
          <div><p className="label mb-1">Escalate when</p>{(["on_no_evidence", "on_contradiction", "on_low_confidence"] as const).map((k) => <label key={k} className="block text-sm"><input type="checkbox" checked={cfg.escalation[k]} onChange={() => setCfg({ ...cfg, escalation: { ...cfg.escalation, [k]: !cfg.escalation[k] } })} /> {k.replaceAll("_", " ")}</label>)}</div>
          <label className="block text-sm"><input type="checkbox" checked={cfg.human_approval.required_for_memory} disabled /> Teacher approval required for trusted memory (enforced)</label>
          <label className="block text-sm"><input type="checkbox" checked={cfg.clarification_enabled} onChange={() => setCfg({ ...cfg, clarification_enabled: !cfg.clarification_enabled })} /> Allow clarifying questions</label>
        </div>
        <div className="flex items-center gap-3 lg:col-span-2"><button className="btn btn-primary" onClick={async () => { try { setCfg(await api("/api/v1/config", { method: "PUT", json: cfg })); setMsg("Saved."); } catch (e: any) { setMsg(e.message); } }}>Save policy</button><span className="text-sm text-muted">{msg}</span></div>
      </div>
    </section>
  );
}

function Stats() {
  const [s, setS] = useState<any>(null);
  const [err, setErr] = useState("");
  useEffect(() => { const l = () => api("/api/v1/admin/stats").then((x) => { setS(x); setErr(""); }).catch((e) => setErr(e.message)); l(); const t = setInterval(l, 5000); return () => clearInterval(t); }, []);
  if (err) return <p className="mt-4 rounded-lg bg-red-50 p-3 text-sm text-red-800">Statistics unavailable: {err}</p>;
  if (!s) return null;
  const esc = s.escalations ?? {};
  const cards: [string, string | number, string?][] = [
    ["Documents", `${s.pdfs} PDF · ${s.videos} video`, `${Object.entries(s.resources).map(([k, v]) => `${v} ${k.replace("_", " ")}`).join(", ")}`],
    ["Chunks / vectors", `${s.chunks} / ${s.vectors ?? "n/a"}`, `${s.segments} lecture segments`],
    ["Trusted memory", s.trusted_resolutions, `${esc.pending ?? 0} pending · ${esc.rejected ?? 0} rejected`],
    ["Agent runs", s.runs.completed, `${s.runs.by_decision.ANSWER} answer · ${s.runs.by_decision.CLARIFY} clarify · ${s.runs.by_decision.ESCALATE} escalate`],
    ["Failures", s.runs.failed, `${s.runs.llm_fallbacks} run(s) used local fallback${s.runs.avg_ms ? ` · avg ${s.runs.avg_ms} ms` : ""}`],
    ["Students", s.active_students, "distinct askers (no accounts in this build)"],
  ];
  return (
    <div className="mt-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-6">
      {cards.map(([l, v, sub]) => <div key={l} className="card p-3"><p className="label">{l}</p><p className="mt-1 text-xl font-semibold">{v}</p>{sub && <p className="mt-0.5 text-[11px] text-muted">{sub}</p>}</div>)}
      <p className="text-xs text-muted sm:col-span-2 lg:col-span-6">Computed live from the database and vector store (recent-run window: last {s.runs.recent_window}). Evaluation results: <Link href="/evaluation" className="text-accent hover:underline">Evaluation page</Link>.</p>
    </div>
  );
}

function Pipeline({ rid, status }: { rid: string; status: string }) {
  const [ev, setEv] = useState<AgentEvent[] | null>(null);
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<any[] | null>(null);
  const [err, setErr] = useState("");
  useEffect(() => {
    const l = () => api<{ events: AgentEvent[] }>(`/api/v1/ingestion/${rid}/events`).then((x) => setEv(x.events)).catch(() => setEv([]));
    l();
    if (status !== "pending" && status !== "processing") return;
    const t = setInterval(l, 1500);
    return () => clearInterval(t);
  }, [rid, status]);
  const search = () => api<any[]>(`/api/v1/resources/${rid}/search?q=${encodeURIComponent(q)}`).then((h) => { setHits(h); setErr(""); }).catch((e) => setErr(e.message));
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <div>
        <p className="label mb-1.5">Processing stages (recorded events)</p>
        {ev === null ? <p className="text-sm text-muted">Loading…</p> : ev.length ? <AgentTimeline events={ev} agents={INGEST_AGENTS} live={status === "pending" || status === "processing"} />
          : <p className="text-sm text-muted">{status === "pending" || status === "processing" ? "Waiting for the processing worker to start…" : "No ingestion run recorded for this resource yet (it predates event recording). Use Reindex to record one."}</p>}
      </div>
      <div>
        <p className="label mb-1.5">Is it searchable? (vector search on this resource only)</p>
        <div className="flex gap-2"><input className="input" placeholder="Type a question this material should answer…" value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === "Enter" && q.trim() && search()} /><button className="btn" disabled={!q.trim()} onClick={search}>Search</button></div>
        {err && <p className="mt-2 text-sm text-red-700">{err}</p>}
        {hits && (hits.length ? <ul className="mt-2 space-y-1.5">{hits.map((h, i) => <li key={i} className="rounded-md border border-line bg-white p-2 text-xs"><b>{h.page ? `p.${h.page}` : h.ts_start != null ? `${Math.floor(h.ts_start / 60)}:${String(Math.floor(h.ts_start % 60)).padStart(2, "0")}` : ""}</b> · similarity {h.similarity.toFixed(2)}{h.heading ? ` · ${h.heading}` : ""}<p className="mt-1 text-muted">{h.excerpt}…</p></li>)}</ul> : <p className="mt-2 text-sm text-muted">No passages found — the resource has no indexed vectors.</p>)}
      </div>
    </div>
  );
}

function RunMonitor() {
  const [runs, setRuns] = useState<any[]>([]);
  const [err, setErr] = useState("");
  useEffect(() => { const l = () => api<any[]>("/api/v1/events/runs?limit=12").then((r) => { setRuns(r); setErr(""); }).catch((e) => setErr(e.message)); l(); const t = setInterval(l, 5000); return () => clearInterval(t); }, []);
  return (
    <section className="mt-10">
      <div className="flex items-end justify-between"><h2 className="text-lg font-semibold tracking-tight">Agent execution monitor</h2><Link href="/agents" className="text-sm text-accent hover:underline">Open orchestration view ↗</Link></div>
      {err && <p className="mt-2 rounded-lg bg-red-50 p-3 text-sm text-red-800">{err}</p>}
      <div className="card mt-3 overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-line text-xs text-muted"><tr><th className="p-3">Question</th><th>Decision</th><th>Mode</th><th>Time</th><th>Errors</th><th className="pr-3"></th></tr></thead>
          <tbody className="divide-y divide-line">
            {runs.map((r) => <tr key={r.run_id}><td className="max-w-xs truncate p-3">{r.question ?? "(continued)"}</td><td>{r.decision ?? "—"}</td><td className="text-xs text-muted">{r.llm_mode ?? ""}{r.fallback ? " · fallback" : ""}</td><td className="text-xs">{r.total_ms != null ? `${r.total_ms} ms` : ""}</td>
              <td>{r.failed ? <span className="pill bg-red-100 text-red-800">failed step</span> : <span className="text-xs text-muted">none</span>}</td><td className="pr-3 text-right"><Link className="text-accent hover:underline" href={`/agents?run=${r.run_id}`}>Inspect</Link></td></tr>)}
            {!runs.length && <tr><td colSpan={6} className="p-4 text-center text-sm text-muted">No agent runs recorded yet.</td></tr>}
          </tbody>
        </table>
      </div>
    </section>
  );
}
