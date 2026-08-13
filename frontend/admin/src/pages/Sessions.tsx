import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { StatusBadge } from "@shared/components/StatusBadge";
import { LoadingBlock, EmptyState, ErrorState } from "@shared/components/States";
import { PageHeader } from "@shared/components/PageHeader";
import { TableToolbar } from "@shared/components/TableToolbar";
import { formatDateTime, formatDuration } from "@shared/format";
import type { AdminSessionDto, SessionStatus } from "@shared/api/types";
import { adminApi } from "../api/adminApi";

const STATUSES: SessionStatus[] = [
  "QUEUED",
  "STARTING",
  "ACTIVE",
  "DISCONNECTED",
  "ISOLATING",
  "ISOLATED",
  "TERMINATING",
  "TERMINATED",
  "FAILED",
];

/**
 * GET /admin/sessions (app/api/admin_sessions.py) has no server-side
 * status/user filter or pagination today — filtering here is
 * client-side over whatever the endpoint returns. Documented gap (section
 * 26/39), not silently pretending the backend supports it.
 */
export function Sessions() {
  const [sessions, setSessions] = useState<AdminSessionDto[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<string>("");
  const [userFilter, setUserFilter] = useState("");

  function load() {
    setError(null);
    adminApi.listSessions().then(setSessions).catch(() => setError("Could not load sessions."));
  }

  useEffect(load, []);

  const filtered = useMemo(() => {
    if (!sessions) return [];
    return sessions.filter(
      (s) =>
        (!statusFilter || s.status === statusFilter) &&
        (!userFilter || s.username.toLowerCase().includes(userFilter.toLowerCase())),
    );
  }, [sessions, statusFilter, userFilter]);

  if (error) {
    return (
      <div className="page">
        <ErrorState action={<button type="button" className="btn btn-secondary btn-sm" onClick={load}>Try again</button>}>
          {error}
        </ErrorState>
      </div>
    );
  }
  if (!sessions) return <LoadingBlock label="Loading sessions…" />;

  return (
    <div className="page">
      <PageHeader title="Sessions" subtitle="Active, isolated, and completed browser sessions across all users." />

      <TableToolbar
        search={userFilter}
        onSearchChange={setUserFilter}
        searchPlaceholder="Filter by username…"
        filters={
          <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)} aria-label="Filter by status">
            <option value="">All statuses</option>
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        }
        onRefresh={load}
      />

      {filtered.length === 0 ? (
        <EmptyState title="No sessions match">Try a different filter, or check back once a session is running.</EmptyState>
      ) : (
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>Session</th>
                <th>User</th>
                <th>Status</th>
                <th>Browser</th>
                <th>Started</th>
                <th>Duration</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((s) => (
                <tr key={s.id}>
                  <td>
                    <Link to={`/sessions/${s.id}`} className="mono">
                      {s.id.slice(0, 8)}
                    </Link>
                  </td>
                  <td>{s.username}</td>
                  <td><StatusBadge value={s.status} /></td>
                  <td>{s.browser}</td>
                  <td>{formatDateTime(s.started_at)}</td>
                  <td>{formatDuration(s.started_at, s.ended_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
