"use client";
import { useCallback, useEffect, useState } from "react";
import { demoApi, type DemoStatus } from "@/lib/demo";

const LABELS: Record<string, string> = { messages: "student messages", sessions: "chat sessions", agent_events: "agent execution events", escalations: "escalations", approved_answers: "approved answers (trusted memory)", memory_vectors: "memory vectors", demo_uploaded_documents: "demo-uploaded documents", demo_document_vectors: "demo document vectors" };
const KEEP: Record<string, string> = { subjects: "subjects", topics: "topics", source_documents: "source documents", video_segments: "lecture segments", source_vectors: "source vectors (PDF + video)", source_files_on_disk: "original files on disk", agent_config: "agent policy configuration" };

export default function DemoReset() {
  const [st, setSt] = useState<DemoStatus | null>(null);
  const [err, setErr] = useState("");
  const [prep, setPrep] = useState<any>(null);
  const [ack, setAck] = useState(false);
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<any>(null);
  const load = useCallback(() => demoApi<DemoStatus>("/status").then((s) => { setSt(s); setErr(""); }).catch((e) => setErr(e.message)), []);
  useEffect(() => { setToken(sessionStorage.getItem("dl-admin-token") ?? ""); load(); const t = setInterval(load, 8000); return () => clearInterval(t); }, [load]);

  async function open() {
    setErr(""); setDone(null); setAck(false);
    if (token) sessionStorage.setItem("dl-admin-token", token);
    try { setPrep(await demoApi("/reset/prepare", { method: "POST" })); } catch (e: any) { setErr(e.message); }
  }
  async function confirm() {
    setBusy(true); setErr("");
    try { const r = await demoApi("/reset", { method: "POST", json: { confirmation_token: prep.confirmation_token, confirm: true } }); setDone(r); setPrep(null); load(); }
    catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  }
  const c = st?.counts;
  return (
    <section className="mt-10">
      <h2 className="text-lg font-semibold tracking-tight">Demo Data Management</h2>
      <div className="card mt-3 border-red-200 p-5">
        {err && <p className="mb-3 rounded-lg bg-red-50 p-3 text-sm text-red-800">{err}</p>}
        {done && <p className="mb-3 rounded-lg bg-accent-soft p-3 text-sm text-accent" role="status">Reset complete in {done.ms} ms: removed {done.deleted.messages} messages, {done.deleted.escalations} escalation(s), {done.deleted.approved_answers} approved answer(s) and {done.deleted_vectors} vector(s). Source documents and vectors verified unchanged ({done.preserved_after.source_documents} documents, {done.preserved_after.source_vectors} vectors).</p>}
        {st ? (
          <div className="grid gap-5 lg:grid-cols-[1fr_auto]">
            <div>
              <p className="text-sm"><span className="label">Status</span><br /><b>{st.state}</b> · {st.last_reset ? `last reset ${new Date(st.last_reset.ts * 1000).toLocaleString()}` : "no reset recorded yet"} · tenant <span className="font-mono text-xs">{st.tenant_id}</span></p>
              <div className="mt-3 grid grid-cols-2 gap-2 text-sm sm:grid-cols-4">
                {[["Demo records", Object.entries(c!).filter(([k]) => !["demo_students"].includes(k)).reduce((a, [, v]) => a + v, 0)], ["Students / doubts", `${c!.demo_students} / ${c!.messages / 2}`], ["Escalations", `${c!.escalations} (${st.pending_escalations} pending)`], ["Approved answers", c!.approved_answers], ["Memory vectors", c!.memory_vectors], ["Demo documents", c!.demo_uploaded_documents]].map(([l, v]) => <div key={String(l)} className="rounded-lg bg-bg p-2.5"><p className="label">{l}</p><p className="text-lg font-semibold">{v}</p></div>)}
              </div>
              <p className="mt-3 text-xs text-muted">Demo users: {st.demo_users.length ? st.demo_users.map((u) => `${u.user_id}`).join(", ") : "none until the first reset"} · access: {st.auth === "token" ? "admin token" : "local requests only"}</p>
            </div>
            <div className="flex flex-col items-start gap-2">
              {st.auth === "token" && <input type="password" className="input w-56" placeholder="Admin token" value={token} onChange={(e) => setToken(e.target.value)} />}
              <button className="btn border-red-300 bg-red-600 text-white hover:!bg-red-700" onClick={open}>Reset Demo Data…</button>
              <p className="max-w-56 text-xs text-muted">Opens a confirmation first; nothing is deleted until you confirm.</p>
            </div>
          </div>
        ) : !err && <p className="text-sm text-muted">Loading…</p>}
      </div>
      {prep && (
        <div className="fixed inset-0 z-30 grid place-items-center bg-black/40 p-4" role="dialog" aria-modal="true" aria-labelledby="reset-title">
          <div className="card max-h-[90vh] w-full max-w-2xl overflow-y-auto p-6">
            <h3 id="reset-title" className="text-xl font-semibold">Reset Demo Environment?</h3>
            <p className="mt-2 text-sm text-muted">This clears everything generated by demonstration activity and restores the original demonstration baseline. It cannot be undone.</p>
            <div className="mt-4 grid gap-4 sm:grid-cols-2">
              <div className="rounded-lg border border-red-200 bg-red-50 p-3"><p className="label text-red-800">Will be deleted</p><ul className="mt-1 space-y-0.5 text-sm">{Object.entries(LABELS).map(([k, l]) => <li key={k}><b>{prep.will_delete[k]}</b> {l}</li>)}</ul></div>
              <div className="rounded-lg border border-line bg-accent-soft p-3"><p className="label text-accent">Will be preserved</p><ul className="mt-1 space-y-0.5 text-sm">{Object.entries(KEEP).map(([k, l]) => <li key={k}><b>{prep.will_preserve[k]}</b> {l}</li>)}<li>API keys, environment, database file and ChromaDB store</li></ul></div>
            </div>
            <div className="mt-4 rounded-lg bg-bg p-3 text-sm"><p className="label">Then restored</p><p>Demo users ({prep.will_restore.demo_users.join(", ")}), one labelled pending ticket, a clean agent history.</p></div>
            <label className="mt-4 flex items-start gap-2 text-sm"><input type="checkbox" className="mt-1" checked={ack} onChange={(e) => setAck(e.target.checked)} /> I understand this deletes the demo activity listed above.</label>
            <div className="mt-4 flex justify-end gap-2"><button className="btn" onClick={() => setPrep(null)} disabled={busy}>Cancel</button>
              <button className="btn border-red-300 bg-red-600 text-white hover:!bg-red-700" disabled={!ack || busy} onClick={confirm}>{busy ? "Resetting…" : "Yes, reset demo data"}</button></div>
            <p className="mt-2 text-right text-[11px] text-muted">Confirmation expires in {prep.expires_in_s}s.</p>
          </div>
        </div>
      )}
    </section>
  );
}
