import { API, TENANT } from "./api";

export type AgentEvent = { run_id: string; seq: number; ts: number; t_ms: number; type: string; agent: string; status: string; title: string; escalation_id: number | null; data: Record<string, any> };
export type Status = "pending" | "running" | "completed" | "failed" | "waiting" | "skipped";

export type AgentMeta = { key: string; name: string; plain: string };
export const QUERY_AGENTS: AgentMeta[] = [
  { key: "understanding", name: "Query Understanding", plain: "Works out what you are really asking." },
  { key: "retrieval", name: "Knowledge Retrieval", plain: "Searches the PDFs, lecture videos and teacher-approved doubts." },
  { key: "verification", name: "Evidence Verification", plain: "Checks the evidence is relevant, citable and consistent." },
  { key: "decision", name: "Decision", plain: "Chooses to answer, ask you a question, or involve a teacher." },
  { key: "response", name: "Response Generation", plain: "Writes the answer from the verified evidence and attaches citations." },
  { key: "memory", name: "Memory", plain: "Reuses teacher-approved knowledge; saves new knowledge only after a teacher approves." },
];
export const FULL_AGENTS: AgentMeta[] = [...QUERY_AGENTS.slice(0, 5), { key: "teacher", name: "Teacher Review", plain: "A human teacher approves or rejects escalated doubts." }, QUERY_AGENTS[5]];
export const INGEST_AGENTS: AgentMeta[] = [
  { key: "ingestion", name: "Document Ingestion", plain: "Registers the document and starts processing." },
  { key: "extraction", name: "Text Extraction", plain: "Reads text from the pages / transcript." },
  { key: "chunking", name: "Chunking", plain: "Splits the text into searchable passages that keep page / timestamp." },
  { key: "embedding", name: "Embedding", plain: "Turns each passage into a vector with the embedding model." },
  { key: "indexing", name: "Knowledge Indexing", plain: "Writes the vectors into the ChromaDB index." },
  { key: "validation", name: "Validation & completion", plain: "Confirms the result and records the final status." },
];

export function agentStatus(events: AgentEvent[], agent: string): Status {
  const mine = events.filter((e) => e.agent === agent && e.type !== "llm_call" && e.type !== "tool_called");
  if (!mine.length) return "pending";
  if (mine.some((e) => e.status === "failed")) return "failed";
  return mine[mine.length - 1].status as Status;
}

export function summarize(agent: string, evs: AgentEvent[]): string {
  const f = (t: string) => evs.find((e) => e.type === t)?.data;
  const last = [...evs].reverse().find((e) => e.type !== "llm_call" && e.type !== "tool_called");
  if (!evs.length) return "";
  switch (agent) {
    case "understanding": { const d = f("agent_completed"); return d ? `intent: ${d.intent}${d.ambiguous ? " · ambiguous" : ""}` : "analysing…"; }
    case "retrieval": { const d = f("retrieval_completed"); return d ? (d.preview_only ? `preview of ${d.preview_sources} source(s)` : `${d.knowledge_chunks} passages · ${d.approved_resolutions} approved doubts`) : last?.data.error ?? "searching…"; }
    case "verification": { const d = f("evidence_verified"); return d ? `${d.relevant_chunks} relevant · ${d.supporting} supporting · ${d.citations_available} citable${d.contradiction ? " · conflict" : ""}${d.quarantined ? ` · ${d.quarantined} quarantined` : ""}` : last?.data.reason ?? "checking…"; }
    case "decision": { const d = [...evs].reverse().find((e) => e.type === "decision_made")?.data; return d ? `${d.decision}${d.confidence ? ` · confidence ${Math.round(d.confidence * 100)}%` : ""}` : "deciding…"; }
    case "response": { const d = f("agent_completed") ?? f("escalation_created") ?? f("clarification_requested"); return d ? (d.escalation_id ? `escalated · ticket #${d.escalation_id}` : d.question ? "asked a clarifying question" : `${d.sources} citation(s)${d.generated === false ? " · approved answer reused" : ""}`) : last?.data.error ?? "writing…"; }
    case "memory": { const d = f("memory_saved") ?? f("memory_retrieved"); return d ? (d.vector_ids ? `saved as resolution #${d.resolution_id}` : `reused resolution #${d.resolution_id}`) : last?.data.reason ?? ""; }
    case "ingestion": return f("stage_completed")?.resource ?? "";
    case "extraction": { const d = f("stage_completed"); return d?.segments != null ? `${d.segments} pages/segments · ${d.characters.toLocaleString()} chars` : ""; }
    case "chunking": { const d = f("stage_completed"); return d?.chunks != null ? `${d.chunks} chunks` : ""; }
    case "embedding": { const d = evs.find((e) => e.type === "stage_completed" || e.type === "stage_skipped")?.data; return d?.vectors != null ? `${d.vectors} vectors · ${d.dims} dims · ${d.ms} ms` : d?.reason ?? ""; }
    case "indexing": { const d = evs.find((e) => e.type === "stage_completed" || e.type === "stage_skipped")?.data; return d?.store ? `stored in ${d.store} · ${d.ms} ms` : d?.reason ?? ""; }
    case "validation": { const d = f("stage_completed"); return d ? `${d.outcome} · ${d.chunks} chunks${d.vectors_in_store != null ? ` · ${d.vectors_in_store} vectors in store` : ""}` : ""; }
    default: return last?.title ?? "";
  }
}

/** POST /agent/ask/stream and parse the SSE frames. Resolves with the final response; rejects on connection failure or an 'error' event. */
export async function streamAsk(body: unknown, onEvent: (e: AgentEvent) => void, onRun?: (id: string) => void, signal?: AbortSignal): Promise<any> {
  const res = await fetch(`${API}/api/v1/agent/ask/stream`, { method: "POST", headers: { "Content-Type": "application/json", "X-Tenant-ID": TENANT }, body: JSON.stringify(body), signal });
  if (!res.ok || !res.body) {
    let d = res.statusText; try { d = (await res.json()).detail ?? d; } catch {}
    throw new Error(typeof d === "string" ? d : JSON.stringify(d));
  }
  const reader = res.body.getReader(), dec = new TextDecoder();
  let buf = "", final: any = null;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let i: number;
    while ((i = buf.indexOf("\n\n")) >= 0) {
      const frame = buf.slice(0, i); buf = buf.slice(i + 2);
      const name = /^event: (.*)$/m.exec(frame)?.[1], data = /^data: (.*)$/m.exec(frame)?.[1];
      if (!name || !data) continue;
      const j = JSON.parse(data);
      if (name === "event") onEvent(j);
      else if (name === "run") onRun?.(j.run_id);
      else if (name === "final") final = j;
      else if (name === "error") throw new Error(j.message);
    }
  }
  if (!final) throw new Error("The connection closed before the agent finished.");
  return final;
}
