// Central API client (section 46): every portal request goes through one
// of these, never ad-hoc fetch() calls scattered across components.
// Cookies (credentials: "include") carry the existing server-side session
// — no client-managed auth token, no localStorage/sessionStorage token
// storage (section 11/45): the backend already issues an HttpOnly,
// SameSite=lax session cookie (backend/app/api/auth.py) and this client
// never needs to read or store it itself.
//
// RBI-POST-003: the one exception is the CSRF cookie (app/core/csrf.py,
// backend) — deliberately NOT HttpOnly, because this client must read it
// and echo it back as X-CSRF-Token on every mutating request. Centralized
// here (not per-page) so no component ever has to think about CSRF.

const CSRF_COOKIE_NAME = "csrf_token";
const CSRF_HEADER_NAME = "X-CSRF-Token";
const MUTATING_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);

function readCookie(name: string): string | null {
  const match = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
  return match ? decodeURIComponent(match[1]) : null;
}

export class ApiError extends Error {
  status: number;
  detail: string;

  constructor(status: number, detail: string) {
    super(detail);
    this.status = status;
    this.detail = detail;
  }
}

export type UnauthorizedHandler = () => void;

export class ApiClient {
  private baseUrl: string;
  private onUnauthorized: UnauthorizedHandler | null = null;

  constructor(baseUrl: string) {
    // Strip a trailing slash so callers can write paths starting with "/"
    // uniformly regardless of how the base URL env var was set.
    this.baseUrl = baseUrl.replace(/\/$/, "");
  }

  setUnauthorizedHandler(handler: UnauthorizedHandler | null): void {
    this.onUnauthorized = handler;
  }

  // The backend issues the CSRF cookie on every response, but a fresh
  // browser's very first request could be a mutating one (e.g. /auth/login
  // submitted before anything else ever hit the backend) with no cookie
  // yet to echo back. A cheap, unauthenticated GET guarantees one exists
  // first — /health always exists in every listener mode (app/main.py's
  // _register_shared_routes) and has no side effects of its own.
  private async ensureCsrfCookie(): Promise<void> {
    if (readCookie(CSRF_COOKIE_NAME)) return;
    try {
      await fetch(`${this.baseUrl}/health`, { credentials: "include" });
    } catch {
      // Best-effort — if the server is unreachable the real request below
      // will fail with the same network error and surface that instead.
    }
  }

  private async request<T>(method: string, path: string, body?: unknown, opts?: { raw?: boolean }): Promise<T> {
    if (MUTATING_METHODS.has(method)) {
      await this.ensureCsrfCookie();
    }
    const headers: Record<string, string> = {};
    if (body !== undefined) headers["Content-Type"] = "application/json";
    if (MUTATING_METHODS.has(method)) {
      const csrfToken = readCookie(CSRF_COOKIE_NAME);
      if (csrfToken) headers[CSRF_HEADER_NAME] = csrfToken;
    }

    let response: Response;
    try {
      response = await fetch(`${this.baseUrl}${path}`, {
        method,
        credentials: "include",
        headers: Object.keys(headers).length > 0 ? headers : undefined,
        body: body !== undefined ? JSON.stringify(body) : undefined,
      });
    } catch {
      throw new ApiError(0, "Cannot reach the server. Check your connection and try again.");
    }

    if (response.status === 401) {
      this.onUnauthorized?.();
      throw new ApiError(401, await this.extractDetail(response, "Your session has expired. Please log in again."));
    }

    if (!response.ok) {
      throw new ApiError(response.status, await this.extractDetail(response, `Request failed (${response.status}).`));
    }

    if (opts?.raw) {
      return response as unknown as T;
    }
    if (response.status === 204) {
      return undefined as T;
    }
    return (await response.json()) as T;
  }

  private async extractDetail(response: Response, fallback: string): Promise<string> {
    try {
      const body = await response.json();
      if (typeof body?.detail === "string") return body.detail;
      // FastAPI validation errors (422) come back as a list under "detail".
      if (Array.isArray(body?.detail) && body.detail[0]?.msg) {
        return body.detail.map((e: { msg: string }) => e.msg).join("; ");
      }
    } catch {
      // Not JSON — fall through to the generic message.
    }
    return fallback;
  }

  get<T>(path: string): Promise<T> {
    return this.request<T>("GET", path);
  }

  post<T>(path: string, body?: unknown): Promise<T> {
    return this.request<T>("POST", path, body ?? {});
  }

  put<T>(path: string, body?: unknown): Promise<T> {
    return this.request<T>("PUT", path, body ?? {});
  }

  delete<T>(path: string): Promise<T> {
    return this.request<T>("DELETE", path);
  }

  /** For endpoints returning a raw Response (file downloads). */
  getRaw(path: string): Promise<Response> {
    return this.request<Response>("GET", path, undefined, { raw: true });
  }

  async postForm<T>(path: string, form: FormData): Promise<T> {
    await this.ensureCsrfCookie();
    const csrfToken = readCookie(CSRF_COOKIE_NAME);
    const response = await fetch(`${this.baseUrl}${path}`, {
      method: "POST",
      credentials: "include",
      headers: csrfToken ? { [CSRF_HEADER_NAME]: csrfToken } : undefined,
      body: form,
    });
    if (response.status === 401) {
      this.onUnauthorized?.();
      throw new ApiError(401, await this.extractDetail(response, "Your session has expired. Please log in again."));
    }
    if (!response.ok) {
      throw new ApiError(response.status, await this.extractDetail(response, `Request failed (${response.status}).`));
    }
    return (await response.json()) as T;
  }
}
