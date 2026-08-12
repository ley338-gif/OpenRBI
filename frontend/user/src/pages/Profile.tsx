import { useState } from "react";
import { useAuth } from "@shared/auth/AuthContext";
import { StatusBadge } from "@shared/components/StatusBadge";
import { ErrorBanner, FormField } from "@shared/components/FormField";
import { userApi } from "../api/userApi";

/**
 * Section 19: identity + MFA status, and voluntary enrollment if not
 * already enabled. No self-service MFA *reset* here — that's an admin-only
 * action (app/api/admin_mfa.py), correctly absent from the User API
 * surface entirely (section 48), not just hidden in this UI.
 */
export function Profile() {
  const { user, refresh } = useAuth();
  const [enrolling, setEnrolling] = useState(false);
  const [qrCode, setQrCode] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const [recoveryCodes, setRecoveryCodes] = useState<string[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function startEnroll() {
    setError(null);
    setEnrolling(true);
    try {
      const res = await userApi.mfaEnroll();
      setQrCode(res.qr_code_png_base64);
    } catch {
      setError("Could not start MFA enrollment.");
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
    } catch {
      setError("That code didn't work. Check your authenticator app and try again.");
    }
  }

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
      </div>

      {!user.mfa_enabled && (
        <div className="card">
          <h2 style={{ margin: "0 0 8px", fontSize: "1.1rem" }}>Enable multi-factor authentication</h2>
          {error && <ErrorBanner>{error}</ErrorBanner>}

          {recoveryCodes ? (
            <>
              <p className="text-muted">
                MFA is now enabled. Store these recovery codes now — they will not be shown again.
              </p>
              <div className="recovery-codes">
                {recoveryCodes.map((c) => (
                  <span key={c}>{c}</span>
                ))}
              </div>
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={() => navigator.clipboard.writeText(recoveryCodes.join("\n"))}
              >
                Copy to clipboard
              </button>
            </>
          ) : !qrCode ? (
            <>
              <p className="text-muted">Add an authenticator app as a second factor for your account.</p>
              <button type="button" className="btn btn-primary" onClick={() => void startEnroll()} disabled={enrolling}>
                Set up MFA
              </button>
            </>
          ) : (
            <form onSubmit={confirmEnroll}>
              <p className="text-muted">Scan this code with any TOTP authenticator app.</p>
              <img className="qr-code" src={qrCode} alt="TOTP enrollment QR code" width={180} height={180} />
              <FormField label="Enter the code from your app to confirm">
                <input value={code} onChange={(e) => setCode(e.target.value)} autoFocus required inputMode="numeric" />
              </FormField>
              <button type="submit" className="btn btn-primary">
                Confirm
              </button>
            </form>
          )}
        </div>
      )}
    </div>
  );
}
