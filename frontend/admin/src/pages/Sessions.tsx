import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { StatusBadge } from "@shared/components/StatusBadge";
import { LoadingBlock, EmptyState, ErrorState } from "@shared/components/States";
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

  useEffect(() => {
    adminApi.listSessions().then(setSessions).catch(() => setError("Could not load sessions."));
  }, []);

  const filtered = useMemo(() => {
    if (!sessions) return [];
    return sessions.filter(
      (s) =>
        (!statusFilter || s.status === statusFilter) &&
        (!userFilter || s.username.toLowerCase().includes(userFilter.toLowerCase())),
    );
  }, [sessions, statusFilter, userFilter]);

  if (error) return <div className="page"><ErrorState>{error}</ErrorState></div>;
  if (!sessions) return <LoadingBlock label="Loading sessions…" />;

  return (
    <div className="page">
      <h1>Sessions</h1>

      <div className="filter-bar">
        <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
          <option value="">All statuses</option>
          {STATUSES.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
        <input placeholder="Filter by username" value={userFilter} onChange={(e) => setUserFilter(e.target.value)} />
        <button type="button" className="btn btn-secondary btn-sm" onClick={() => adminApi.listSessions().then(setSessions)}>
          Refresh
        </button>
      </div>

      {filtered.length === 0 ? (
        <EmptyState>No sessions match.</EmptyState>
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
