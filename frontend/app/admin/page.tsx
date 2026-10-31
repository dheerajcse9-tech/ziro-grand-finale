"use client";
import { useCallback, useEffect, useState } from "react";
import Shell from "@/components/Shell";
import { api, type Resource, type Subject } from "@/lib/api";

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
      <PolicyEditor />
    </Shell>
  );
}

type Run = (fn: () => Promise<unknown>, ok: string) => Promise<void>;
function Row({ r, run }: { r: Resource & { topic: string }; run: Run }) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
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
            <button className="btn text-xs" onClick={() => setOpen(!open)}>Add transcript</button></>}
          <button className="btn text-xs" onClick={() => run(() => api(`/api/v1/resources/${r.id}/reindex`, { method: "POST" }), "Reindex finished — check status.")}>Reindex</button>
        </td>
      </tr>
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
