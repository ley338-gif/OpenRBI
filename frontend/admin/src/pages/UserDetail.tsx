import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { StatusBadge } from "@shared/components/StatusBadge";
import { ConfirmDialog } from "@shared/components/ConfirmDialog";
import { LoadingBlock, ErrorState, EmptyState } from "@shared/components/States";
import { FormField } from "@shared/components/FormField";
import { PageHeader } from "@shared/components/PageHeader";
import { DefinitionList } from "@shared/components/DefinitionList";
import { ActionMenu } from "@shared/components/ActionMenu";
import { AttachList, type AttachListItem } from "@shared/components/AttachList";
import { useToast } from "@shared/components/Toast";
import { formatDateTime } from "@shared/format";
import type { AdminSessionDto, LockoutStatusDto, SecurityEventDto, UserSummaryDto } from "@shared/api/types";
import { adminApi } from "../api/adminApi";

type PendingAction =
  | { kind: "disable" }
  | { kind: "enable" }
  | { kind: "reset-mfa" }
  | { kind: "revoke-sessions" }
  | { kind: "lock" }
  | { kind: "unlock" }
  | { kind: "session"; action: "disconnect" | "isolate" | "restore" | "kill"; sessionId: string };

export function UserDetail() {
  const { id } = useParams<{ id: string }>();
  const { notify } = useToast();
  const [user, setUser] = useState<UserSummaryDto | null>(null);
  const [sessions, setSessions] = useState<AdminSessionDto[] | null>(null);
  const [events, setEvents] = useState<SecurityEventDto[]>([]);
  const [lockout, setLockout] = useState<LockoutStatusDto | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState<PendingAction | null>(null);
  const [busy, setBusy] = useState(false);
  const [showResetPassword, setShowResetPassword] = useState(false);
  const [newPassword, setNewPassword] = useState("");
  const [groupsBusy, setGroupsBusy] = useState(false);

  function load() {
    if (!id) return;
    Promise.all([
      adminApi.getUser(id),
      adminApi.userSessions(id),
      adminApi.listSecurityEvents({ user_id: id, limit: 15 }),
      adminApi.getLockoutStatus(id),
    ])
      .then(([u, s, e, l]) => {
        setUser(u);
        setSessions(s);
        setEvents(e);
        setLockout(l);
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
      } else if (pending.kind === "revoke-sessions") {
        const result = await adminApi.revokeUserSessions(id);
        notify(result.terminated_count === 0 ? "No live sessions to terminate" : `Terminated ${result.terminated_count} session(s)`);
        load();
      } else if (pending.kind === "lock") {
        await adminApi.lockAccount(id);
        notify("Account locked — logins are blocked and any active session was revoked");
        load();
      } else if (pending.kind === "unlock") {
        await adminApi.unlockAccount(id);
        notify("Account unlocked");
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

  async function searchGroupsForUser(query: string): Promise<AttachListItem[]> {
    const groups = await adminApi.listGroups();
    const needle = query.toLowerCase();
    return groups
      .filter((g) => g.name.toLowerCase().includes(needle))
      .slice(0, 10)
      .map((g) => ({ id: g.id, label: g.name, meta: `${g.member_count} member${g.member_count === 1 ? "" : "s"}` }));
  }
  async function addUserToGroup(groupId: string) {
    if (!id) return;
    setGroupsBusy(true);
    try { await adminApi.addGroupMember(groupId, id); notify("Added to group"); load(); }
    catch { notify("Could not add this group", "error"); } finally { setGroupsBusy(false); }
  }
  async function removeUserFromGroup(groupId: string) {
    if (!id) return;
    setGroupsBusy(true);
    try { await adminApi.removeGroupMember(groupId, id); notify("Removed from group"); load(); }
    catch { notify("Could not remove this group", "error"); } finally { setGroupsBusy(false); }
  }

  if (error) return <div className="page"><ErrorState>{error}</ErrorState></div>;
  if (!user || !sessions || !lockout) return <LoadingBlock label="Loading user…" />;

  return (
    <div className="page">
      <p><Link to="/users">← Users</Link></p>
      <PageHeader
        title={user.username}
        meta={<StatusBadge value={user.is_active ? "ACTIVE" : "DISABLED"} />}
        actions={
          <>
            {user.is_active ? (
              <button type="button" className="btn btn-danger" onClick={() => setPending({ kind: "disable" })}>
                Disable
              </button>
            ) : (
              <button type="button" className="btn btn-secondary" onClick={() => setPending({ kind: "enable" })}>
                Enable
              </button>
            )}
            {user.auth_source === "LOCAL" ? (
              <button type="button" className="btn btn-secondary" onClick={() => setShowResetPassword(true)}>
                Reset password
              </button>
            ) : (
              <span className="text-muted" style={{ alignSelf: "center", fontSize: "0.8rem" }}>Password managed by LDAP</span>
            )}
            {user.mfa_enabled && (
              <button type="button" className="btn btn-danger" onClick={() => setPending({ kind: "reset-mfa" })}>
                Reset MFA
              </button>
            )}
            {lockout.locked ? (
              <button type="button" className="btn btn-secondary" onClick={() => setPending({ kind: "unlock" })}>
                Unlock account
              </button>
            ) : (
              <button type="button" className="btn btn-danger" onClick={() => setPending({ kind: "lock" })}>
                Lock account
              </button>
            )}
          </>
        }
      />

      <div className="card">
        <div className="section-header">
          <h2>Overview</h2>
        </div>
        <DefinitionList
          items={[
            { label: "Role", value: user.role },
            { label: "Authentication source", value: <StatusBadge value={user.auth_source} /> },
            { label: "MFA", value: <StatusBadge value={user.mfa_enabled ? "ENABLED" : "NOT ENABLED"} /> },
            {
              label: "Login lockout",
              value: (
                <>
                  <StatusBadge value={lockout.locked ? "LOCKED" : "NOT LOCKED"} />
                  {lockout.locked && lockout.locked_seconds_remaining !== null && (
                    <span className="text-muted" style={{ marginLeft: "6px", fontSize: "0.85rem" }}>
                      clears in {Math.ceil(lockout.locked_seconds_remaining / 60)} min
                    </span>
                  )}
                </>
              ),
            },
            { label: "Created", value: formatDateTime(user.created_at) },
          ]}
        />

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
        <div className="section-header">
          <h2>Groups</h2>
        </div>
        <AttachList
          entityLabel="group"
          attached={user.groups.map((g) => ({ id: g.id, label: g.name }))}
          onSearch={searchGroupsForUser}
          onAdd={addUserToGroup}
          onRemove={removeUserFromGroup}
          busy={groupsBusy}
          emptyLabel="This user isn't in any groups yet."
        />
      </div>

      <div className="card">
        <div className="section-header">
          <h2>Sessions</h2>
          {sessions.some((s) => s.status !== "TERMINATED" && s.status !== "FAILED") && (
            <button type="button" className="btn btn-danger btn-sm" onClick={() => setPending({ kind: "revoke-sessions" })}>
              Terminate all sessions
            </button>
          )}
        </div>
        {sessions.length === 0 ? (
          <EmptyState title="No sessions">This user has never started a Secure Browser session.</EmptyState>
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
        <div className="section-header">
          <h2>Recent activity</h2>
        </div>
        {events.length === 0 ? (
          <EmptyState title="No recorded activity">Security events involving this account will appear here.</EmptyState>
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
      {pending?.kind === "lock" && (
        <ConfirmDialog
          title={`Lock ${user.username}'s account?`}
          description="Immediately blocks new logins for 15 minutes (the same lockout the system applies automatically after repeated failed attempts) and revokes any session they currently have."
          confirmLabel="Lock account"
          danger
          busy={busy}
          onConfirm={() => void confirmPending()}
          onCancel={() => setPending(null)}
        />
      )}
      {pending?.kind === "unlock" && (
        <ConfirmDialog
          title={`Unlock ${user.username}'s account?`}
          description="Allows the user to log in again immediately, instead of waiting for the lockout to clear on its own."
          confirmLabel="Unlock account"
          busy={busy}
          onConfirm={() => void confirmPending()}
          onCancel={() => setPending(null)}
        />
      )}
      {pending?.kind === "revoke-sessions" && (
        <ConfirmDialog
          title={`Terminate all sessions for ${user.username}?`}
          description="Immediately terminates every live browser sandbox this user currently has. Unsaved browser state in each will be lost. This cannot be undone."
          confirmLabel="Terminate all"
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

  // The one contextual action stays a visible button (never buried in a
  // menu, section 23); Disconnect — the least consequential option — moves
  // into the "⋯" menu alongside it. Kill stays visible too, since it's the
  // most severe action and shouldn't require an extra click to discover.
  const primary =
    session.status === "ISOLATED"
      ? { label: "Restore", action: "restore" as const }
      : { label: "Isolate", action: "isolate" as const };

  const menuItems = [];
  if (session.status === "ACTIVE" || session.status === "DISCONNECTED") {
    menuItems.push({ label: "Disconnect", onSelect: () => onAction("disconnect") });
  }

  return (
    <div style={{ display: "flex", gap: "4px", justifyContent: "flex-end" }}>
      <button type="button" className="btn btn-secondary btn-sm" onClick={() => onAction(primary.action)}>
        {primary.label}
      </button>
      <button type="button" className="btn btn-danger btn-sm" onClick={() => onAction("kill")}>
        Kill
      </button>
      {menuItems.length > 0 && <ActionMenu items={menuItems} label="More session actions" />}
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
