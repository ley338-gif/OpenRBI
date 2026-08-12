import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "./AuthContext";
import { ApiError } from "../api/client";
import { ErrorBanner, FormField } from "../components/FormField";
import { Icons } from "../components/Icons";
import type { EnrollResponse, SetupConfirmResponse } from "../api/types";

type Step =
  | { kind: "credentials" }
  | { kind: "mfa_verify"; mfaToken: string }
  | { kind: "mfa_setup_qr"; mfaToken: string; qrCode: string }
  | { kind: "recovery_codes"; codes: string[] };

export interface MfaFlowApi {
  mfaSetupEnroll: (mfaToken: string) => Promise<EnrollResponse>;
  mfaSetupConfirm: (mfaToken: string, code: string) => Promise<SetupConfirmResponse>;
  mfaVerify: (mfaToken: string, code: string) => Promise<unknown>;
}

/**
 * Shared between both portals (section 8) — the underlying endpoints
 * (/auth/login, /mfa/setup/enroll, /mfa/setup/confirm, /auth/mfa/verify)
 * are registered in every listener mode. Covers every branch app/api/
 * auth.py's /auth/login can return (section 9): immediate session, a
 * live-TOTP challenge for an already-enrolled account, or mandatory
 * first-time enrollment for a role that requires MFA. ADMIN/
 * SECURITY_REVIEWER accounts always hit the second or third branch, never
 * the first — MFA is mandatory for those roles — but this component
 * doesn't need to special-case that; it just follows whatever the backend
 * actually returns.
 */
export function LoginFlow({
  mfaApi,
  portalLabel,
  title,
}: {
  mfaApi: MfaFlowApi;
  portalLabel: string;
  /** Portal-specific heading shown under the brand, e.g. "Welcome to
   * OpenRBI" or "Admin Sign In". Falls back to a generic greeting. */
  title?: string;
}) {
  const { login, refresh } = useAuth();
  const navigate = useNavigate();
  const [step, setStep] = useState<Step>({ kind: "credentials" });
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submitCredentials(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const result = await login(username, password);
      if (result.status === "ok") {
        navigate("/", { replace: true });
      } else if (result.status === "mfa_required") {
        setStep({ kind: "mfa_verify", mfaToken: result.mfa_token! });
      } else {
        const enroll = await mfaApi.mfaSetupEnroll(result.mfa_token!);
        setStep({ kind: "mfa_setup_qr", mfaToken: result.mfa_token!, qrCode: enroll.qr_code_png_base64 });
      }
    } catch (e) {
      setError(errorMessage(e, "Login failed. Check your username and password."));
    } finally {
      setBusy(false);
    }
  }

  async function submitMfaVerify(e: React.FormEvent) {
    e.preventDefault();
    if (step.kind !== "mfa_verify") return;
    setError(null);
    setBusy(true);
    try {
      await mfaApi.mfaVerify(step.mfaToken, code);
      await refresh();
      navigate("/", { replace: true });
    } catch (e) {
      setError(errorMessage(e, "That code didn't work. Check your authenticator app and try again."));
    } finally {
      setBusy(false);
    }
  }

  async function submitMfaSetupConfirm(e: React.FormEvent) {
    e.preventDefault();
    if (step.kind !== "mfa_setup_qr") return;
    setError(null);
    setBusy(true);
    try {
      const result = await mfaApi.mfaSetupConfirm(step.mfaToken, code);
      // Deliberately NOT calling refresh() here yet. The backend already
      // set the session cookie (app/api/mfa.py's setup_confirm), but this
      // component is still mounted at "/login", where the route element is
      // `user ? <Navigate to="/" /> : <LoginFlow/>` — refreshing here would
      // make `user` truthy immediately, swapping LoginFlow out for the
      // redirect in the very same render and skipping the recovery-codes
      // step entirely (a real bug caught only by an automated, non-manual
      // test: a human clicking through never triggers the race, but it's
      // fully deterministic under React's batching, and would silently
      // lose the user's one-time recovery codes). refresh() now happens in
      // handleContinue below, only once the user has actually seen them.
      setStep({ kind: "recovery_codes", codes: result.recovery_codes });
    } catch (e) {
      setError(errorMessage(e, "That code didn't work. Check your authenticator app and try again."));
    } finally {
      setBusy(false);
    }
  }

  if (step.kind === "recovery_codes") {
    return (
      <div className="login-shell">
        <div className="login-card">
          <Brand portalLabel={portalLabel} />
          <h1 style={{ fontSize: "1.1rem" }}>Save your recovery codes</h1>
          <p className="text-muted">
            Store these recovery codes now. They will not be shown again. Each one can be used once, in place of a code
            from your authenticator app, if you lose access to it.
          </p>
          <div className="recovery-codes">
            {step.codes.map((c) => (
              <span key={c}>{c}</span>
            ))}
          </div>
          <button
            type="button"
            className="btn btn-secondary"
            style={{ width: "100%", marginBottom: "8px" }}
            onClick={() => navigator.clipboard.writeText(step.codes.join("\n"))}
          >
            Copy to clipboard
          </button>
          <button
            type="button"
            className="btn btn-primary"
            style={{ width: "100%" }}
            onClick={async () => {
              // Refresh only now — the backend already holds a valid
              // session (set by mfaSetupConfirm), but committing that to
              // client state earlier would swap this screen out before the
              // user ever saw their recovery codes (see the comment above
              // submitMfaSetupConfirm).
              await refresh();
              navigate("/", { replace: true });
            }}
          >
            I've saved these, continue
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="login-shell">
      <div className="login-card">
        <Brand portalLabel={portalLabel} />
        {error && <ErrorBanner>{error}</ErrorBanner>}

        {step.kind === "credentials" && (
          <form onSubmit={submitCredentials}>
            {title && <h1 style={{ fontSize: "1.15rem", margin: "0 0 20px" }}>{title}</h1>}
            <FormField label="Username">
              <input value={username} onChange={(e) => setUsername(e.target.value)} autoFocus required />
            </FormField>
            <FormField label="Password">
              <div className="password-field">
                <input
                  type={showPassword ? "text" : "password"}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  aria-label="Password"
                  required
                />
                <button
                  type="button"
                  className="password-toggle"
                  onClick={() => setShowPassword((v) => !v)}
                  aria-label={showPassword ? "Hide password" : "Show password"}
                  tabIndex={-1}
                >
                  {showPassword ? <Icons.EyeOff /> : <Icons.Eye />}
                </button>
              </div>
            </FormField>
            <button type="submit" className="btn btn-primary" style={{ width: "100%" }} disabled={busy}>
              {busy ? <span className="spinner" /> : null} Log in
            </button>
            <p className="login-footnote">Forgot your password? Contact your administrator.</p>
          </form>
        )}

        {step.kind === "mfa_verify" && (
          <form onSubmit={submitMfaVerify}>
            <p className="text-muted">Enter the 6-digit code from your authenticator app.</p>
            <FormField label="Authentication code">
              <input value={code} onChange={(e) => setCode(e.target.value)} autoFocus required inputMode="numeric" />
            </FormField>
            <button type="submit" className="btn btn-primary" style={{ width: "100%" }} disabled={busy}>
              {busy ? <span className="spinner" /> : null} Verify
            </button>
          </form>
        )}

        {step.kind === "mfa_setup_qr" && (
          <form onSubmit={submitMfaSetupConfirm}>
            <p className="text-muted">
              Multi-factor authentication is required for your account. Scan this code with any TOTP authenticator app.
            </p>
            <img className="qr-code" src={step.qrCode} alt="TOTP enrollment QR code" width={180} height={180} />
            <FormField label="Enter the code from your app to confirm">
              <input value={code} onChange={(e) => setCode(e.target.value)} autoFocus required inputMode="numeric" />
            </FormField>
            <button type="submit" className="btn btn-primary" style={{ width: "100%" }} disabled={busy}>
              {busy ? <span className="spinner" /> : null} Confirm and continue
            </button>
          </form>
        )}
      </div>
    </div>
  );
}

function Brand({ portalLabel }: { portalLabel: string }) {
  return (
    <div className="brand">
      <img className="brand-lockup" src="/logo.png" alt="OpenRBI — Remote Browser Isolation" />
      <span className="subtitle">{portalLabel}</span>
    </div>
  );
}

function errorMessage(e: unknown, fallback: string): string {
  if (e instanceof ApiError) {
    if (e.status === 429) return "Too many failed attempts. Try again in a few minutes.";
    return e.detail || fallback;
  }
  return fallback;
}
