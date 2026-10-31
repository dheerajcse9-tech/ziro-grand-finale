export const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
export const TENANT = process.env.NEXT_PUBLIC_TENANT_ID ?? "demo-university";

export async function api<T = any>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const headers: Record<string, string> = { "X-Tenant-ID": TENANT, ...(init.headers as Record<string, string>) };
  let body = init.body;
  if (init.json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(init.json);
  }
  const res = await fetch(`${API}${path}`, { ...init, headers, body, cache: "no-store" });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const j = await res.json();
      detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    } catch {}
    throw new Error(detail);
  }
  return res.json();
}

export const fileUrl = (path: string, page?: number | null) => `${API}${path}?tenant_id=${TENANT}${page ? `#page=${page}` : ""}`;

export function studentId(): string {
  if (typeof window === "undefined") return "";
  let id = localStorage.getItem("dl-student");
  if (!id) {
    id = "stu-" + Math.random().toString(36).slice(2, 8);
    localStorage.setItem("dl-student", id);
  }
  return id;
}

export const fmtTime = (s: number | null | undefined) => {
  if (s == null) return "";
  const m = Math.floor(s / 60), r = Math.floor(s % 60);
  return `${m}:${String(r).padStart(2, "0")}`;
};

export type Resource = { id: string; subject_id: string; topic_id: string; type: "pdf" | "video"; title: string; url: string | null; youtube_id: string | null; filename?: string | null; origin: string; transcript_origin: string | null; attribution: string; status: string; status_detail: string; chunk_count: number; file_url: string | null };
export type Topic = { id: string; subject_id: string; name: string; description: string; sample_questions: string[]; resources: Resource[] };
export type Subject = { id: string; name: string; description: string; topics: Topic[] };
export type Source = { source_type: string; source_id: string; source_name: string; filename?: string | null; heading?: string | null; timestamp_status?: string | null; page?: number | null; timestamp_start?: number | null; timestamp_end?: number | null; youtube_id?: string | null; url?: string | null; trust: string; origin?: string | null; excerpt?: string | null };
export type AgentResponse = { decision: "ANSWER" | "CLARIFY" | "ESCALATE"; answer: string | null; clarification_question: string | null; escalation_id: number | null; message: string | null; confidence: number; sources: Source[]; reason: string; reason_code: string; answered_from: string; llm_mode: string; run_id?: string | null; trace: { step: string; ok: boolean; detail: string; ms: number }[] };

export type Segment = { id: number; title: string; topic: string; subtopic: string; start_s: number; end_s: number; verification: string; timestamp_source: string };
