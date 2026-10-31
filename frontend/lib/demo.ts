import { api } from "./api";

export const adminHeaders = (): Record<string, string> => {
  const t = typeof window !== "undefined" ? sessionStorage.getItem("dl-admin-token") : null;
  return t ? { "X-Admin-Token": t } : {};
};
export const demoApi = <T = any>(path: string, init: RequestInit & { json?: unknown } = {}) => api<T>(`/api/v1/demo${path}`, { ...init, headers: { ...adminHeaders(), ...(init.headers as Record<string, string>) } });

export type DemoStatus = { tenant_id: string; last_reset: { ts: number; actor: string } | null; state: string; auth: "token" | "local-only"; pending_escalations: number; baseline_questions: string[];
  counts: Record<string, number>; preserved: Record<string, number>; demo_users: { role: string; user_id: string; label: string }[] };
export type Check = { name: string; ok: boolean; detail: string };
export type TestResult = { id: number; status: "pass" | "fail"; checks: Check[]; actual: Record<string, any>; run_ids: string[]; db_diff: Record<string, number>; ms: number; ran_at: number; error: string | null };
export type TestDef = { id: number; role: string; name: string; input: string; workflow: string; decision: string; evidence: string; db: string };
