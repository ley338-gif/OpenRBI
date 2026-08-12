import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import type { ApiClient } from "../api/client";
import type { CurrentUser, LoginResponse } from "../api/types";

interface AuthContextValue {
  user: CurrentUser | null;
  loading: boolean;
  login: (username: string, password: string) => Promise<LoginResponse>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

/**
 * Shared across both portals (section 8) — the underlying endpoints
 * (/auth/login, /auth/me, /auth/logout, /mfa/*) are registered in every
 * listener mode (app/api/auth.py, app/api/mfa.py), so this component works
 * unmodified against either the User or the Admin API base URL.
 *
 * Sets no client-side auth token anywhere (section 11/45) — the backend's
 * own HttpOnly session cookie is the only credential; this context just
 * tracks who that cookie currently belongs to to drive route guards/UI.
 */
export function AuthProvider({ api, children }: { api: ApiClient; children: ReactNode }) {
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const me = await api.get<CurrentUser>("/auth/me");
      setUser(me);
    } catch {
      setUser(null);
    }
  }, [api]);

  useEffect(() => {
    api.setUnauthorizedHandler(() => setUser(null));
    void refresh().finally(() => setLoading(false));
    return () => api.setUnauthorizedHandler(null);
  }, [api, refresh]);

  const login = useCallback(
    async (username: string, password: string) => {
      const result = await api.post<LoginResponse>("/auth/login", { username, password });
      if (result.status === "ok") {
        await refresh();
      }
      return result;
    },
    [api, refresh],
  );

  const logout = useCallback(async () => {
    try {
      await api.post("/auth/logout");
    } finally {
      setUser(null);
    }
  }, [api]);

  const value = useMemo(() => ({ user, loading, login, logout, refresh }), [user, loading, login, logout, refresh]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within an AuthProvider");
  return ctx;
}
