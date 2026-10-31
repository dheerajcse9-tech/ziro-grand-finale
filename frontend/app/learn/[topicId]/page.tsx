"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useState } from "react";
import Shell from "@/components/Shell";
import Tutor from "@/components/Tutor";
import { api, fileUrl, fmtTime, studentId, type Resource, type Source, type Subject, type Topic } from "@/lib/api";

type Doubt = { question: string; decision: string; solved: boolean; created_at: number };

function mark(topicId: string, key: "lecture" | "notes" | "doubt") {
  const a = JSON.parse(localStorage.getItem("dl-activity") ?? "{}");
  a[topicId] = { ...a[topicId], [key]: true, last: Date.now() };
  localStorage.setItem("dl-activity", JSON.stringify(a));
}

export default function Page() {
  return <Suspense fallback={<p className="p-8 text-sm text-muted">Loading workspace…</p>}><Workspace /></Suspense>;
}

function Workspace() {
  const { topicId } = useParams<{ topicId: string }>();
  const [subject, setSubject] = useState<Subject | null>(null);
  const [topic, setTopic] = useState<Topic | null>(null);
  const [video, setVideo] = useState<{ id: string; start: number; n: number } | null>(null);
  const [pdf, setPdf] = useState<{ id: string; page: number } | null>(null);
  const [tab, setTab] = useState<"notes" | "materials" | "doubts">("notes");
  const [doubts, setDoubts] = useState<Doubt[]>([]);
  const [error, setError] = useState("");

  const loadDoubts = useCallback(() => api<Doubt[]>(`/api/v1/doubts?user_id=${studentId()}&topic_id=${topicId}`).then(setDoubts).catch(() => {}), [topicId]);

  useEffect(() => {
    api<Subject[]>("/api/v1/catalog").then((cat) => {
      const s = cat.find((x) => x.topics.some((t) => t.id === topicId));
      const t = s?.topics.find((x) => x.id === topicId);
      if (!s || !t) return setError("Topic not found.");
      setSubject(s); setTopic(t);
      const v = t.resources.find((r) => r.type === "video");
      const p = t.resources.find((r) => r.type === "pdf" && r.status === "indexed") ?? t.resources.find((r) => r.type === "pdf");
      if (v?.youtube_id) setVideo({ id: v.youtube_id, start: 0, n: 0 });
      if (p) setPdf({ id: p.id, page: 1 });
      mark(topicId, "lecture");
    }).catch((e) => setError(e.message));
    loadDoubts();
  }, [topicId, loadDoubts]);

  function cite(s: Source) {
    if (s.source_type === "video" && s.youtube_id) {
      setVideo((v) => ({ id: s.youtube_id!, start: Math.floor(s.timestamp_start ?? 0), n: (v?.n ?? 0) + 1 }));
      window.scrollTo({ top: 0, behavior: "smooth" });
    } else if (s.source_type === "pdf") {
      setPdf({ id: s.source_id, page: s.page ?? 1 });
      setTab("notes"); mark(topicId, "notes");
    }
  }

  if (error) return <Shell><div className="card p-6 text-sm text-red-800">{error}</div></Shell>;
  if (!topic || !subject) return <Shell><p className="text-sm text-muted">Loading workspace…</p></Shell>;
  const videos = topic.resources.filter((r) => r.type === "video");
  const pdfs = topic.resources.filter((r) => r.type === "pdf");
  const curVideo = videos.find((v) => v.youtube_id === video?.id);

  return (
    <Shell wide>
      <div className="mb-4 text-sm text-muted"><Link href="/" className="hover:text-ink">Dashboard</Link> / {subject.name} / <span className="text-ink">{topic.name}</span></div>
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_420px]">
        <div className="min-w-0 space-y-4">
          <div className="card overflow-hidden">
            {video ? (
              <div className="aspect-video bg-black">
                <iframe key={`${video.id}-${video.start}-${video.n}`} className="h-full w-full" title="Lecture video" allow="accelerometer; autoplay; encrypted-media; picture-in-picture" allowFullScreen
                  src={`https://www.youtube.com/embed/${video.id}?start=${video.start}&rel=0${video.n ? "&autoplay=1" : ""}`} />
              </div>
            ) : <p className="p-6 text-sm text-muted">No video for this topic yet.</p>}
            <div className="flex flex-wrap items-center justify-between gap-2 p-3 text-sm">
              <div><p className="font-medium">{curVideo?.title}</p>{video && video.start > 0 && <p className="text-xs text-accent">Cued to {fmtTime(video.start)} from an answer citation</p>}</div>
              {curVideo && <p className="max-w-md text-xs text-muted">{curVideo.attribution} Transcript: <b>{curVideo.transcript_origin ?? "none"}</b></p>}
            </div>
            {videos.length > 1 && (
              <div className="flex flex-wrap gap-2 border-t border-line p-3">
                {videos.map((v) => <button key={v.id} onClick={() => setVideo((x) => ({ id: v.youtube_id!, start: 0, n: x?.n ?? 0 }))} className={`btn text-xs ${v.youtube_id === video?.id ? "btn-primary" : ""}`}>{v.title.slice(0, 44)}</button>)}
              </div>
            )}
          </div>

          <div className="card">
            <div className="flex gap-1 border-b border-line p-2 text-sm">
              {([["notes", "Notes (PDF)"], ["materials", "Study materials"], ["doubts", `My doubts (${doubts.length})`]] as const).map(([k, l]) => (
                <button key={k} onClick={() => { setTab(k); if (k === "notes") mark(topicId, "notes"); if (k === "doubts") loadDoubts(); }} className={`rounded-md px-3 py-1.5 ${tab === k ? "bg-accent-soft font-medium text-accent" : "text-muted"}`}>{l}</button>
              ))}
            </div>
            {tab === "notes" && (
              <div className="p-3">
                {pdf ? (
                  <>
                    <div className="mb-2 flex flex-wrap items-center gap-2 text-sm">
                      <select className="input max-w-xs" value={pdf.id} onChange={(e) => setPdf({ id: e.target.value, page: 1 })}>{pdfs.map((p) => <option key={p.id} value={p.id}>{p.title}</option>)}</select>
                      <span className="text-muted">Page {pdf.page}</span>
                      <a className="ml-auto text-accent hover:underline" target="_blank" rel="noreferrer" href={fileUrl(`/api/v1/resources/${pdf.id}/file`, pdf.page)}>Open in new tab ↗</a>
                    </div>
                    <iframe key={`${pdf.id}-${pdf.page}`} title="PDF notes" className="h-[560px] w-full rounded-lg border border-line" src={fileUrl(`/api/v1/resources/${pdf.id}/file`, pdf.page)} />
                  </>
                ) : <p className="p-3 text-sm text-muted">No PDF notes attached to this topic.</p>}
              </div>
            )}
            {tab === "materials" && (
              <ul className="divide-y divide-line">
                {topic.resources.map((r: Resource) => (
                  <li key={r.id} className="flex flex-wrap items-center justify-between gap-2 p-4 text-sm">
                    <div><p className="font-medium">{r.type === "video" ? "▶" : "📄"} {r.title}</p><p className="text-xs text-muted">{r.attribution || r.origin}</p></div>
                    <span className={`pill ${r.status === "indexed" ? "bg-accent-soft text-accent" : "bg-amber-100 text-amber-800"}`}>{r.status === "indexed" ? `Indexed · ${r.chunk_count} chunks` : r.status.replace("_", " ")}</span>
                  </li>
                ))}
              </ul>
            )}
            {tab === "doubts" && (
              <ul className="divide-y divide-line">
                {doubts.length ? doubts.map((d, i) => <li key={i} className="flex justify-between gap-3 p-4 text-sm"><span>{d.question}</span><span className={`pill ${d.solved ? "bg-accent-soft text-accent" : "bg-amber-100 text-amber-800"}`}>{d.solved ? "Solved" : d.decision === "CLARIFY" ? "Clarifying" : "Open"}</span></li>) : <li className="p-4 text-sm text-muted">No doubts asked on this topic yet.</li>}
              </ul>
            )}
          </div>
        </div>
        <aside className="lg:sticky lg:top-20 lg:self-start">
          <Tutor subjectId={subject.id} topicId={topic.id} topicName={topic.name} samples={topic.sample_questions} onCite={cite} onAsked={() => { mark(topicId, "doubt"); loadDoubts(); }} />
        </aside>
      </div>
    </Shell>
  );
}
