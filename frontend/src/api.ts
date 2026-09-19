import type { Alert, Dashboard, LeadDetail, LeadSummary } from "./types";

class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    ...init,
  });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(response.status, detail);
  }
  return (await response.json()) as T;
}

export const api = {
  leads: (params: Record<string, string> = {}) =>
    request<LeadSummary[]>(`/api/leads?${new URLSearchParams(params).toString()}`),
  tlQueue: () => request<LeadSummary[]>("/api/queue/tl"),
  qaQueue: () => request<LeadSummary[]>("/api/queue/qa"),
  alerts: () => request<Alert[]>("/api/alerts"),
  lead: (id: string) => request<LeadDetail>(`/api/leads/${id}`),
  override: (leadId: string, resultId: number, body: { auditor: string; new_result: string; reason: string }) =>
    request<LeadDetail>(`/api/leads/${leadId}/results/${resultId}/override`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  review: (leadId: string, body: { reviewer: string; decision: "approve" | "reject"; notes?: string }) =>
    request<LeadDetail>(`/api/leads/${leadId}/review`, { method: "POST", body: JSON.stringify(body) }),
  patchCrm: (leadId: string, body: { actor: string; fields: Record<string, unknown>; rescore: boolean }) =>
    request<LeadDetail>(`/api/leads/${leadId}/crm`, { method: "PATCH", body: JSON.stringify(body) }),
  rescore: (leadId: string) => request<LeadDetail>(`/api/leads/${leadId}/rescore`, { method: "POST" }),
  submit: (leadId: string) =>
    request<{ lead_id: string; status: string; message: string }>(`/api/leads/${leadId}/submit`, { method: "POST" }),
  dashboard: (period: string, groupBy: string) =>
    request<Dashboard>(`/api/dashboard?period=${period}&group_by=${groupBy}`),
};

export { ApiError };
