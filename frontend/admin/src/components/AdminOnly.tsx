import type { ReactNode } from "react";
import { Link, Navigate } from "react-router-dom";
import { useAuth } from "@shared/auth/AuthContext";

// A SECURITY_REVIEWER uses this portal for review work (dashboard, sessions,
// quarantine, incidents, audit, health, workers) but not for administration:
// the backend answers 403 to that role for users/groups, policies, LDAP, MFA
// reset, node lifecycle actions and session Kill (docs/admin-guide.md#security-reviewer-access).
// The UI hides those instead of offering controls that can only fail. This is
// presentation only; the backend is what enforces it.

export function useIsAdmin(): boolean {
  const { user } = useAuth();
  return user?.role === "ADMIN";
}

/** Route guard for administrator-only pages. */
export function AdminOnly({ children }: { children: ReactNode }) {
  return useIsAdmin() ? <>{children}</> : <Navigate to="/" replace />;
}

/** A user reference: links to the user page for administrators, plain text otherwise. */
export function UserLink({ userId, className, children }: { userId: string; className?: string; children: ReactNode }) {
  const isAdmin = useIsAdmin();
  if (!isAdmin) return <span className={className}>{children}</span>;
  return (
    <Link className={className} to={`/users/${userId}`}>
      {children}
    </Link>
  );
}
