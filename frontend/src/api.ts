import type {
  AIDecision,
  EquityPoint,
  JobName,
  JobResult,
  KillSwitchState,
  Order,
  Position,
  Proposal,
  Reconciliation,
  Risk,
  Signal,
  Status,
} from "./types";

const TOKEN_KEY = "trading-desk-api-token";

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

export function getToken(): string {
  try {
    return localStorage.getItem(TOKEN_KEY) ?? "";
  } catch {
    return "";
  }
}

export function saveToken(value: string): void {
  try {
    localStorage.setItem(TOKEN_KEY, value.trim());
  } catch {
    // Storage can be unavailable (private mode); the token then lasts for this page only.
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init.body) headers.set("Content-Type", "application/json");

  let response: Response;
  try {
    response = await fetch(`/api${path}`, { ...init, headers });
  } catch {
    throw new ApiError(0, "Can't reach the trading API.");
  }
  if (!response.ok) {
    let detail = response.statusText || `Request failed (${response.status})`;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      // Not JSON; keep the status text.
    }
    throw new ApiError(response.status, detail);
  }
  return (await response.json()) as T;
}

const post = { method: "POST" } as const;

export const api = {
  status: () => request<Status>("/status"),
  proposals: (status: string | null, limit = 100) => {
    const query = new URLSearchParams({ limit: String(limit) });
    if (status) query.set("status", status);
    return request<Proposal[]>(`/proposals?${query}`);
  },
  approve: (id: number) => request<Proposal>(`/proposals/${id}/approve`, post),
  reject: (id: number) => request<Proposal>(`/proposals/${id}/reject`, post),
  positions: () => request<Position[]>("/positions"),
  orders: (limit = 40) => request<Order[]>(`/orders?limit=${limit}`),
  signals: () => request<Signal[]>("/signals"),
  equity: () => request<EquityPoint[]>("/equity"),
  risk: () => request<Risk>("/risk"),
  aiDecisions: (limit = 12) => request<AIDecision[]>(`/ai-decisions?limit=${limit}`),
  reconciliations: (limit = 5) => request<Reconciliation[]>(`/reconciliations?limit=${limit}`),
  killSwitch: (body: { engage: boolean; reason?: string; confirm?: string }) =>
    request<KillSwitchState>("/kill-switch", { method: "POST", body: JSON.stringify(body) }),
  runJob: (name: JobName) => request<JobResult>(`/jobs/${name}`, post),
};
