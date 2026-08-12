import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { StatusBadge } from "@shared/components/StatusBadge";
import { ConfirmDialog } from "@shared/components/ConfirmDialog";
import { LoadingBlock, ErrorState } from "@shared/components/States";
import { useToast } from "@shared/components/Toast";
import { formatDateTime } from "@shared/format";
import type { AdminSessionDto, SecurityEventDto } from "@shared/api/types";
import { adminApi } from "../api/adminApi";

type Action = "disconnect" | "isolate" | "restore" | "kill";

export function SessionDetail() {
  const { id } = useParams<{ id: string }>();
  const { notify } = useToast();
  const [session, setSession] = useState<AdminSessionDto | null>(null);
  const [events, setEvents] = useState<SecurityEventDto[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [pendingAction, setPendingAction] = useState<Action | null>(null);
  const [busy, setBusy] = useState(false);

  function load() {
    if (!id) return;
    Promise.all([adminApi.getSession(id), adminApi.listSecurityEvents({ session_id: id, limit: 25 })])
      .then(([s, e]) => {
        setSession(s);
        setEvents(e);
      })
      .catch(() => setError("Could not load this session."));
  }
  useEffect(load, [id]);

  async function confirm() {
    if (!pendingAction || !session) return;
    setBusy(true);
    try {
      const call = {
        disconnect: adminApi.disconnectSession,
        isolate: adminApi.isolateSession,
        restore: adminApi.restoreSession,
        kill: adminApi.killSession,
      }[pendingAction];
      const updated = await call(session.id);
      setSession(updated);
      notify(`Session ${pendingAction}d`);
      load();
    } catch {
      notify("Action failed", "error");
    } finally {
      setBusy(false);
      setPendingAction(null);
    }
  }

  if (error) return <div className="page"><ErrorState>{error}</ErrorState></div>;
  if (!session) return <LoadingBlock label="Loading session…" />;

  const live = session.status !== "TERMINATED" && session.status !== "FAILED";

  const copy: Record<Action, { title: string; description: string; danger?: boolean }> = {
    disconnect: {
      title: `Disconnect session ${session.id.slice(0, 8)}?`,
      description: "Drops the remote-display connection. The sandbox keeps running.",
    },
    isolate: {
      title: `Isolate session ${session.id.slice(0, 8)}?`,
      description:
        "Immediately cuts network access, uploads, downloads, and clipboard for this session. The sandbox is preserved for review.",
      danger: true,
    },
    restore: {
      title: `Restore session ${session.id.slice(0, 8)}?`,
      description: "Re-connects this session's network access, reversing an earlier isolation.",
    },
    kill: {
      title: `Kill session ${session.id.slice(0, 8)}?`,
      description: "This immediately terminates the user's browser sandbox. Unsaved browser state will be lost. This cannot be undone.",
      danger: true,
    },
  };

  return (
    <div className="page">
      <p><Link to="/sessions">← Sessions</Link></p>
      <div className="flex-between">
        <h1 style={{ marginBottom: 0 }}>
          Session <span className="mono">{session.id.slice(0, 8)}</span>
        </h1>
        {live && (
          <div style={{ display: "flex", gap: "8px" }}>
            {(session.status === "ACTIVE" || session.status === "DISCONNECTED") && (
              <>
                <button type="button" className="btn btn-secondary" onClick={() => setPendingAction("disconnect")}>
                  Disconnect
                </button>
                <button type="button" className="btn btn-secondary" onClick={() => setPendingAction("isolate")}>
                  Isolate
                </button>
              </>
            )}
            {session.status === "ISOLATED" && (
              <button type="button" className="btn btn-secondary" onClick={() => setPendingAction("restore")}>
                Restore
              </button>
            )}
            <button type="button" className="btn btn-danger" onClick={() => setPendingAction("kill")}>
              Kill
            </button>
          </div>
        )}
      </div>

      <div className="card">
        <dl className="detail-grid">
          <div>
            <dt>User</dt>
            <dd><Link to={`/users/${session.user_id}`}>{session.username}</Link></dd>
          </div>
          <div>
            <dt>Status</dt>
            <dd><StatusBadge value={session.status} /></dd>
          </div>
          <div>
            <dt>Browser</dt>
            <dd>{session.browser}</dd>
          </div>
          <div>
            <dt>Sandbox backend</dt>
            <dd>{session.sandbox_backend}</dd>
          </div>
          <div>
            <dt>Display backend</dt>
            <dd>{session.display_backend}</dd>
          </div>
          <div>
            <dt>Created</dt>
            <dd>{formatDateTime(session.created_at)}</dd>
          </div>
          <div>
            <dt>Started</dt>
            <dd>{formatDateTime(session.started_at)}</dd>
          </div>
          <div>
            <dt>Ended</dt>
            <dd>{formatDateTime(session.ended_at)}</dd>
          </div>
          <div>
            <dt>Resource limits</dt>
            <dd>
              {session.cpu_limit} CPU · {session.ram_limit_mb} MB RAM · {session.pid_limit} PIDs · {session.disk_limit_mb} MB disk
            </dd>
          </div>
        </dl>
      </div>

      <div className="card">
        <h2 style={{ margin: "0 0 8px", fontSize: "1.1rem" }}>Recent security events</h2>
        {events.length === 0 ? (
          <p className="text-muted">No events recorded for this session.</p>
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

      {pendingAction && (
        <ConfirmDialog
          title={copy[pendingAction].title}
          description={copy[pendingAction].description}
          confirmLabel={pendingAction[0].toUpperCase() + pendingAction.slice(1)}
          danger={copy[pendingAction].danger}
          busy={busy}
          onConfirm={() => void confirm()}
          onCancel={() => setPendingAction(null)}
        />
      )}
    </div>
  );
}
