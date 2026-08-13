import { useState } from "react";
import { useAuth } from "./AuthContext";
import { ApiError } from "../api/client";
import { ErrorBanner, FormField } from "../components/FormField";
import type { EnrollResponse, FirstRunAdminResponse, FirstRunMfaConfirmResponse } from "../api/types";

type Step =
  | { kind: "admin_form" }
  | { kind: "mfa_setup_qr"; mfaToken: string; qrCode: string }
  | { kind: "recovery_codes"; codes: string[] };

export interface SetupFlowApi {
  firstRunCreateAdmin: (payload: { setup_token: string; username: string; password: string }) => Promise<FirstRunAdminResponse>;
  mfaSetupEnroll: (mfaToken: string) => Promise<EnrollResponse>;
  firstRunMfaConfirm: (mfaToken: string, code: string) => Promise<FirstRunMfaConfirmResponse>;
}

/**
 * Roadmap B1.9 — shown instead of the normal login form when the backend
 * reports setup_required (see the Admin Portal's App.tsx). Deliberately a
 * parallel component to LoginFlow.tsx rather than a shared one: the two
 * flows submit different first steps (username+password vs. setup
 * token+username+password) and land on different backend endpoints, but
 * everything from "show the QR code" onward mirrors LoginFlow's
 * mfa_setup_qr/recovery_codes steps exactly — same markup, same classes,
 * same "don't refresh() until the user has actually seen their recovery
 * codes" ordering (see LoginFlow's own comment on that, the same
 * reasoning applies here unchanged) — because the underlying backend
 * mechanism (MFA enrollment) genuinely is the same one, just reached via
 * a different first step.
 *
 * No technical installation/database detail is ever shown here — only
 * the same three fields the task's own mockup describes.
 */
export function SetupFlow({ setupApi, portalLabel }: { setupApi: SetupFlowApi; portalLabel: string }) {
  const { refresh } = useAuth();
  const [step, setStep] = useState<Step>({ kind: "admin_form" });
  const [setupToken, setSetupToken] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submitAdminForm(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (password !== confirmPassword) {
      setError("Passwords do not match.");
      return;
    }
    setBusy(true);
    try {
      const result = await setupApi.firstRunCreateAdmin({ setup_token: setupToken, username, password });
      const enroll = await setupApi.mfaSetupEnroll(result.mfa_token);
      setStep({ kind: "mfa_setup_qr", mfaToken: result.mfa_token, qrCode: enroll.qr_code_png_base64 });
    } catch (e) {
      setError(errorMessage(e, "Could not create the administrator. Check the setup token and try again."));
    } finally {
      setBusy(false);
    }
  }

  async function submitMfaConfirm(e: React.FormEvent) {
    e.preventDefault();
    if (step.kind !== "mfa_setup_qr") return;
    setError(null);
    setBusy(true);
    try {
      const result = await setupApi.firstRunMfaConfirm(step.mfaToken, code);
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
              // Setup is fully complete server-side already; refresh only
              // now that the operator has actually seen the codes (same
              // ordering rationale as LoginFlow's identical step).
              await refresh();
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

        {step.kind === "admin_form" && (
          <form onSubmit={submitAdminForm}>
            <h1 style={{ fontSize: "1.15rem", margin: "0 0 4px" }}>Initial System Setup</h1>
            <p className="text-muted" style={{ margin: "0 0 20px" }}>
              Create the first administrator account.
            </p>
            <FormField label="Setup token" hint="Printed to the backend server/container console at startup">
              <input value={setupToken} onChange={(e) => setSetupToken(e.target.value)} autoFocus required />
            </FormField>
            <FormField label="Username">
              <input value={username} onChange={(e) => setUsername(e.target.value)} required />
            </FormField>
            <FormField label="Password">
              <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required />
            </FormField>
            <FormField label="Confirm password">
              <input
                type="password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                required
              />
            </FormField>
            <button type="submit" className="btn btn-primary" style={{ width: "100%" }} disabled={busy}>
              {busy ? <span className="spinner" /> : null} Create administrator
            </button>
          </form>
        )}

        {step.kind === "mfa_setup_qr" && (
          <form onSubmit={submitMfaConfirm}>
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
    if (e.status === 409) return "Setup has already been completed on this installation.";
    return e.detail || fallback;
  }
  return fallback;
}
