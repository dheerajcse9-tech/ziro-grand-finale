"use client";
import { useState } from "react";
import { agentStatus, summarize, type AgentEvent, type AgentMeta, type Status } from "@/lib/events";

const TONE: Record<Status, { dot: string; text: string; label: string }> = {
  pending: { dot: "border-line bg-white text-muted", text: "text-muted", label: "Pending" },
  running: { dot: "border-accent bg-accent-soft text-accent", text: "text-accent", label: "Running" },
  completed: { dot: "border-accent bg-accent text-white", text: "text-accent", label: "Completed" },
  failed: { dot: "border-red-300 bg-red-100 text-red-700", text: "text-red-700", label: "Failed" },
  waiting: { dot: "border-amber-300 bg-amber-100 text-amber-800", text: "text-amber-800", label: "Waiting for approval" },
  skipped: { dot: "border-line bg-slate-100 text-slate-500", text: "text-slate-500", label: "Skipped" },
};
export const STATUS_TONE = TONE;

export function StatusDot({ s }: { s: Status }) {
  const glyph = s === "completed" ? "✓" : s === "failed" ? "✕" : s === "waiting" ? "⏸" : s === "skipped" ? "–" : s === "running" ? "" : "";
  return <span className={`grid h-6 w-6 shrink-0 place-items-center rounded-full border text-xs font-semibold ${TONE[s].dot} ${s === "running" ? "animate-pulse" : ""}`}>{glyph || (s === "running" ? "●" : "")}</span>;
}

const KEEP_HIDDEN = new Set(["description"]);
function Detail({ e }: { e: AgentEvent }) {
  const entries = Object.entries(e.data).filter(([k, v]) => v !== null && v !== undefined && v !== "" && !KEEP_HIDDEN.has(k));
  return (
    <li className="rounded-md border border-line bg-bg p-2">
      <div className="flex flex-wrap items-center gap-2"><span className="font-mono text-[11px] font-semibold">{e.type}</span><span className={`text-[11px] ${TONE[e.status as Status]?.text}`}>{e.status}</span>
        <span className="ml-auto font-mono text-[11px] text-muted">+{e.t_ms} ms · {new Date(e.ts * 1000).toLocaleTimeString()}</span></div>
      {entries.length > 0 && <pre className="mt-1 max-h-48 overflow-auto whitespace-pre-wrap break-words font-mono text-[11px] leading-snug text-muted">{entries.map(([k, v]) => `${k}: ${typeof v === "object" ? JSON.stringify(v) : v}`).join("\n")}</pre>}
    </li>
  );
}

/** One expandable card per agent, derived only from recorded events. */
export default function AgentTimeline({ events, agents, live = false, technical = true }: { events: AgentEvent[]; agents: AgentMeta[]; live?: boolean; technical?: boolean }) {
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const visible = agents.filter((a) => events.some((e) => e.agent === a.key) || live);
  if (!visible.length) return <p className="text-sm text-muted">No execution events recorded.</p>;
  return (
    <ol className="space-y-1.5">
      {visible.map((a) => {
        const evs = events.filter((e) => e.agent === a.key);
        const s = agentStatus(events, a.key);
        const tools = evs.filter((e) => e.type === "tool_called");
        const first = evs[0], lastEv = evs[evs.length - 1];
        const dur = first && lastEv ? lastEv.t_ms - first.t_ms : 0;
        return (
          <li key={a.key} className={`rounded-lg border bg-white ${s === "running" ? "border-accent" : "border-line"}`}>
            <button onClick={() => setOpen((o) => ({ ...o, [a.key]: !o[a.key] }))} className="flex w-full items-start gap-3 p-2.5 text-left" aria-expanded={!!open[a.key]}>
              <StatusDot s={s} />
              <span className="min-w-0 flex-1">
                <span className="flex flex-wrap items-center gap-x-2"><span className="text-sm font-medium">{a.name}</span><span className={`text-xs ${TONE[s].text}`}>{TONE[s].label}</span>
                  {first && <span className="font-mono text-[11px] text-muted">+{first.t_ms} ms{dur > 0 ? ` · ${dur} ms` : ""}</span>}</span>
                <span className="block text-xs text-muted">{evs.length ? summarize(a.key, evs) || a.plain : a.plain}</span>
                {tools.length > 0 && <span className="mt-1 flex flex-wrap gap-1">{tools.map((t, i) => <span key={i} className={`pill !py-0 text-[11px] ${t.status === "failed" ? "bg-red-100 text-red-800" : "bg-slate-100 text-slate-700"}`}>🔧 {t.data.tool} · {t.data.count ?? "ok"}{t.data.count != null ? " results" : ""} · {t.data.ms} ms</span>)}</span>}
              </span>
              <span className="text-xs text-muted">{open[a.key] ? "▲" : "▼"}</span>
            </button>
            {open[a.key] && (
              <div className="border-t border-line p-2.5 text-xs">
                <p className="mb-2 text-muted">{a.plain}</p>
                {technical && (evs.length ? <ul className="space-y-1.5">{evs.map((e) => <Detail key={e.seq} e={e} />)}</ul> : <p className="text-muted">Not reached.</p>)}
              </div>
            )}
          </li>
        );
      })}
    </ol>
  );
}
