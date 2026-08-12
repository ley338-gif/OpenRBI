import { useAuth } from "@shared/auth/AuthContext";
import { StatusBadge } from "@shared/components/StatusBadge";

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
      <h1>Profile</h1>
      <div className="card">
        <dl className="detail-grid">
          <div>
            <dt>Username</dt>
            <dd>{user.username}</dd>
          </div>
          <div>
            <dt>Role</dt>
            <dd>{user.role}</dd>
          </div>
          <div>
            <dt>MFA</dt>
            <dd>
              <StatusBadge value={user.mfa_enabled ? "ENABLED" : "NOT ENABLED"} />
            </dd>
          </div>
        </dl>
        <p className="text-muted" style={{ marginBottom: 0 }}>
          To reset your MFA, ask another administrator to use the Reset MFA action on your account.
        </p>
      </div>
    </div>
  );
}
