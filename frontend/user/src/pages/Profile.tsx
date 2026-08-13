import { useEffect, useMemo, useState } from "react";
import { useAuth } from "@shared/auth/AuthContext";
import { StatusBadge } from "@shared/components/StatusBadge";
import { ErrorBanner, FormField } from "@shared/components/FormField";
import { PageHeader } from "@shared/components/PageHeader";
import { ConfirmDialog } from "@shared/components/ConfirmDialog";
import { EmptyState, LoadingBlock } from "@shared/components/States";
import { Icons } from "@shared/components/Icons";
import { useToast } from "@shared/components/Toast";
import { formatDateTime } from "@shared/format";
import type { SessionResponseDto } from "@shared/api/types";
import { userApi } from "../api/userApi";
import { ApiError } from "@shared/api/client";

const LIVE_STATUSES = new Set(["QUEUED", "STARTING", "ACTIVE", "DISCONNECTED", "ISOLATING", "ISOLATED"]);

export function Profile() {
  const { user, refresh } = useAuth();
  const { notify } = useToast();
  const [sessions, setSessions] = useState<SessionResponseDto[] | null>(null);
  const [enrolling, setEnrolling] = useState(false);
  const [qrCode, setQrCode] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const [recoveryCodes, setRecoveryCodes] = useState<string[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pendingSession, setPendingSession] = useState<SessionResponseDto | null>(null);
  const [terminating, setTerminating] = useState(false);
  const [showPasswordForm, setShowPasswordForm] = useState(false);
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [passwordBusy, setPasswordBusy] = useState(false);
  const [passwordError, setPasswordError] = useState<string | null>(null);
  const [showMfaReset, setShowMfaReset] = useState(false);
  const [mfaResetCode, setMfaResetCode] = useState("");
  const [mfaResetBusy, setMfaResetBusy] = useState(false);

  function loadSessions() {
    userApi.mySessions().then(setSessions).catch(() => setSessions([]));
  }
  useEffect(loadSessions, []);

  const liveSessions = useMemo(() => (sessions ?? []).filter((s) => LIVE_STATUSES.has(s.status)), [sessions]);

  async function startEnroll() {
    setError(null);
    setEnrolling(true);
    try {
      const res = await userApi.mfaEnroll();
      setQrCode(res.qr_code_png_base64);
    } catch {
      setError("Could not start MFA enrollment.");
    } finally {
      setEnrolling(false);
    }
  }

  async function confirmEnroll(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      const res = await userApi.mfaEnrollConfirm(code);
      setRecoveryCodes(res.recovery_codes);
      await refresh();
      notify("Multi-factor authentication enabled");
    } catch {
      setError("That code didn't work. Check your authenticator app and try again.");
    }
  }

  async function terminateSession() {
    if (!pendingSession) return;
    setTerminating(true);
    try {
      await userApi.terminateSession(pendingSession.id);
      notify("Secure Browser session ended");
      loadSessions();
    } catch {
      notify("Could not end this session", "error");
    } finally {
      setTerminating(false);
      setPendingSession(null);
    }
  }

  async function changePassword(e: React.FormEvent) {
    e.preventDefault();
    setPasswordError(null);
    if (newPassword !== confirmPassword) return setPasswordError("The new passwords do not match.");
    if (newPassword.length < 12) return setPasswordError("Use at least 12 characters.");
    setPasswordBusy(true);
    try {
      const result = await userApi.changePassword(currentPassword, newPassword);
      notify(`Password changed${result.other_sessions_revoked ? `; ${result.other_sessions_revoked} other session(s) signed out` : ""}`);
      setCurrentPassword(""); setNewPassword(""); setConfirmPassword(""); setShowPasswordForm(false);
    } catch (e) {
      setPasswordError(e instanceof ApiError ? e.detail : "Could not change the password.");
    } finally { setPasswordBusy(false); }
  }

  async function resetMfa(e: React.FormEvent) {
    e.preventDefault();
    setError(null); setMfaResetBusy(true);
    try {
      await userApi.mfaResetSelf(mfaResetCode);
      window.location.assign("/login");
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : "Could not reset MFA.");
    } finally { setMfaResetBusy(false); }
  }

  if (!user) return null;

  return (
    <div className="page profile-page">
      <PageHeader title="User profile" subtitle="Manage your account information, security settings, and Secure Browser sessions." />

      <div className="card profile-summary">
        <div><span>Username</span><strong>{user.username}</strong></div>
        <div><span>Role</span><strong>{user.role}</strong></div>
        <div><span>MFA status</span><StatusBadge value={user.mfa_enabled ? "ENABLED" : "NOT ENABLED"} /></div>
      </div>

      <div className="profile-card-grid">
        <section className="card profile-card">
          <ProfileCardTitle icon={<Icons.User />} title="Personal information" />
          <div className="profile-detail-list">
            <ProfileRow label="Username" value={user.username} />
            <ProfileRow label="Role" value={user.role} />
            <ProfileRow label="Authentication" value={<StatusBadge value={user.auth_source} />} />
            <ProfileRow label="Member since" value={formatDateTime(user.created_at)} />
          </div>
          {user.auth_source === "LDAP" && <p className="profile-note">Account attributes are managed by your central directory.</p>}
        </section>

        <section className="card profile-card">
          <ProfileCardTitle icon={<Icons.Shield />} title="Multi-factor authentication" badge={<StatusBadge value={user.mfa_enabled ? "ENABLED" : "NOT ENABLED"} />} />
          <p className="text-muted profile-card-copy">An authenticator app adds a verification code to your sign-in.</p>
          {error && <ErrorBanner>{error}</ErrorBanner>}
          {recoveryCodes ? (
            <>
              <p className="text-muted">Store these one-time recovery codes now. They will not be shown again.</p>
              <div className="recovery-codes">{recoveryCodes.map((c) => <span key={c}>{c}</span>)}</div>
              <button type="button" className="btn btn-secondary btn-sm" onClick={() => navigator.clipboard.writeText(recoveryCodes.join("\n"))}>Copy codes</button>
            </>
          ) : user.mfa_enabled ? (
            <>
              <div className="security-method">
                <div className="profile-card-icon"><Icons.Shield /></div>
                <div><strong>Authenticator app</strong><span>TOTP verification</span></div>
                <button type="button" className="btn btn-secondary btn-sm security-method-action" onClick={() => setShowMfaReset((v) => !v)}>Replace</button>
              </div>
              {showMfaReset && <form className="security-inline-form" onSubmit={resetMfa}>
                <p>Enter a current authenticator or recovery code. You will be signed out on every device and must configure MFA again.</p>
                <FormField label="Current authentication code"><input value={mfaResetCode} onChange={(e) => setMfaResetCode(e.target.value)} required autoFocus /></FormField>
                <div className="form-actions"><button type="submit" className="btn btn-danger" disabled={mfaResetBusy}>{mfaResetBusy && <span className="spinner" />} Reset and sign out</button><button type="button" className="btn btn-secondary" onClick={() => setShowMfaReset(false)}>Cancel</button></div>
              </form>}
            </>
          ) : !qrCode ? (
            <button type="button" className="btn btn-primary" onClick={() => void startEnroll()} disabled={enrolling}>
              {enrolling && <span className="spinner" />} Set up MFA
            </button>
          ) : (
            <form onSubmit={confirmEnroll}>
              <p className="text-muted">Scan this code with your authenticator app.</p>
              <img className="qr-code" src={qrCode} alt="TOTP enrollment QR code" width={180} height={180} />
              <FormField label="Authentication code"><input value={code} onChange={(e) => setCode(e.target.value)} autoFocus required inputMode="numeric" /></FormField>
              <button type="submit" className="btn btn-primary">Confirm MFA</button>
            </form>
          )}
        </section>

        <section className="card profile-card">
          <ProfileCardTitle icon={<Icons.Settings />} title="Security" />
          {user.auth_source === "LOCAL" ? (
            <div className="security-message">
              <strong>Local account</strong>
              <p>Your password is stored securely by OpenRBI.</p>
              {!showPasswordForm && <button type="button" className="btn btn-secondary btn-sm security-card-action" onClick={() => setShowPasswordForm(true)}>Change password</button>}
            </div>
          ) : (
            <div className="security-message">
              <strong>Directory-managed password</strong>
              <p>Your password is managed by the central LDAP directory and cannot be changed in OpenRBI.</p>
            </div>
          )}
          <div className="security-message">
            <strong>Account protection</strong>
            <p>{user.mfa_enabled ? "Multi-factor authentication is protecting this account." : "Set up MFA to add a second factor to sign-in."}</p>
          </div>
          {user.auth_source === "LOCAL" && showPasswordForm && <form className="security-inline-form" onSubmit={changePassword}>
            {passwordError && <ErrorBanner>{passwordError}</ErrorBanner>}
            <FormField label="Current password"><input type="password" autoComplete="current-password" value={currentPassword} onChange={(e) => setCurrentPassword(e.target.value)} required /></FormField>
            <FormField label="New password" hint="At least 12 characters. All other login sessions are revoked after a change."><input type="password" autoComplete="new-password" value={newPassword} onChange={(e) => setNewPassword(e.target.value)} required minLength={12} /></FormField>
            <FormField label="Confirm new password"><input type="password" autoComplete="new-password" value={confirmPassword} onChange={(e) => setConfirmPassword(e.target.value)} required minLength={12} /></FormField>
            <div className="form-actions"><button type="submit" className="btn btn-primary" disabled={passwordBusy}>{passwordBusy && <span className="spinner" />} Save password</button><button type="button" className="btn btn-secondary" onClick={() => setShowPasswordForm(false)}>Cancel</button></div>
          </form>}
        </section>
      </div>

      <section className="card profile-sessions">
        <div className="section-header">
          <div><h2>Secure Browser sessions</h2><p className="text-muted">Active isolated browser sessions associated with your account.</p></div>
        </div>
        {sessions === null ? <LoadingBlock label="Loading sessions…" /> : liveSessions.length === 0 ? (
          <EmptyState icon={<Icons.Sessions />} title="No active sessions">Your active Secure Browser sessions will appear here.</EmptyState>
        ) : (
          <div className="table-wrap">
            <table className="data-table">
              <thead><tr><th>Session</th><th>Browser</th><th>Started</th><th>Status</th><th></th></tr></thead>
              <tbody>{liveSessions.map((s) => (
                <tr key={s.id}>
                  <td><span className="table-primary mono">{s.id.slice(0, 8)}</span><span className="identity-meta">Secure Browser</span></td>
                  <td>{s.browser}</td>
                  <td>{formatDateTime(s.started_at ?? s.created_at)}</td>
                  <td><StatusBadge value={s.status} /></td>
                  <td><button type="button" className="btn btn-danger btn-sm" onClick={() => setPendingSession(s)}>End session</button></td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        )}
      </section>

      {pendingSession && <ConfirmDialog title="End Secure Browser session?" description={`Session ${pendingSession.id.slice(0, 8)} will be terminated. Any unsaved work in the isolated browser will be lost.`} confirmLabel="End session" danger busy={terminating} onConfirm={() => void terminateSession()} onCancel={() => setPendingSession(null)} />}
    </div>
  );
}

function ProfileCardTitle({ icon, title, badge }: { icon: React.ReactNode; title: string; badge?: React.ReactNode }) {
  return <div className="profile-card-title"><div className="profile-card-icon">{icon}</div><h2>{title}</h2>{badge && <div className="profile-card-badge">{badge}</div>}</div>;
}

function ProfileRow({ label, value }: { label: string; value: React.ReactNode }) {
  return <div className="profile-detail-row"><span>{label}</span><strong>{value}</strong></div>;
}
