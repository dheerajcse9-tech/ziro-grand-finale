"use client";
import { useCallback, useEffect, useState } from "react";
import Shell from "@/components/Shell";
import AgentTimeline from "@/components/AgentTimeline";
import { api, fmtTime } from "@/lib/api";
import { FULL_AGENTS, type AgentEvent } from "@/lib/events";

type Ev = { source_type: string; source_name: string; page?: number; timestamp_start?: number; timestamp_end?: number; similarity: number; relevant: boolean; excerpt?: string };
type Receipt = { eid: number; kind: "approved" | "rejected"; result: any; events: AgentEvent[] };
type Mem = { id: number; escalation_id: number; question: string; answer: string; topic_id: string | null; approved_by: string; created_at: number };
type Esc = { id: number; question: string; standalone_question: string; subject_id: string; topic_id: string; reason: string; evidence: Ev[]; status: string; teacher_answer?: string; teacher_note?: string; teacher_id?: string; created_at: number; resolved_at?: number };

export default function Teacher() {
  const [tab, setTab] = useState<"pending" | "resolved" | "memory">("pending");
  const [receipt, setReceipt] = useState<Receipt | null>(null);
  const [mem, setMem] = useState<Mem[]>([]);
  const [q, setQ] = useState("");
  const [items, setItems] = useState<Esc[]>([]);
  const [counts, setCounts] = useState({ pending: 0, memory: 0 });
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    try {
      const [list, pend, memory] = await Promise.all([api<Esc[]>(`/api/v1/escalations?status=${tab === "memory" ? "pending" : tab}`), api<Esc[]>("/api/v1/escalations?status=pending"), api<Mem[]>("/api/v1/resolutions")]);
      setItems(list); setMem(memory); setCounts({ pending: pend.length, memory: memory.length }); setErr("");
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
        {(["pending", "resolved", "memory"] as const).map((k) => <button key={k} onClick={() => setTab(k)} className={`rounded-md px-3 py-1.5 ${tab === k ? "bg-accent-soft font-medium text-accent" : "text-muted"}`}>{k === "pending" ? "Pending" : k === "resolved" ? "Resolved history" : `Approved knowledge (${counts.memory})`}</button>)}
      </div>
      {err && <p className="mt-3 rounded-lg bg-red-50 p-3 text-sm text-red-800">{err}</p>}
      {receipt && <ReceiptCard r={receipt} close={() => setReceipt(null)} />}
      {tab === "memory" ? (
        <div className="mt-3 space-y-3">
          <input className="input max-w-md" placeholder="Search approved doubts…" value={q} onChange={(e) => setQ(e.target.value)} />
          {mem.filter((m) => !q.trim() || `${m.question} ${m.answer}`.toLowerCase().includes(q.trim().toLowerCase())).map((m) => (
            <div key={m.id} className="card p-4"><div className="flex flex-wrap items-center justify-between gap-2"><p className="font-medium">{m.question}</p><span className="pill bg-accent-soft text-accent">Trusted memory #{m.id}</span></div>
              <p className="mt-1 text-xs text-muted">{m.topic_id ?? "no topic"} · approved by {m.approved_by} · {new Date(m.created_at * 1000).toLocaleString()} · from ticket #{m.escalation_id}</p>
              <p className="mt-2 whitespace-pre-wrap rounded-lg bg-bg p-3 text-sm">{m.answer}</p></div>
          ))}
          {!mem.length && <div className="card p-8 text-center text-sm text-muted">No approved knowledge yet. Approve an escalated doubt to create the first entry.</div>}
          {!!mem.length && !mem.some((m) => !q.trim() || `${m.question} ${m.answer}`.toLowerCase().includes(q.trim().toLowerCase())) && <p className="text-sm text-muted">No approved doubts match “{q}”.</p>}
        </div>
      ) : (
      <div className="mt-3 space-y-4">
        {items.map((e) => tab === "pending" ? <Pending key={e.id} e={e} done={load} onReceipt={setReceipt} /> : <Resolved key={e.id} e={e} />)}
        {!items.length && !err && <div className="card p-8 text-center text-sm text-muted">{tab === "pending" ? "No pending doubts. Ask the tutor something it can’t answer to see one here." : "Nothing resolved yet."}</div>}
      </div>
      )}
    </Shell>
  );
}

function EvidenceList({ ev, pick }: { ev: Ev[]; pick?: (t: string) => void }) {
  if (!ev.length) return <p className="text-sm text-muted">The agent retrieved no evidence for this question.</p>;
  return (
    <ul className="space-y-1.5">
      {ev.map((x, i) => (
        <li key={i} className="rounded-lg border border-line bg-bg p-2.5 text-xs">
          <div className="flex flex-wrap items-center gap-2"><b>{x.source_type === "video" ? `▶ ${x.source_name} · ${fmtTime(x.timestamp_start)}–${fmtTime(x.timestamp_end)}` : x.source_type === "pdf" ? `📄 ${x.source_name} · p.${x.page}` : x.source_name}</b>
            <span className="text-muted">similarity {x.similarity.toFixed(2)}</span>{!x.relevant && <span className="pill bg-slate-200 text-slate-700">below relevance threshold</span>}</div>
          {x.excerpt && <p className="mt-1 text-muted">{x.excerpt}…</p>}
          {x.excerpt && pick && <button className="mt-1 text-accent hover:underline" onClick={() => pick(x.excerpt!)}>Insert excerpt into my answer</button>}
        </li>
      ))}
    </ul>
  );
}

function Pending({ e, done, onReceipt }: { e: Esc; done: () => void; onReceipt: (r: Receipt) => void }) {
  const [inv, setInv] = useState<AgentEvent[] | null>(null);
  const [showInv, setShowInv] = useState(false);
  const [answer, setAnswer] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  async function act(kind: "approve" | "reject") {
    setBusy(true); setErr("");
    try {
      const result = await api(`/api/v1/escalations/${e.id}/${kind}`, { method: "POST", json: kind === "approve" ? { answer, teacher_id: "teacher" } : { note, teacher_id: "teacher" } });
      const { events } = await api<{ events: AgentEvent[] }>(`/api/v1/escalations/${e.id}/events`).catch(() => ({ events: [] }));
      onReceipt({ eid: e.id, kind: kind === "approve" ? "approved" : "rejected", result, events }); done();
    }
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
      <div className="mt-4"><button className="text-sm text-accent hover:underline" onClick={() => { setShowInv(!showInv); if (!inv) api<{ events: AgentEvent[] }>(`/api/v1/escalations/${e.id}/events`).then((x) => setInv(x.events)).catch(() => setInv([])); }}>{showInv ? "Hide" : "Show"} agent investigation history</button>
        {showInv && <div className="mt-2">{inv ? (inv.length ? <AgentTimeline events={inv} agents={FULL_AGENTS} /> : <p className="text-sm text-muted">No recorded agent run for this ticket (created before event recording).</p>) : <p className="text-sm text-muted">Loading…</p>}</div>}</div>
      <div className="mt-4"><p className="label mb-1.5">Retrieved evidence</p><EvidenceList ev={e.evidence} pick={(t) => setAnswer((a) => (a ? a + "\n\n" : "") + t)} /></div>
      <p className="mt-4 rounded-lg bg-bg p-3 text-xs text-muted"><b>Proposed answer:</b> none — the agent declined to answer because the evidence did not support one. Write the answer yourself, or insert an evidence excerpt below as a starting point and edit it.</p>
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

function ReceiptCard({ r, close }: { r: Receipt; close: () => void }) {
  const saved = r.events.find((e) => e.type === "memory_saved");
  return (
    <div className={`card mt-4 border-2 p-4 ${r.kind === "approved" ? "border-accent" : "border-slate-300"}`} role="status">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className={`font-medium ${r.kind === "approved" ? "text-accent" : ""}`}>{r.kind === "approved" ? `Ticket #${r.eid} approved and saved to trusted memory` : `Ticket #${r.eid} rejected — nothing was saved to trusted memory`}</p>
          {r.kind === "approved" && <ul className="mt-1 list-disc pl-5 text-sm text-muted">
            <li>Memory-save result: resolution <b>#{r.result.resolution_id}</b>, indexed: <b>{String(r.result.indexed)}</b>, trust level: <b>{r.result.trust}</b></li>
            <li>Vector ids written: <span className="font-mono text-xs">{(r.result.vector_ids ?? []).join(", ")}</span></li>
            <li>Similar questions from any student session will now retrieve this answer, attributed as teacher-approved.</li>
          </ul>}
        </div>
        <button className="btn text-xs" onClick={close}>Dismiss</button>
      </div>
      {r.events.length > 0 && <details className="mt-3"><summary className="cursor-pointer text-sm text-accent">Full recorded process{saved ? ` (saved in ${saved.t_ms} ms into the run)` : ""}</summary><div className="mt-2"><AgentTimeline events={r.events} agents={FULL_AGENTS} /></div></details>}
    </div>
  );
}
