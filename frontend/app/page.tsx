"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import Shell from "@/components/Shell";
import { api, studentId, type Subject } from "@/lib/api";

type Doubt = { question: string; decision: string; solved: boolean; topic_id: string | null; created_at: number; escalation: { status: string } | null; escalation_id: number | null };
type Activity = Record<string, { lecture?: boolean; notes?: boolean; doubt?: boolean; last?: number }>;

export default function StudentDashboard() {
  const [subjects, setSubjects] = useState<Subject[] | null>(null);
  const [doubts, setDoubts] = useState<Doubt[]>([]);
  const [activity, setActivity] = useState<Activity>({});
  const [sid, setSid] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    const id = studentId();
    setSid(id);
    setActivity(JSON.parse(localStorage.getItem("dl-activity") ?? "{}"));
    api<Subject[]>("/api/v1/catalog").then(setSubjects).catch((e) => setError(e.message));
    const load = () => api<Doubt[]>(`/api/v1/doubts?user_id=${id}`).then(setDoubts).catch(() => {});
    load();
    const t = setInterval(load, 8000);
    return () => clearInterval(t);
  }, []);

  const topics = subjects?.flatMap((s) => s.topics) ?? [];
  const nameOf = (id: string | null) => topics.find((t) => t.id === id)?.name ?? "General";
  const done = (id: string) => ["lecture", "notes", "doubt"].filter((k) => activity[id]?.[k as "lecture"]).length;
  const visited = topics.filter((t) => activity[t.id]?.last).length;
  const recent = topics.filter((t) => activity[t.id]?.last).sort((a, b) => (activity[b.id].last ?? 0) - (activity[a.id].last ?? 0)).slice(0, 3);
  const solved = doubts.filter((d) => d.solved).length;
  const next = recent[0] ?? topics[0];

  return (
    <Shell>
      <section className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="label">Student dashboard</p>
          <h1 className="mt-1 text-3xl font-semibold tracking-tight">Welcome back{sid ? `, ${sid}` : ""}</h1>
          <p className="mt-1 text-muted">Pick up where you left off, or ask the AI tutor about anything in your course.</p>
        </div>
        {next && <Link href={`/learn/${next.id}`} className="btn btn-primary">Open AI tutor →</Link>}
      </section>

      {error && <div className="card mt-6 border-red-200 p-4 text-sm text-red-800">Cannot reach the backend: {error}. Start it with <code>uvicorn app.main:app --port 8000</code>.</div>}

      <section className="mt-8 grid grid-cols-2 gap-4 md:grid-cols-4">
        {[["Courses", subjects?.length ?? "–"], ["Topics visited", `${visited}/${topics.length || "–"}`], ["Doubts asked", doubts.length], ["Doubts solved", solved]].map(([l, v]) => (
          <div key={l as string} className="card p-4"><p className="label">{l}</p><p className="mt-2 text-3xl font-semibold tabular-nums">{v}</p></div>
        ))}
      </section>

      <section className="mt-10">
        <h2 className="text-lg font-semibold tracking-tight">Available courses</h2>
        {subjects?.map((s) => (
          <div key={s.id} className="card mt-3 p-5">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <div><h3 className="text-xl font-semibold tracking-tight">{s.name}</h3><p className="text-sm text-muted">{s.description}</p></div>
              <span className="pill bg-accent-soft text-accent">{s.topics.length} topics</span>
            </div>
            <div className="mt-4 grid gap-3 sm:grid-cols-2">
              {s.topics.map((t, i) => {
                const pct = Math.round((done(t.id) / 3) * 100);
                return (
                  <Link key={t.id} href={`/learn/${t.id}`} className="group rounded-lg border border-line p-4 transition hover:border-accent">
                    <div className="flex items-start justify-between gap-2">
                      <div><p className="text-xs text-muted">Topic {i + 1}</p><p className="font-medium group-hover:text-accent">{t.name}</p></div>
                      <span className="text-xs text-muted">{t.resources.filter((r) => r.type === "video").length} video · {t.resources.filter((r) => r.type === "pdf").length} PDF</span>
                    </div>
                    <p className="mt-1 text-sm text-muted">{t.description}</p>
                    <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-line"><div className="h-full bg-accent" style={{ width: `${pct}%` }} /></div>
                    <p className="mt-1 text-xs text-muted">Activity {done(t.id)}/3 · lecture opened, notes read, doubt asked</p>
                  </Link>
                );
              })}
            </div>
          </div>
        ))}
        {!subjects && !error && <p className="mt-3 text-sm text-muted">Loading courses…</p>}
      </section>

      <section className="mt-10 grid gap-6 lg:grid-cols-2">
        <div>
          <h2 className="text-lg font-semibold tracking-tight">Recently viewed topics</h2>
          <div className="card mt-3 divide-y divide-line">
            {recent.length ? recent.map((t) => (
              <Link key={t.id} href={`/learn/${t.id}`} className="flex items-center justify-between p-4 text-sm hover:bg-bg"><span className="font-medium">{t.name}</span><span className="text-muted">{new Date(activity[t.id].last!).toLocaleString()}</span></Link>
            )) : <p className="p-4 text-sm text-muted">You haven’t opened a topic yet.</p>}
          </div>
        </div>
        <div>
          <h2 className="text-lg font-semibold tracking-tight">My doubts</h2>
          <div className="card mt-3 max-h-72 divide-y divide-line overflow-y-auto">
            {doubts.length ? doubts.map((d, i) => (
              <div key={i} className="flex items-start justify-between gap-3 p-4 text-sm">
                <div><p className="font-medium">{d.question}</p><p className="text-xs text-muted">{nameOf(d.topic_id)} · {new Date(d.created_at * 1000).toLocaleString()}</p></div>
                <Status d={d} />
              </div>
            )) : <p className="p-4 text-sm text-muted">No doubts yet. Open a topic and ask the tutor.</p>}
          </div>
        </div>
      </section>
    </Shell>
  );
}

function Status({ d }: { d: Doubt }) {
  const s = d.escalation?.status;
  if (d.decision === "CLARIFY") return <span className="pill bg-amber-100 text-amber-800">Clarifying</span>;
  if (s === "approved") return <span className="pill bg-accent-soft text-accent">Teacher answered</span>;
  if (s === "rejected") return <span className="pill bg-red-100 text-red-800">Closed by teacher</span>;
  if (d.decision === "ESCALATE") return <span className="pill bg-amber-100 text-amber-800">With teacher</span>;
  return <span className="pill bg-accent-soft text-accent">Answered</span>;
}
