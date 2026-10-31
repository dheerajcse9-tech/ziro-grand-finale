"use client";
import { useCallback, useEffect, useState } from "react";
import Shell from "@/components/Shell";
import { api } from "@/lib/api";

type Result = { id: string; category: string; question: string; follow_up?: string; expected: string; actual: string; reason_code: string; passed: boolean; failures: string[]; answer: string; confidence: number; sources: { source_type: string; source_name: string; page?: number; timestamp_start?: number }[] };
type Run = { id: number; created_at: number; llm_mode: string; metrics: Record<string, number | null>; results: Result[] };

const LABELS: [string, string, string][] = [
  ["pass_rate", "Cases passed", "All checks for a case succeeded"],
  ["decision_accuracy", "Decision accuracy", "Expected ANSWER / CLARIFY / ESCALATE"],
  ["answer_correctness", "Answer correctness", "Required key concepts present in answers"],
  ["evidence_support", "Evidence support", "Answers cite the expected source"],
  ["unsupported_answer_rate", "Unsupported-answer rate", "Answers lacking valid citations (lower is better)"],
  ["false_answer_rate", "Answered when it should not", "Hallucination risk (lower is better)"],
  ["escalation_rate", "Escalation rate", "Share of questions sent to a teacher"],
  ["clarification_accuracy", "Clarification accuracy", "Ambiguous questions that got a clarifying question"],
  ["solved_doubt_reuse", "Solved-doubt reuse", "Approved resolutions reused for paraphrases"],
  ["tool_execution_success", "Tool execution success", "Tool calls that executed without error"],
  ["injection_resistance", "Injection resistance", "Injected instructions not followed"],
];

export default function Evaluation() {
  const [run, setRun] = useState<Run | null | undefined>(undefined);
  const [running, setRunning] = useState(false);
  const [err, setErr] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const load = useCallback(async () => {
    try {
      const [l, s] = await Promise.all([api<Run | null>("/api/v1/evaluation/latest"), api<{ running: boolean; error: string | null }>("/api/v1/evaluation/status")]);
      setRun(l); setRunning(s.running); if (s.error) setErr(s.error);
    } catch (e: any) { setErr(e.message); }
  }, []);
  useEffect(() => { load(); }, [load]);
  useEffect(() => { if (!running) return; const t = setInterval(load, 2000); return () => clearInterval(t); }, [running, load]);
  const pct = (v: number | null | undefined) => (v == null ? "n/a" : `${Math.round(v * 100)}%`);
  const failed = run?.results.filter((r) => !r.passed) ?? [];

  return (
    <Shell>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div><p className="label">Evaluation</p><h1 className="mt-1 text-3xl font-semibold tracking-tight">Agent evaluation</h1>
          <p className="mt-1 max-w-2xl text-muted">Runs the reproducible 18-case dataset through the live agent in an isolated tenant. Every number below is computed from that run — nothing is pre-filled.</p></div>
        <button className="btn btn-primary" disabled={running} onClick={async () => { setErr(""); await api("/api/v1/evaluation/run", { method: "POST" }).catch((e) => setErr(e.message)); setRunning(true); }}>{running ? "Running…" : "Run evaluation"}</button>
      </div>
      {err && <p className="mt-4 rounded-lg bg-red-50 p-3 text-sm text-red-800">{err}</p>}
      {run === null && !running && <div className="card mt-8 p-8 text-center text-sm text-muted">No evaluation has been run yet. Click “Run evaluation”.</div>}
      {run && (
        <>
          <p className="mt-4 text-sm text-muted">Run #{run.id} · {new Date(run.created_at * 1000).toLocaleString()} · LLM mode: <b className={run.llm_mode === "local-demo" ? "text-amber-700" : "text-accent"}>{run.llm_mode}</b>{run.llm_mode === "local-demo" && " (deterministic demo mode: no Gemini key configured; answers are extractive)"}</p>
          <div className="mt-4 grid grid-cols-2 gap-3 md:grid-cols-4">
            {LABELS.map(([k, l, h]) => <div key={k} className="card p-4" title={h}><p className="label">{l}</p><p className="mt-1 text-3xl font-semibold tabular-nums">{pct(run.metrics[k])}</p><p className="mt-1 text-xs text-muted">{h}</p></div>)}
            <div className="card p-4"><p className="label">Passed / total</p><p className="mt-1 text-3xl font-semibold tabular-nums">{run.metrics.passed}/{run.metrics.total_cases}</p></div>
          </div>
          {failed.length > 0 && (
            <section className="mt-8"><h2 className="text-lg font-semibold tracking-tight text-red-800">Failed cases ({failed.length})</h2>
              <div className="mt-3 space-y-3">{failed.map((r) => <div key={r.id} className="card border-red-200 p-4 text-sm"><p className="font-medium">{r.id} · {r.question}</p><ul className="mt-1 list-disc pl-5 text-red-800">{r.failures.map((f, i) => <li key={i}>{f}</li>)}</ul></div>)}</div></section>
          )}
          <section className="mt-8"><h2 className="text-lg font-semibold tracking-tight">All cases</h2>
            <div className="card mt-3 divide-y divide-line">
              {run.results.map((r) => (
                <div key={r.id} className="p-4 text-sm">
                  <button className="flex w-full items-start justify-between gap-3 text-left" onClick={() => setOpen(open === r.id ? null : r.id)}>
                    <div><p className="font-medium">{r.question}{r.follow_up ? <span className="font-normal text-muted"> → “{r.follow_up}”</span> : ""}</p><p className="text-xs text-muted">{r.id} · {r.category.replace("_", " ")} · expected {r.expected} · got {r.actual} ({r.reason_code})</p></div>
                    <span className={`pill shrink-0 ${r.passed ? "bg-accent-soft text-accent" : "bg-red-100 text-red-800"}`}>{r.passed ? "PASS" : "FAIL"}</span>
                  </button>
                  {open === r.id && <div className="mt-3 space-y-2 rounded-lg bg-bg p-3 text-xs"><p className="whitespace-pre-wrap">{r.answer}</p>
                    {r.sources.map((s, i) => <p key={i} className="text-muted">{s.source_type}: {s.source_name}{s.page ? ` p.${s.page}` : ""}{s.timestamp_start != null ? ` @${Math.round(s.timestamp_start)}s` : ""}</p>)}
                    {r.failures.map((f, i) => <p key={i} className="text-red-700">✗ {f}</p>)}</div>}
                </div>
              ))}
            </div>
          </section>
        </>
      )}
    </Shell>
  );
}
