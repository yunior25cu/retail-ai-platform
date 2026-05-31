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
};
