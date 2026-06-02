/**
 * HTTP client for the retail-ai-platform Python API.
 *
 * - Attaches Authorization: Bearer <token> on every request.
 * - On 401: attempts one silent refresh, then redirects to /login.
 * - Base URL from VITE_API_URL env var.
 */

import axios, {
  type AxiosInstance,
  type AxiosRequestConfig,
  type InternalAxiosRequestConfig,
} from "axios";

// ── Token storage ────────────────────────────────────────────────────────────

const ACCESS_KEY  = "ai_access_token";
const REFRESH_KEY = "ai_refresh_token";

export const tokenStore = {
  getAccess:     ()      => localStorage.getItem(ACCESS_KEY),
  getRefresh:    ()      => localStorage.getItem(REFRESH_KEY),
  setAccess:     (t: string) => localStorage.setItem(ACCESS_KEY, t),
  setRefresh:    (t: string) => localStorage.setItem(REFRESH_KEY, t),
  clear:         ()      => {
    localStorage.removeItem(ACCESS_KEY);
    localStorage.removeItem(REFRESH_KEY);
  },
};

// ── Axios instance ───────────────────────────────────────────────────────────

const BASE_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8001";

const http: AxiosInstance = axios.create({
  baseURL: BASE_URL,
  headers: { "Content-Type": "application/json" },
});

let _isRefreshing = false;
let _failedQueue: Array<{
  resolve: (token: string) => void;
  reject: (err: unknown) => void;
}> = [];

function _processQueue(err: unknown, token: string | null) {
  _failedQueue.forEach(({ resolve, reject }) =>
    err ? reject(err) : resolve(token!)
  );
  _failedQueue = [];
}

// Request interceptor — attach Bearer token
http.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const token = tokenStore.getAccess();
  if (token) {
    config.headers = config.headers ?? {};
    config.headers["Authorization"] = `Bearer ${token}`;
  }
  return config;
});

// Response interceptor — silent refresh on 401
http.interceptors.response.use(
  (res) => res,
  async (error) => {
    const original: AxiosRequestConfig & { _retry?: boolean } =
      error.config ?? {};

    if (error.response?.status === 401 && !original._retry) {
      original._retry = true;
      const refreshToken = tokenStore.getRefresh();

      if (!refreshToken) {
        tokenStore.clear();
        window.location.href = "/login";
        return Promise.reject(error);
      }

      if (_isRefreshing) {
        return new Promise((resolve, reject) => {
          _failedQueue.push({ resolve, reject });
        }).then((token) => {
          original.headers = original.headers ?? {};
          original.headers["Authorization"] = `Bearer ${token}`;
          return http(original);
        });
      }

      _isRefreshing = true;
      try {
        const { data } = await axios.post(`${BASE_URL}/api/v1/auth/refresh`, {
          refresh_token: refreshToken,
        });
        tokenStore.setAccess(data.access_token);
        tokenStore.setRefresh(data.refresh_token);
        _processQueue(null, data.access_token);
        original.headers = original.headers ?? {};
        original.headers["Authorization"] = `Bearer ${data.access_token}`;
        return http(original);
      } catch (refreshErr) {
        _processQueue(refreshErr, null);
        tokenStore.clear();
        window.location.href = "/login";
        return Promise.reject(refreshErr);
      } finally {
        _isRefreshing = false;
      }
    }

    return Promise.reject(error);
  }
);

// ── Typed API functions ──────────────────────────────────────────────────────

export interface LoginPayload {
  email: string;
  password: string;
  tenant_slug: string;
}

export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
  tenant_id: number;
  role: string;
  vertical: string;
}

export interface UserResponse {
  id: string;
  email: string;
  role: string;
  full_name: string | null;
  tenant_id: number;
  tenant_name?: string | null;
  is_active: boolean;
  created_at: string;
}

export interface ChatPayload {
  message: string;
  conversation_id?: string;
}

export interface ChatResponse {
  response: string;
  conversation_id: string;
  request_id: string;
  tools_used: Array<{ name: string; duration_ms: number; is_error: boolean }>;
  tokens_input: number;
  tokens_output: number;
  duration_ms: number;
}

export interface SuggestionsResponse {
  suggestions: string[];
}

export interface ConversationSummary {
  conversation_id: string;
  title: string;
  last_message_at: string | null;
  message_count: number;
}

export interface ConversationMessage {
  role: string;
  content: string;
  tools_used: string[] | null;
  duration_ms: number | null;
  created_at: string;
}

export interface FeedbackPayload {
  request_id: string;
  rating: "positive" | "negative";
  comment?: string;
}

export interface MetricsResponse {
  period: string;
  total_queries: number;
  total_cost_usd: number;
  active_users: number;
  top_tool: string | null;
  top_tool_count: number;
  longest_conversation_turns: number;
  avg_duration_ms: number;
  queries_by_role: Record<string, number>;
  queries_by_day: Array<{ date: string; count: number }>;
}

export interface TenantConfigResponse {
  monthly_budget_usd: number;
  budget_alert_pct: number;
  memory_turns: number;
  suggestions_enabled: boolean;
  rate_limits: Record<string, number>;
  current_spend_usd: number;
  vertical: string;
}

export interface TenantConfigPatch {
  monthly_budget_usd?: number;
  budget_alert_pct?: number;
  memory_turns?: number;
  suggestions_enabled?: boolean;
  rate_limit_director?: number;
  rate_limit_produccion?: number;
  rate_limit_compras?: number;
  rate_limit_marca?: number;
  rate_limit_tienda?: number;
  rate_limit_producto?: number;
}

export interface AdminTenant {
  id: number;
  name: string;
  slug: string;
  vertical: string;
  plan: string;
  is_active: boolean;
  created_at: string;
  platform_tenant_id: number | null;
}

export interface AdminUser {
  id: string;
  email: string;
  role: string;
  full_name: string | null;
  tenant_id: number;
  is_active: boolean;
  created_at: string;
  last_login_at: string | null;
}

export interface VerticalOut {
  name: string;
  label: string;
  tool_count: number;
  tenant_count: number;
}

export const api = {
  login: (payload: LoginPayload) =>
    http.post<TokenResponse>("/api/v1/auth/login", payload).then((r) => r.data),

  refreshToken: (refreshToken: string) =>
    http
      .post<TokenResponse>("/api/v1/auth/refresh", { refresh_token: refreshToken })
      .then((r) => r.data),

  logout: () =>
    http.post("/api/v1/auth/logout").catch(() => null),

  getMe: () =>
    http.get<UserResponse>("/api/v1/auth/me").then((r) => r.data),

  sendMessage: (payload: ChatPayload) =>
    http.post<ChatResponse>("/api/v1/internal/chat", payload).then((r) => r.data),

  getSuggestions: (tenantId: number, role: string) =>
    http
      .get<SuggestionsResponse>("/api/v1/internal/suggestions", {
        headers: { "X-Tenant-Id": String(tenantId), "X-User-Role": role },
      })
      .then((r) => r.data),

  getConversations: () =>
    http.get<ConversationSummary[]>("/api/v1/internal/conversations").then((r) => r.data),

  getConversationMessages: (conversationId: string) =>
    http
      .get<ConversationMessage[]>(`/api/v1/internal/conversations/${conversationId}/messages`)
      .then((r) => r.data),

  submitFeedback: (payload: FeedbackPayload) =>
    http.post<{ ok: boolean }>("/api/v1/internal/feedback", payload).then((r) => r.data),

  getMetrics: () =>
    http.get<MetricsResponse>("/api/v1/internal/metrics").then((r) => r.data),

  // Config
  getTenantConfig: (queryStr = "") =>
    http.get<TenantConfigResponse>(`/api/v1/config/tenant${queryStr}`).then((r) => r.data),

  patchTenantConfig: (patch: TenantConfigPatch, queryStr = "") =>
    http.patch<TenantConfigResponse>(`/api/v1/config/tenant${queryStr}`, patch).then((r) => r.data),

  // Admin
  adminGetTenants: () =>
    http.get<AdminTenant[]>("/api/v1/admin/tenants").then((r) => r.data),

  adminCreateTenant: (payload: Omit<AdminTenant, "id" | "is_active" | "created_at">) =>
    http.post<AdminTenant>("/api/v1/admin/tenants", payload).then((r) => r.data),

  adminPatchTenant: (id: number, patch: Partial<AdminTenant>) =>
    http.patch<AdminTenant>(`/api/v1/admin/tenants/${id}`, patch).then((r) => r.data),

  adminGetUsers: (tenantId?: number) =>
    http
      .get<AdminUser[]>("/api/v1/admin/users", { params: tenantId ? { tenant_id: tenantId } : {} })
      .then((r) => r.data),

  adminInviteUser: (payload: { email: string; password: string; role: string; full_name?: string; tenant_id: number }) =>
    http.post<AdminUser>("/api/v1/admin/users/invite", payload).then((r) => r.data),

  adminPatchUser: (id: string, patch: { role?: string; is_active?: boolean; full_name?: string }) =>
    http.patch<AdminUser>(`/api/v1/admin/users/${id}`, patch).then((r) => r.data),

  adminGetVerticals: () =>
    http.get<VerticalOut[]>("/api/v1/admin/verticals").then((r) => r.data),

  adminGetPlatformMetrics: () =>
    http.get<PlatformMetricsResponse>("/api/v1/admin/platform_metrics").then((r) => r.data),

  adminGetLogs: (params: {
    tenant_id?: number;
    status_filter?: "SUCCESS" | "ERROR" | "PARTIAL";
    limit?: number;
    offset?: number;
  } = {}) =>
    http
      .get<LogsResponse>("/api/v1/admin/logs", { params })
      .then((r) => r.data),
};

export interface LogRow {
  timestamp: string | null;
  tenant_id: number;
  tenant_name: string | null;
  user_id: string;
  user_role: string;
  conversation_id: string | null;
  status: string;
  tokens: number;
  cost_usd: number;
  preview: string;
  source: "pg" | "ss";
}

export interface LogsResponse {
  total: number;
  rows: LogRow[];
}

export interface PlatformTenantRow {
  tenant_id: number;
  tenant_name: string;
  chats: number;
  cost_usd: number;
}

export interface PlatformMetricsResponse {
  period: string;
  total_chats: number;
  total_cost_usd: number;
  active_tenants: number;
  top_tool: string;
  top_tool_count: number;
  by_tenant: PlatformTenantRow[];
}
