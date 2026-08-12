import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { StatusBadge } from "@shared/components/StatusBadge";
import { LoadingBlock, ErrorState } from "@shared/components/States";
import { formatDateTime } from "@shared/format";
import type { AdminSessionDto, IncidentDto, QuarantineFileDto, SecurityEventDto, SystemHealthDto } from "@shared/api/types";
import { adminApi } from "../api/adminApi";

interface DashboardData {
  sessions: AdminSessionDto[];
  incidents: IncidentDto[];
  quarantine: QuarantineFileDto[];
  health: SystemHealthDto;
  recentEvents: SecurityEventDto[];
}

/**
 * Every number here comes from a real list/health endpoint, aggregated
 * client-side (section 3/21) — there is no dedicated dashboard-stats
 * endpoint in the backend today. That's a real, documented gap (see
 * docs/architecture.md#user-portal--admin-portal), not hidden behind a
 * fake chart: if the operator has thousands of sessions/incidents, this
 * page will get slower before the backend gets a summary endpoint.
 */
export function Dashboard() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([
      adminApi.listSessions(),
      adminApi.listIncidents({ status_filter: undefined }),
      adminApi.listQuarantine("QUARANTINED"),
      adminApi.getHealth(),
      adminApi.listSecurityEvents({ limit: 10 }),
    ])
      .then(([sessions, incidents, quarantine, health, recentEvents]) =>
        setData({ sessions, incidents, quarantine, health, recentEvents }),
      )
      .catch(() => setError("Could not load the dashboard. The backend may be unavailable."));
  }, []);

  if (error) return <div className="page"><ErrorState>{error}</ErrorState></div>;
  if (!data) return <LoadingBlock label="Loading dashboard…" />;

  const activeSessions = data.sessions.filter((s) => s.status === "ACTIVE" || s.status === "DISCONNECTED").length;
  const isolatedSessions = data.sessions.filter((s) => s.status === "ISOLATED" || s.status === "ISOLATING").length;
  const openIncidents = data.incidents.filter((i) => i.status === "NEW" || i.status === "INVESTIGATING").length;

  return (
    <div className="page">
      <h1>Dashboard</h1>

      <div className="stat-grid">
        <div className="stat-card">
          <div className="label">Active sessions</div>
          <div className="value">{activeSessions}</div>
        </div>
        <div className="stat-card">
          <div className="label">Isolated sessions</div>
          <div className="value">{isolatedSessions}</div>
        </div>
        <div className="stat-card">
          <div className="label">Open incidents</div>
          <div className="value">{openIncidents}</div>
        </div>
        <div className="stat-card">
          <div className="label">Quarantine items</div>
          <div className="value">{data.quarantine.length}</div>
        </div>
        <div className="stat-card">
          <div className="label">System health</div>
          <div className="value" style={{ fontSize: "1.1rem" }}>
            <StatusBadge value={data.health.status} />
          </div>
        </div>
      </div>

      <div className="card">
        <div className="flex-between" style={{ marginBottom: "8px" }}>
          <h2 style={{ margin: 0, fontSize: "1.1rem" }}>Recent security events</h2>
          <Link to="/audit">View all</Link>
        </div>
        {data.recentEvents.length === 0 ? (
          <p className="text-muted">No events yet.</p>
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th>Event</th>
                <th>Time</th>
              </tr>
            </thead>
            <tbody>
              {data.recentEvents.map((e) => (
                <tr key={e.id}>
                  <td>{e.event_type}</td>
                  <td>{formatDateTime(e.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
