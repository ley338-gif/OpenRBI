import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider, useAuth } from "@shared/auth/AuthContext";
import { LoginFlow } from "@shared/auth/LoginFlow";
import { ToastProvider } from "@shared/components/Toast";
import { LoadingBlock } from "@shared/components/States";
import { api } from "./api/client";
import { userApi } from "./api/userApi";
import { Dashboard } from "./pages/Dashboard";
import { SecureBrowser } from "./pages/SecureBrowser";
import { Downloads } from "./pages/Downloads";
import { Profile } from "./pages/Profile";
import { AppShell } from "./components/AppShell";

function RequireAuth({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  if (loading) return <LoadingBlock label="Checking your session…" />;
  if (!user) return <Navigate to="/login" replace />;
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
            <LoginFlow mfaApi={userApi} portalLabel="USER PORTAL" title="Welcome to OpenRBI" />
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
        <Route path="browser" element={<SecureBrowser />} />
        <Route path="downloads" element={<Downloads />} />
        <Route path="profile" element={<Profile />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider api={api}>
        <ToastProvider>
          <Routed />
        </ToastProvider>
      </AuthProvider>
    </BrowserRouter>
  );
}
