"use client";
import { useEffect, useRef, useState } from "react";
import { api, fmtTime, studentId, type AgentResponse, type Source } from "@/lib/api";

type Msg = { role: "user" | "assistant"; text: string; response?: AgentResponse };

export default function Tutor({ subjectId, topicId, topicName, samples, onCite, onAsked }: {
  subjectId: string; topicId: string; topicName: string; samples: string[];
  onCite: (s: Source) => void; onAsked: () => void;
}) {
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [sessionId, setSessionId] = useState("");
  const [error, setError] = useState("");
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

  useEffect(() => end.current?.scrollIntoView({ behavior: "smooth" }), [msgs, busy]);

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
    setInput(""); setError(""); setBusy(true);
    setMsgs((m) => [...m, { role: "user", text: q }]);
    try {
      const r = await api<AgentResponse>("/api/v1/agent/ask", { method: "POST", json: { question: q, tenant_id: process.env.NEXT_PUBLIC_TENANT_ID ?? "demo-university", session_id: sessionId, user_id: studentId(), subject_id: subjectId, topic_id: topicId } });
      setMsgs((m) => [...m, { role: "assistant", text: r.answer ?? r.clarification_question ?? r.message ?? "", response: r }]);
      onAsked();
    } catch (e: any) {
      setError(e.message);
    } finally { setBusy(false); }
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
          : <Reply key={i} r={m.response} text={m.text} onCite={onCite} teacher={m.response?.escalation_id ? teacher[m.response.escalation_id] : undefined} />)}
        {busy && <p className="animate-pulse text-sm text-muted">Searching evidence and deciding how to respond…</p>}
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

function Reply({ r, text, onCite, teacher }: { r?: AgentResponse; text: string; onCite: (s: Source) => void; teacher?: { status: string; teacher_answer?: string; teacher_note?: string } }) {
  const [trace, setTrace] = useState(false);
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
            <button key={i} onClick={() => onCite(s)} title={s.excerpt ?? ""} className="max-w-full truncate rounded-md border border-line bg-white px-2 py-1 text-left text-xs hover:border-accent">
              {s.source_type === "video" ? `▶ ${s.source_name.slice(0, 38)} · ${fmtTime(s.timestamp_start)}–${fmtTime(s.timestamp_end)}`
                : s.source_type === "pdf" ? `📄 ${s.source_name} · p.${s.page}` : "✓ Teacher-approved resolution"}
            </button>
          ))}
        </div>
      )}
      <button onClick={() => setTrace(!trace)} className="mt-3 text-xs text-muted underline-offset-2 hover:underline">{trace ? "Hide" : "Show"} agent steps · {r.llm_mode}</button>
      {trace && <ol className="mt-2 space-y-1 border-l-2 border-line pl-3 text-xs">{r.trace.map((t, i) => <li key={i} className={t.ok ? "" : "text-amber-700"}><span className="font-mono">{t.step}</span> <span className="text-muted">{t.detail}</span></li>)}</ol>}
    </div>
  );
}
