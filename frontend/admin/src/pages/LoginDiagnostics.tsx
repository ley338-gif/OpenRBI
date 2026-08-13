import { useState } from "react";
import { Link } from "react-router-dom";
import { StatusBadge } from "@shared/components/StatusBadge";
import { ApiError } from "@shared/api/client";
import { formatDateTime } from "@shared/format";
import type { LoginDiagnosticsResponseDto } from "@shared/api/types";
import { adminApi } from "../api/adminApi";

/**
 * Roadmap B1.10.6 — "why can't this user log in?" Strictly read-only:
 * every field here is a signal /auth/login already checks (lockout,
 * disabled, MFA-mandatory-but-not-enrolled, LDAP reachability from the
 * account's perspective) — this page never tests a password and never
 * authenticates on the user's behalf. When it truly finds nothing, it
 * says so plainly rather than implying the password itself was checked.
 */
export function LoginDiagnostics() {
  const [username, setUsername] = useState("");
  const [result, setResult] = useState<LoginDiagnosticsResponseDto | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!username.trim()) return;
    setBusy(true);
    setError(null);
    try {
      setResult(await adminApi.loginDiagnostics(username.trim()));
    } catch (err) {
      setResult(null);
      setError(err instanceof ApiError ? err.detail : "Could not run diagnostics. The backend may be unavailable.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="page">
      <h1>Login Diagnostics</h1>
      <p className="text-muted">
        Read-only. This never tests a password or logs in on the user's behalf — it only shows the same signals
        the real login check already evaluates.
      </p>

      <div className="card">
        <form onSubmit={submit} className="filter-bar" style={{ marginBottom: 0 }}>
          <input
            placeholder="Username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            style={{ minWidth: "260px" }}
            autoFocus
          />
          <button type="submit" className="btn btn-primary" disabled={busy || !username.trim()}>
            {busy ? <span className="spinner" /> : "Diagnose"}
          </button>
        </form>
      </div>

      {error && (
        <div className="card">
          <p className="text-muted">{error}</p>
        </div>
      )}

      {result && (
        <>
          <div className="card">
            <h2 style={{ margin: "0 0 8px", fontSize: "1.1rem" }}>Possible reasons</h2>
            {result.possible_reasons.length === 0 ? (
              <p className="text-muted">No blockers found.</p>
            ) : (
              <ul style={{ margin: 0, paddingLeft: "20px" }}>
                {result.possible_reasons.map((reason, i) => (
                  <li key={i} style={{ marginBottom: "6px" }}>
                    {reason}
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div className="card">
            <h2 style={{ margin: "0 0 8px", fontSize: "1.1rem" }}>Account state</h2>
            <dl className="detail-grid">
              <div>
                <dt>Account exists</dt>
                <dd><StatusBadge value={result.account_exists ? "YES" : "NO"} /></dd>
              </div>
              {result.account_exists && (
                <>
                  <div>
                    <dt>Status</dt>
                    <dd><StatusBadge value={result.is_active ? "ACTIVE" : "DISABLED"} /></dd>
                  </div>
                  <div>
                    <dt>MFA</dt>
                    <dd><StatusBadge value={result.mfa_enabled ? "ENABLED" : "NOT ENABLED"} /></dd>
                  </div>
                  <div>
                    <dt>Auth source</dt>
                    <dd>{result.auth_source === "local" ? "Local password" : "LDAP"}</dd>
                  </div>
                </>
              )}
              <div>
                <dt>Login lockout</dt>
                <dd>
                  <StatusBadge value={result.lockout.locked ? "LOCKED" : "NOT LOCKED"} />
                  {result.lockout.locked && result.lockout.locked_seconds_remaining !== null && (
                    <span className="text-muted" style={{ marginLeft: "6px", fontSize: "0.85rem" }}>
                      clears in {Math.ceil(result.lockout.locked_seconds_remaining / 60)} min
                    </span>
                  )}
                </dd>
              </div>
              <div>
                <dt>LDAP enabled system-wide</dt>
                <dd>{result.ldap_enabled ? "Yes" : "No"}</dd>
              </div>
            </dl>
            {result.user_id && (
              <p style={{ marginTop: "12px" }}>
                <Link to={`/users/${result.user_id}`}>View full user detail →</Link>
              </p>
            )}
          </div>

          <div className="card">
            <h2 style={{ margin: "0 0 8px", fontSize: "1.1rem" }}>Recent failed attempts (last hour)</h2>
            {result.recent_failed_attempts.length === 0 ? (
              <p className="text-muted">None.</p>
            ) : (
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Event</th>
                    <th>Time</th>
                  </tr>
                </thead>
                <tbody>
                  {result.recent_failed_attempts.map((e, i) => (
                    <tr key={i}>
                      <td>{e.event_type}</td>
                      <td>{formatDateTime(e.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </>
      )}
    </div>
  );
}
