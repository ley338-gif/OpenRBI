import { useEffect, useState } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider, useAuth } from "@shared/auth/AuthContext";
import { LoginFlow } from "@shared/auth/LoginFlow";
import { SetupFlow } from "@shared/auth/SetupFlow";
import { ToastProvider } from "@shared/components/Toast";
import { LoadingBlock } from "@shared/components/States";
import { api } from "./api/client";
import { adminApi } from "./api/adminApi";
import { AppShell } from "./components/AppShell";
import { Dashboard } from "./pages/Dashboard";
import { Profile } from "./pages/Profile";
import { Users } from "./pages/Users";
import { UserDetail } from "./pages/UserDetail";
import { Groups } from "./pages/Groups";
import { Sessions } from "./pages/Sessions";
import { SessionDetail } from "./pages/SessionDetail";
import { Policies } from "./pages/Policies";
import { PolicyDetail } from "./pages/PolicyDetail";
import { Quarantine } from "./pages/Quarantine";
import { QuarantineDetail } from "./pages/QuarantineDetail";
import { Incidents } from "./pages/Incidents";
import { IncidentDetail } from "./pages/IncidentDetail";
import { Audit } from "./pages/Audit";
import { System } from "./pages/System";
import { LdapSettings } from "./pages/LdapSettings";

function RequireAuth({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  if (loading) return <LoadingBlock label="Checking your session…" />;
  if (!user) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

/**
 * Roadmap B1.9 — shown instead of the entire app (any route, not just
 * /login) whenever the backend reports setup_required. The server, not
 * this check, is what actually closes the setup endpoints once
 * initialized (409 on every one of them, app/api/setup.py) — this is
 * routing/UX only. Skipped entirely once a real session exists (`user`
 * truthy): a logged-in admin never needs to see it, and it's also how
 * SetupFlow's own "I've saved these, continue" step (which calls
 * refresh(), setting `user`) naturally transitions the app back to the
 * normal routes without this component needing to re-poll anything.
 */
function SetupGate({ children }: { children: React.ReactNode }) {
  const { user, loading: authLoading } = useAuth();
  const [setupRequired, setSetupRequired] = useState<boolean | null>(null);

  useEffect(() => {
    if (user) return;
    adminApi
      .firstRunStatus()
      .then((r) => setSetupRequired(r.setup_required))
      .catch(() => setSetupRequired(false));
  }, [user]);

  if (user) return <>{children}</>;
  if (authLoading || setupRequired === null) return <LoadingBlock />;
  if (setupRequired) return <SetupFlow setupApi={adminApi} portalLabel="ADMIN PORTAL" />;
  return <>{children}</>;
}

function Routed() {
  const { user, loading } = useAuth();
  return (
    <Routes>
      <Route
        path="/login"
        element={
          loading ? (
            <LoadingBlock />
          ) : user ? (
            <Navigate to="/" replace />
          ) : (
            <LoginFlow mfaApi={adminApi} portalLabel="ADMIN PORTAL" title="Admin Sign In" />
          )
        }
      />
      <Route
        path="/"
        element={
          <RequireAuth>
            <AppShell />
          </RequireAuth>
        }
      >
        <Route index element={<Dashboard />} />
        <Route path="profile" element={<Profile />} />
        <Route path="users" element={<Users />} />
        <Route path="users/:id" element={<UserDetail />} />
        <Route path="groups" element={<Groups />} />
        <Route path="sessions" element={<Sessions />} />
        <Route path="sessions/:id" element={<SessionDetail />} />
        <Route path="policies" element={<Policies />} />
        <Route path="policies/:id" element={<PolicyDetail />} />
        <Route path="quarantine" element={<Quarantine />} />
        <Route path="quarantine/:id" element={<QuarantineDetail />} />
        <Route path="incidents" element={<Incidents />} />
        <Route path="incidents/:id" element={<IncidentDetail />} />
        <Route path="audit" element={<Audit />} />
        <Route path="system" element={<System />} />
        <Route path="settings/ldap" element={<LdapSettings />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}

export default function App() {
  return (
    <BrowserRouter basename={import.meta.env.BASE_URL}>
      <AuthProvider api={api}>
        <ToastProvider>
          <SetupGate>
            <Routed />
          </SetupGate>
        </ToastProvider>
      </AuthProvider>
    </BrowserRouter>
  );
}
