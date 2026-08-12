import { useAuth } from "@shared/auth/AuthContext";
import { StatusBadge } from "@shared/components/StatusBadge";
import { PageHeader } from "@shared/components/PageHeader";
import { DefinitionList } from "@shared/components/DefinitionList";

/**
 * Identity + MFA status only. Unlike the User Portal's Profile page,
 * there's no voluntary-enrollment flow here — ADMIN/SECURITY_REVIEWER
 * accounts already have MFA enabled by the time they can hold a session
 * (mandatory enrollment at login), so the "not enabled" branch is
 * unreachable in practice, not a missing feature. No self-service MFA
 * *reset* here either — that's admin_mfa.py's ADMIN-only endpoint.
 */
export function Profile() {
  const { user } = useAuth();
  if (!user) return null;

  return (
    <div className="page">
      <PageHeader title="Profile" subtitle="Your administrator account identity and MFA status." />
      <div className="card">
        <DefinitionList
          items={[
            { label: "Username", value: user.username },
            { label: "Role", value: user.role },
            { label: "MFA", value: <StatusBadge value={user.mfa_enabled ? "ENABLED" : "NOT ENABLED"} /> },
          ]}
        />
        <p className="text-muted" style={{ marginBottom: 0 }}>
          To reset your MFA, ask another administrator to use the Reset MFA action on your account.
        </p>
      </div>
    </div>
  );
}
