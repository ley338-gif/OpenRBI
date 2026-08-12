import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { StatusBadge } from "@shared/components/StatusBadge";
import { ConfirmDialog } from "@shared/components/ConfirmDialog";
import { LoadingBlock, ErrorState } from "@shared/components/States";
import { FormField } from "@shared/components/FormField";
import { useToast } from "@shared/components/Toast";
import { formatDateTime } from "@shared/format";
import type { AdminSessionDto, SecurityEventDto, UserSummaryDto } from "@shared/api/types";
import { adminApi } from "../api/adminApi";

type PendingAction =
  | { kind: "disable" }
  | { kind: "enable" }
  | { kind: "reset-mfa" }
  | { kind: "session"; action: "disconnect" | "isolate" | "restore" | "kill"; sessionId: string };

export function UserDetail() {
  const { id } = useParams<{ id: string }>();
  const { notify } = useToast();
  const [user, setUser] = useState<UserSummaryDto | null>(null);
  const [sessions, setSessions] = useState<AdminSessionDto[] | null>(null);
  const [events, setEvents] = useState<SecurityEventDto[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState<PendingAction | null>(null);
  const [busy, setBusy] = useState(false);
  const [showResetPassword, setShowResetPassword] = useState(false);
  const [newPassword, setNewPassword] = useState("");

  function load() {
    if (!id) return;
    Promise.all([adminApi.getUser(id), adminApi.userSessions(id), adminApi.listSecurityEvents({ user_id: id, limit: 15 })])
      .then(([u, s, e]) => {
        setUser(u);
        setSessions(s);
        setEvents(e);
      })
      .catch(() => setError("Could not load this user. They may not exist, or the backend is unavailable."));
  }

  useEffect(load, [id]);

  async function confirmPending() {
    if (!pending || !id) return;
    setBusy(true);
    try {
      if (pending.kind === "disable") {
        setUser(await adminApi.disableUser(id));
        notify("User disabled");
      } else if (pending.kind === "enable") {
        setUser(await adminApi.enableUser(id));
        notify("User enabled");
      } else if (pending.kind === "reset-mfa") {
        await adminApi.resetUserMfa(id);
        notify("MFA reset — the user will be asked to re-enroll on next login");
        load();
      } else {
        const call = {
          disconnect: adminApi.disconnectSession,
          isolate: adminApi.isolateSession,
          restore: adminApi.restoreSession,
          kill: adminApi.killSession,
        }[pending.action];
        const updated = await call(pending.sessionId);
        setSessions((prev) => prev!.map((s) => (s.id === updated.id ? updated : s)));
        notify(`Session ${pending.action}d`);
      }
    } catch {
      notify("Action failed", "error");
    } finally {
      setBusy(false);
      setPending(null);
    }
  }

  async function submitResetPassword(e: React.FormEvent) {
    e.preventDefault();
    if (!id) return;
    setBusy(true);
    try {
      await adminApi.resetPassword(id, newPassword);
      notify("Password reset");
      setShowResetPassword(false);
      setNewPassword("");
    } catch {
      notify("Could not reset password", "error");
    } finally {
      setBusy(false);
    }
  }

  if (error) return <div className="page"><ErrorState>{error}</ErrorState></div>;
  if (!user || !sessions) return <LoadingBlock label="Loading user…" />;

  return (
    <div className="page">
      <p><Link to="/users">← Users</Link></p>
      <h1>{user.username}</h1>

      <div className="card">
        <dl className="detail-grid">
          <div>
            <dt>Status</dt>
            <dd><StatusBadge value={user.is_active ? "ACTIVE" : "DISABLED"} /></dd>
          </div>
          <div>
            <dt>Role</dt>
            <dd>{user.role}</dd>
          </div>
          <div>
            <dt>Groups</dt>
            <dd>{user.groups.join(", ") || "—"}</dd>
          </div>
          <div>
            <dt>MFA</dt>
            <dd><StatusBadge value={user.mfa_enabled ? "ENABLED" : "NOT ENABLED"} /></dd>
          </div>
          <div>
            <dt>Created</dt>
            <dd>{formatDateTime(user.created_at)}</dd>
          </div>
        </dl>
        <div style={{ display: "flex", gap: "8px" }}>
          {user.is_active ? (
            <button type="button" className="btn btn-danger" onClick={() => setPending({ kind: "disable" })}>
              Disable
            </button>
          ) : (
            <button type="button" className="btn btn-secondary" onClick={() => setPending({ kind: "enable" })}>
              Enable
            </button>
          )}
          <button type="button" className="btn btn-secondary" onClick={() => setShowResetPassword(true)}>
            Reset password
          </button>
          {user.mfa_enabled && (
            <button type="button" className="btn btn-danger" onClick={() => setPending({ kind: "reset-mfa" })}>
              Reset MFA
            </button>
          )}
        </div>

        {showResetPassword && (
          <form onSubmit={submitResetPassword} style={{ marginTop: "16px", maxWidth: "320px" }}>
            <FormField label="New password">
              <input type="password" value={newPassword} onChange={(e) => setNewPassword(e.target.value)} required autoFocus />
            </FormField>
            <div style={{ display: "flex", gap: "8px" }}>
              <button type="submit" className="btn btn-primary btn-sm" disabled={busy}>
                Save
              </button>
              <button type="button" className="btn btn-secondary btn-sm" onClick={() => setShowResetPassword(false)}>
                Cancel
              </button>
            </div>
          </form>
        )}
      </div>

      <div className="card">
        <h2 style={{ margin: "0 0 8px", fontSize: "1.1rem" }}>Sessions</h2>
        {sessions.length === 0 ? (
          <p className="text-muted">No sessions.</p>
        ) : (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Session</th>
                  <th>Status</th>
                  <th>Started</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {sessions.map((s) => (
                  <tr key={s.id}>
                    <td>
                      <Link to={`/sessions/${s.id}`} className="mono">
                        {s.id.slice(0, 8)}
                      </Link>
                    </td>
                    <td><StatusBadge value={s.status} /></td>
                    <td>{formatDateTime(s.started_at)}</td>
                    <td>
                      <SessionActions
                        session={s}
                        onAction={(action) => setPending({ kind: "session", action, sessionId: s.id })}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="card">
        <h2 style={{ margin: "0 0 8px", fontSize: "1.1rem" }}>Recent activity</h2>
        {events.length === 0 ? (
          <p className="text-muted">No recorded activity.</p>
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th>Event</th>
                <th>Time</th>
              </tr>
            </thead>
            <tbody>
              {events.map((e) => (
                <tr key={e.id}>
                  <td>{e.event_type}</td>
                  <td>{formatDateTime(e.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {pending?.kind === "disable" && (
        <ConfirmDialog
          title={`Disable ${user.username}?`}
          description="This immediately prevents the user from logging in or starting new sessions. Existing sessions are not affected."
          confirmLabel="Disable"
          danger
          busy={busy}
          onConfirm={() => void confirmPending()}
          onCancel={() => setPending(null)}
        />
      )}
      {pending?.kind === "enable" && (
        <ConfirmDialog
          title={`Enable ${user.username}?`}
          description="This allows the user to log in again."
          confirmLabel="Enable"
          busy={busy}
          onConfirm={() => void confirmPending()}
          onCancel={() => setPending(null)}
        />
      )}
      {pending?.kind === "reset-mfa" && (
        <ConfirmDialog
          title={`Reset MFA for ${user.username}?`}
          description="This disables their current TOTP enrollment and invalidates all their recovery codes. They will be required to re-enroll on their next login."
          confirmLabel="Reset MFA"
          danger
          busy={busy}
          onConfirm={() => void confirmPending()}
          onCancel={() => setPending(null)}
        />
      )}
      {pending?.kind === "session" && (
        <SessionActionConfirm pending={pending} busy={busy} onConfirm={() => void confirmPending()} onCancel={() => setPending(null)} />
      )}
    </div>
  );
}

function SessionActions({
  session,
  onAction,
}: {
  session: AdminSessionDto;
  onAction: (action: "disconnect" | "isolate" | "restore" | "kill") => void;
}) {
  const live = session.status !== "TERMINATED" && session.status !== "FAILED";
  if (!live) return <span className="text-muted">—</span>;
  return (
    <div style={{ display: "flex", gap: "4px" }}>
      {(session.status === "ACTIVE" || session.status === "DISCONNECTED") && (
        <>
          <button type="button" className="btn btn-secondary btn-sm" onClick={() => onAction("disconnect")}>
            Disconnect
          </button>
          <button type="button" className="btn btn-secondary btn-sm" onClick={() => onAction("isolate")}>
            Isolate
          </button>
        </>
      )}
      {session.status === "ISOLATED" && (
        <button type="button" className="btn btn-secondary btn-sm" onClick={() => onAction("restore")}>
          Restore
        </button>
      )}
      <button type="button" className="btn btn-danger btn-sm" onClick={() => onAction("kill")}>
        Kill
      </button>
    </div>
  );
}

function SessionActionConfirm({
  pending,
  busy,
  onConfirm,
  onCancel,
}: {
  pending: { action: "disconnect" | "isolate" | "restore" | "kill"; sessionId: string };
  busy: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const short = pending.sessionId.slice(0, 8);
  const copy = {
    disconnect: { title: `Disconnect session ${short}?`, description: "Drops the remote-display connection. The sandbox keeps running." },
    isolate: {
      title: `Isolate session ${short}?`,
      description: "Immediately cuts network access, uploads, downloads, and clipboard for this session. The sandbox is preserved for review.",
    },
    restore: { title: `Restore session ${short}?`, description: "Re-connects this session's network access, reversing an earlier isolation." },
    kill: {
      title: `Kill session ${short}?`,
      description: "This immediately terminates the user's browser sandbox. Unsaved browser state will be lost. This cannot be undone.",
    },
  }[pending.action];
  return (
    <ConfirmDialog
      title={copy.title}
      description={copy.description}
      confirmLabel={pending.action[0].toUpperCase() + pending.action.slice(1)}
      danger={pending.action === "kill" || pending.action === "isolate"}
      busy={busy}
      onConfirm={onConfirm}
      onCancel={onCancel}
    />
  );
}
