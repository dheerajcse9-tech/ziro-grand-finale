"use client";
import { useCallback, useEffect, useState } from "react";
import Shell from "@/components/Shell";
import { api, fmtTime } from "@/lib/api";

type Ev = { source_type: string; source_name: string; page?: number; timestamp_start?: number; timestamp_end?: number; similarity: number; relevant: boolean; excerpt?: string };
type Esc = { id: number; question: string; standalone_question: string; subject_id: string; topic_id: string; reason: string; evidence: Ev[]; status: string; teacher_answer?: string; teacher_note?: string; teacher_id?: string; created_at: number; resolved_at?: number };

export default function Teacher() {
  const [tab, setTab] = useState<"pending" | "resolved">("pending");
  const [items, setItems] = useState<Esc[]>([]);
  const [counts, setCounts] = useState({ pending: 0, memory: 0 });
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    try {
      const [list, pend, mem] = await Promise.all([api<Esc[]>(`/api/v1/escalations?status=${tab}`), api<Esc[]>("/api/v1/escalations?status=pending"), api<unknown[]>("/api/v1/resolutions")]);
      setItems(list); setCounts({ pending: pend.length, memory: mem.length }); setErr("");
    } catch (e: any) { setErr(e.message); }
  }, [tab]);
  useEffect(() => { load(); const t = setInterval(load, 6000); return () => clearInterval(t); }, [load]);

  return (
    <Shell>
      <p className="label">Teacher dashboard</p>
      <h1 className="mt-1 text-3xl font-semibold tracking-tight">Escalated doubts</h1>
      <p className="mt-1 text-muted">Only answers you approve enter the trusted solved-doubt memory the agent reuses.</p>
      <div className="mt-6 grid max-w-md grid-cols-2 gap-3">
        <div className="card p-4"><p className="label">Pending</p><p className="mt-1 text-3xl font-semibold">{counts.pending}</p></div>
        <div className="card p-4"><p className="label">Trusted memory</p><p className="mt-1 text-3xl font-semibold">{counts.memory}</p></div>
      </div>
      <div className="mt-6 flex gap-1 text-sm">
        {(["pending", "resolved"] as const).map((k) => <button key={k} onClick={() => setTab(k)} className={`rounded-md px-3 py-1.5 ${tab === k ? "bg-accent-soft font-medium text-accent" : "text-muted"}`}>{k === "pending" ? "Pending" : "Resolved history"}</button>)}
      </div>
      {err && <p className="mt-3 rounded-lg bg-red-50 p-3 text-sm text-red-800">{err}</p>}
      <div className="mt-3 space-y-4">
        {items.map((e) => tab === "pending" ? <Pending key={e.id} e={e} done={load} /> : <Resolved key={e.id} e={e} />)}
        {!items.length && !err && <div className="card p-8 text-center text-sm text-muted">{tab === "pending" ? "No pending doubts. Ask the tutor something it can’t answer to see one here." : "Nothing resolved yet."}</div>}
      </div>
    </Shell>
  );
}

function EvidenceList({ ev }: { ev: Ev[] }) {
  if (!ev.length) return <p className="text-sm text-muted">The agent retrieved no evidence for this question.</p>;
  return (
    <ul className="space-y-1.5">
      {ev.map((x, i) => (
        <li key={i} className="rounded-lg border border-line bg-bg p-2.5 text-xs">
          <div className="flex flex-wrap items-center gap-2"><b>{x.source_type === "video" ? `▶ ${x.source_name} · ${fmtTime(x.timestamp_start)}–${fmtTime(x.timestamp_end)}` : x.source_type === "pdf" ? `📄 ${x.source_name} · p.${x.page}` : x.source_name}</b>
            <span className="text-muted">similarity {x.similarity.toFixed(2)}</span>{!x.relevant && <span className="pill bg-slate-200 text-slate-700">below relevance threshold</span>}</div>
          {x.excerpt && <p className="mt-1 text-muted">{x.excerpt}…</p>}
        </li>
      ))}
    </ul>
  );
}

function Pending({ e, done }: { e: Esc; done: () => void }) {
  const [answer, setAnswer] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  async function act(kind: "approve" | "reject") {
    setBusy(true); setErr("");
    try { await api(`/api/v1/escalations/${e.id}/${kind}`, { method: "POST", json: kind === "approve" ? { answer, teacher_id: "teacher" } : { note, teacher_id: "teacher" } }); done(); }
    catch (x: any) { setErr(x.message); } finally { setBusy(false); }
  }
  return (
    <div className="card p-5">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div><p className="text-xs text-muted">Ticket #{e.id} · {e.subject_id ?? "—"} / {e.topic_id ?? "no topic"} · {new Date(e.created_at * 1000).toLocaleString()}</p><p className="mt-1 text-lg font-medium">{e.question}</p>
          {e.standalone_question !== e.question && <p className="text-sm text-muted">Interpreted as: {e.standalone_question}</p>}</div>
        <span className="pill bg-amber-100 text-amber-800">{e.reason.split(":")[0].replaceAll("_", " ")}</span>
      </div>
      <p className="mt-2 text-sm"><span className="label">Escalation reason</span><br />{e.reason}</p>
      <div className="mt-4"><p className="label mb-1.5">Retrieved evidence</p><EvidenceList ev={e.evidence} /></div>
      <div className="mt-4"><p className="label mb-1.5">Your answer</p>
        <textarea className="input min-h-28" value={answer} onChange={(x) => setAnswer(x.target.value)} placeholder="Write the verified answer. Once approved it is saved to trusted memory and reused for similar questions." /></div>
      <input className="input mt-2" value={note} onChange={(x) => setNote(x.target.value)} placeholder="Optional note if rejecting (shown to the student)" />
      {err && <p className="mt-2 text-sm text-red-700">{err}</p>}
      <div className="mt-3 flex gap-2">
        <button className="btn btn-primary" disabled={busy || answer.trim().length < 10} onClick={() => act("approve")}>Approve answer</button>
        <button className="btn btn-danger" disabled={busy} onClick={() => act("reject")}>Reject / close</button>
      </div>
    </div>
  );
}

function Resolved({ e }: { e: Esc }) {
  return (
    <div className="card p-5">
      <div className="flex flex-wrap items-center justify-between gap-2"><p className="font-medium">#{e.id} · {e.question}</p>
        <span className={`pill ${e.status === "approved" ? "bg-accent-soft text-accent" : "bg-red-100 text-red-800"}`}>{e.status === "approved" ? "Approved → trusted memory" : "Rejected"}</span></div>
      <p className="text-xs text-muted">{e.topic_id} · resolved {e.resolved_at ? new Date(e.resolved_at * 1000).toLocaleString() : ""} by {e.teacher_id}</p>
      {e.teacher_answer && <p className="mt-3 whitespace-pre-wrap rounded-lg bg-bg p-3 text-sm">{e.teacher_answer}</p>}
      {e.teacher_note && <p className="mt-2 text-sm text-muted">Note: {e.teacher_note}</p>}
    </div>
  );
}
