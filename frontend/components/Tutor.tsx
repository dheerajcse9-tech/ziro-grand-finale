"use client";
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import AgentTimeline from "@/components/AgentTimeline";
import { api, fmtTime, studentId, type AgentResponse, type Source } from "@/lib/api";
import { QUERY_AGENTS, FULL_AGENTS, streamAsk, type AgentEvent } from "@/lib/events";

type Msg = { role: "user" | "assistant"; text: string; response?: AgentResponse; events?: AgentEvent[] };

export default function Tutor({ subjectId, topicId, topicName, samples, onCite, onAsked }: {
  subjectId: string; topicId: string; topicName: string; samples: string[];
  onCite: (s: Source) => void; onAsked: () => void;
}) {
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [sessionId, setSessionId] = useState("");
  const [error, setError] = useState("");
  const [live, setLive] = useState<AgentEvent[]>([]);
  const [teacher, setTeacher] = useState<Record<number, { status: string; teacher_answer?: string; teacher_note?: string }>>({});
  const end = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const key = `dl-session-${topicId}`;
    const sid = localStorage.getItem(key) ?? `${studentId()}-${topicId}-${Date.now().toString(36)}`;
    localStorage.setItem(key, sid);
    setSessionId(sid);
    api<{ role: "user" | "assistant"; content: string; response: AgentResponse | null }[]>(`/api/v1/sessions/${sid}/messages`)
      .then((m) => setMsgs(m.map((x) => ({ role: x.role, text: x.content, response: x.response ?? undefined }))))
      .catch(() => {});
  }, [topicId]);

  useEffect(() => {
    end.current?.scrollIntoView({ behavior: "smooth" });
  }, [msgs, busy, live]);
  // poll open escalations so teacher answers show up in the conversation
  useEffect(() => {
    const open = msgs.map((m) => m.response?.escalation_id).filter((x): x is number => !!x && teacher[x]?.status !== "approved" && teacher[x]?.status !== "rejected");
    if (!open.length) return;
    const t = setInterval(() => open.forEach((id) => api(`/api/v1/escalations/${id}`).then((e) => setTeacher((p) => ({ ...p, [id]: e }))).catch(() => {})), 5000);
    return () => clearInterval(t);
  }, [msgs, teacher]);

  async function send(q: string) {
    q = q.trim();
    if (!q || busy) return;
    setInput(""); setError(""); setBusy(true); setLive([]);
    setMsgs((m) => [...m, { role: "user", text: q }]);
    const seen: AgentEvent[] = [];
    try {
      const r: AgentResponse = await streamAsk(
        { question: q, tenant_id: process.env.NEXT_PUBLIC_TENANT_ID ?? "demo-university", session_id: sessionId, user_id: studentId(), subject_id: subjectId, topic_id: topicId },
        (e) => { seen.push(e); setLive([...seen]); });
      setMsgs((m) => [...m, { role: "assistant", text: r.answer ?? r.clarification_question ?? r.message ?? "", response: r, events: seen }]);
      onAsked();
    } catch (e: any) {
      // The run continues server-side; try to recover its stored result instead of leaving the student with nothing.
      setError(`${e.message} — checking whether the agent still finished…`);
      const before = msgs.length + 1;
      for (let i = 0; i < 6; i++) {
        await new Promise((res) => setTimeout(res, 2000));
        try {
          const m = await api<{ role: "user" | "assistant"; content: string; response: AgentResponse | null }[]>(`/api/v1/sessions/${sessionId}/messages`);
          if (m.length > before) { setMsgs(m.map((x) => ({ role: x.role, text: x.content, response: x.response ?? undefined }))); setError(""); onAsked(); return; }
        } catch {}
      }
      setError(`${e.message}. The answer could not be recovered; please ask again.`);
    } finally { setBusy(false); setLive([]); }
  }

  return (
    <div className="card flex h-[calc(100vh-7.5rem)] min-h-[520px] flex-col">
      <div className="border-b border-line p-4">
        <p className="label">AI tutor</p>
        <p className="text-sm text-muted">Context: <span className="font-medium text-ink">{topicName}</span>. Ask anything — I search all course material, not just this topic.</p>
      </div>
      <div className="flex-1 space-y-4 overflow-y-auto p-4">
        {!msgs.length && (
          <div className="space-y-2">
            <p className="text-sm text-muted">Try a question:</p>
            {samples.map((s) => <button key={s} onClick={() => send(s)} className="block w-full rounded-lg border border-line px-3 py-2 text-left text-sm hover:border-accent">{s}</button>)}
          </div>
        )}
        {msgs.map((m, i) => m.role === "user"
          ? <div key={i} className="ml-8 rounded-xl rounded-br-sm bg-accent px-3.5 py-2.5 text-sm text-white">{m.text}</div>
          : <Reply key={i} r={m.response} text={m.text} events={m.events} onCite={onCite} teacher={m.response?.escalation_id ? teacher[m.response.escalation_id] : undefined} />)}
        {busy && (
          <div className="rounded-xl border border-accent/40 bg-white p-3">
            <p className="label mb-2 flex items-center gap-2 text-accent"><span className="h-2 w-2 animate-pulse rounded-full bg-accent" />Agents working live</p>
            <AgentTimeline events={live} agents={QUERY_AGENTS} live technical={false} />
          </div>
        )}
        {error && <p className="rounded-lg bg-red-50 p-3 text-sm text-red-800">Request failed: {error}</p>}
        <div ref={end} />
      </div>
      <form onSubmit={(e) => { e.preventDefault(); send(input); }} className="flex gap-2 border-t border-line p-3">
        <input className="input" value={input} onChange={(e) => setInput(e.target.value)} placeholder="Ask a doubt…" maxLength={2000} />
        <button className="btn btn-primary" disabled={busy || !input.trim()}>Ask</button>
      </form>
    </div>
  );
}

function Reply({ r, text, events, onCite, teacher }: { r?: AgentResponse; text: string; events?: AgentEvent[]; onCite: (s: Source) => void; teacher?: { status: string; teacher_answer?: string; teacher_note?: string } }) {
  const [trace, setTrace] = useState(false);
  const [evs, setEvs] = useState<AgentEvent[] | null>(events ?? null);
  const [evErr, setEvErr] = useState("");
  const toggle = () => {
    setTrace(!trace);
    if (!trace && !evs && r?.run_id) api<{ events: AgentEvent[] }>(`/api/v1/events/runs/${r.run_id}`).then((x) => setEvs(x.events)).catch((e) => setEvErr(e.message));
  };
  if (!r) return <div className="mr-8 rounded-xl bg-bg p-3 text-sm">{text}</div>;
  const tone = r.decision === "ANSWER" ? "border-line bg-white" : r.decision === "CLARIFY" ? "border-amber-200 bg-amber-50" : "border-line bg-bg";
  return (
    <div className={`mr-4 rounded-xl rounded-bl-sm border p-3.5 text-sm ${tone}`}>
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <span className={`pill ${r.decision === "ANSWER" ? "bg-accent-soft text-accent" : r.decision === "CLARIFY" ? "bg-amber-100 text-amber-800" : "bg-slate-200 text-slate-700"}`}>{r.decision === "ESCALATE" ? "Sent to teacher" : r.decision === "CLARIFY" ? "Need more detail" : r.answered_from === "approved_resolution" ? "Teacher-approved answer" : "Answer from course material"}</span>
        {r.decision === "ANSWER" && <span className="text-xs text-muted">evidence confidence {Math.round(r.confidence * 100)}%</span>}
      </div>
      <p className="whitespace-pre-wrap leading-relaxed">{text}</p>
      {r.decision === "ESCALATE" && !teacher?.status?.match(/approved|rejected/) && <p className="mt-2 text-xs text-muted">Why: {r.reason}</p>}
      {teacher?.status === "approved" && <div className="mt-3 rounded-lg bg-accent-soft p-3"><p className="label text-accent">Teacher’s verified answer</p><p className="mt-1 whitespace-pre-wrap">{teacher.teacher_answer}</p></div>}
      {teacher?.status === "rejected" && <p className="mt-3 rounded-lg bg-red-50 p-3 text-red-800">Your teacher closed this doubt{teacher.teacher_note ? `: ${teacher.teacher_note}` : "."}</p>}
      {r.sources.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {r.sources.map((s, i) => (
            <button key={i} onClick={() => onCite(s)} title={(s.timestamp_status === "unverified" ? "Timestamp supplied by the course team and pending independent verification. " : "") + (s.heading ? s.heading + " — " : "") + (s.excerpt ?? "")} className="max-w-full truncate rounded-md border border-line bg-white px-2 py-1 text-left text-xs hover:border-accent">
              {s.source_type === "video"
                ? `▶ ${s.source_name.slice(0, 34)} · ${fmtTime(s.timestamp_start)}–${fmtTime(s.timestamp_end)}${s.timestamp_status === "unverified" ? " · ⚠ unverified timestamp" : ""}`
                : s.source_type === "pdf" ? `📄 ${s.filename ?? s.source_name} · p.${s.page}` : "✓ Teacher-approved resolution"}
            </button>
          ))}
        </div>
      )}
      <button onClick={toggle} className="mt-3 text-xs text-muted underline-offset-2 hover:underline">{trace ? "Hide" : "Show"} agent activity · {r.llm_mode}</button>
      {trace && (
        <div className="mt-2">
          {evs ? <AgentTimeline events={evs} agents={FULL_AGENTS} /> : evErr ? <p className="text-xs text-red-700">{evErr}</p> : r.run_id ? <p className="text-xs text-muted">Loading…</p>
            : <ol className="space-y-1 border-l-2 border-line pl-3 text-xs">{r.trace.map((t, i) => <li key={i} className={t.ok ? "" : "text-amber-700"}><span className="font-mono">{t.step}</span> <span className="text-muted">{t.detail}</span></li>)}</ol>}
          {r.run_id && <Link href={`/agents?run=${r.run_id}`} className="mt-2 inline-block text-xs text-accent hover:underline">Open in orchestration view ↗</Link>}
        </div>
      )}
    </div>
  );
}
