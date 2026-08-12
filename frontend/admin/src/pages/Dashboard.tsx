import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { StatusBadge } from "@shared/components/StatusBadge";
import { StatCard } from "@shared/components/StatCard";
import { PageHeader } from "@shared/components/PageHeader";
import { LoadingBlock, ErrorState, EmptyState } from "@shared/components/States";
import { Icons } from "@shared/components/Icons";
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

const CRITICAL_EVENTS = new Set(["MALWARE_DETECTED", "SESSION_ISOLATED", "LOGIN_LOCKED"]);
const WARNING_EVENTS = new Set(["FILE_REJECTED", "UPLOAD_BLOCKED", "DOWNLOAD_BLOCKED", "USER_LOGIN_FAILED"]);

function eventSeverityClass(eventType: string): string {
  if (CRITICAL_EVENTS.has(eventType)) return "critical";
  if (WARNING_EVENTS.has(eventType)) return "warning";
  return "";
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

  function load() {
    setError(null);
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
  }

  useEffect(load, []);

  if (error) {
    return (
      <div className="page">
        <ErrorState action={<button type="button" className="btn btn-secondary btn-sm" onClick={load}>Try again</button>}>
          {error}
        </ErrorState>
      </div>
    );
  }
  if (!data) return <LoadingBlock label="Loading dashboard…" />;

  const activeSessions = data.sessions.filter((s) => s.status === "ACTIVE" || s.status === "DISCONNECTED");
  const isolatedSessions = data.sessions.filter((s) => s.status === "ISOLATED" || s.status === "ISOLATING");
  const openIncidents = data.incidents.filter((i) => i.status === "NEW" || i.status === "INVESTIGATING");
  const criticalIncidents = openIncidents.filter((i) => i.severity === "CRITICAL" || i.severity === "HIGH");
  const degradedComponents = data.health.components.filter((c) => c.status !== "HEALTHY");

  // Only real conditions, computed from the same data as the KPI row —
  // never an invented alert (section 17/19).
  const attention: { key: string; label: string; meta: string; to: string }[] = [];
  if (criticalIncidents.length > 0) {
    attention.push({
      key: "incidents",
      label: `${criticalIncidents.length} high/critical incident${criticalIncidents.length === 1 ? "" : "s"} open`,
      meta: criticalIncidents[0].title,
      to: "/incidents",
    });
  }
  if (isolatedSessions.length > 0) {
    attention.push({
      key: "isolated",
      label: `${isolatedSessions.length} session${isolatedSessions.length === 1 ? "" : "s"} isolated`,
      meta: isolatedSessions.map((s) => s.username).slice(0, 3).join(", "),
      to: "/sessions",
    });
  }
  if (data.quarantine.length > 0) {
    attention.push({
      key: "quarantine",
      label: `${data.quarantine.length} file${data.quarantine.length === 1 ? "" : "s"} awaiting review`,
      meta: data.quarantine[0].original_name,
      to: "/quarantine",
    });
  }
  if (degradedComponents.length > 0) {
    attention.push({
      key: "health",
      label: `${degradedComponents.length} system component${degradedComponents.length === 1 ? "" : "s"} degraded`,
      meta: degradedComponents.map((c) => c.name).join(", "),
      to: "/system",
    });
  }

  return (
    <div className="page">
      <PageHeader title="Dashboard" subtitle="Operational overview of sessions, incidents, and system health." />

      <div className="stat-grid">
        <StatCard label="Active sessions" value={activeSessions.length} />
        <StatCard label="Isolated sessions" value={isolatedSessions.length} />
        <StatCard label="Open incidents" value={openIncidents.length} />
        <StatCard label="Quarantine" value={data.quarantine.length} />
        <StatCard label="System health" value={<StatusBadge value={data.health.status} />} />
      </div>

      <div className="card">
        <div className="section-header">
          <h2>Needs attention</h2>
        </div>
        {attention.length === 0 ? (
          <EmptyState icon={<Icons.Shield width={20} height={20} />} title="Nothing needs attention">
            No open high-severity incidents, isolated sessions, quarantined files, or degraded components right now.
          </EmptyState>
        ) : (
          <div className="attention-list">
            {attention.map((item) => (
              <Link key={item.key} to={item.to} className="attention-item" style={{ textDecoration: "none", color: "inherit" }}>
                <div>
                  <div className="attention-label">{item.label}</div>
                  <div className="attention-meta">{item.meta}</div>
                </div>
                <Icons.ChevronDown width={16} height={16} style={{ transform: "rotate(-90deg)" }} />
              </Link>
            ))}
          </div>
        )}
      </div>

      <div className="card">
        <div className="section-header">
          <h2>Recent activity</h2>
          <Link to="/audit" className="btn btn-secondary btn-sm">
            View all
          </Link>
        </div>
        {data.recentEvents.length === 0 ? (
          <EmptyState title="No events yet">Security events will appear here as they happen.</EmptyState>
        ) : (
          <div className="activity-feed">
            {data.recentEvents.map((e) => (
              <div className="activity-item" key={e.id}>
                <div className={`activity-dot ${eventSeverityClass(e.event_type)}`} />
                <div style={{ flex: 1 }}>
                  <div className="activity-title">{e.event_type}</div>
                  {(e.user_id || e.session_id) && (
                    <div className="activity-meta">
                      {e.session_id && `Session ${e.session_id.slice(0, 8)}`}
                      {e.user_id && e.session_id && " · "}
                      {e.user_id && `User ${e.user_id.slice(0, 8)}`}
                    </div>
                  )}
                </div>
                <div className="activity-time">{formatDateTime(e.created_at)}</div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
