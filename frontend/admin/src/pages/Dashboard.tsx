import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { StatusBadge } from "@shared/components/StatusBadge";
import { StatCard } from "@shared/components/StatCard";
import { PageHeader } from "@shared/components/PageHeader";
import { EmptyState, ErrorState } from "@shared/components/States";
import { Icons } from "@shared/components/Icons";
import { LineChart, type LineChartPoint } from "@shared/components/LineChart";
import { formatDateTime } from "@shared/format";
import type { DashboardRange, DashboardResponseDto, SecurityEventDto } from "@shared/api/types";
import { adminApi } from "../api/adminApi";

const RANGES: { key: DashboardRange; label: string }[] = [
  { key: "1h", label: "1h" }, { key: "6h", label: "6h" }, { key: "24h", label: "24h" }, { key: "7d", label: "7d" },
];
const POLL_INTERVAL_MS = 15_000;
const STATUS_LABELS: Record<string, string> = {
  PENDING_SCAN: "Pending scan", SCANNING: "Scanning", QUARANTINED: "Pending review",
  RELEASED: "Released", REJECTED: "Blocked", DELETED: "Deleted",
};
const EVENT_LABELS: Record<string, string> = {
  USER_CREATED: "User created", USER_DISABLED: "User disabled", USER_ENABLED: "User enabled",
  USER_LOGIN: "User signed in", USER_LOGIN_FAILED: "Login failed", LOGIN_LOCKED: "Account locked",
  SESSION_STARTED: "Session started", SESSION_DISCONNECTED: "Session disconnected",
  SESSION_ISOLATED: "Session isolated", FILE_REJECTED: "File rejected", DOWNLOAD_BLOCKED: "Download blocked",
  UPLOAD_BLOCKED: "Upload blocked", MALWARE_DETECTED: "Malware detected",
};

function formatXForRange(range: DashboardRange) {
  return (iso: string) => range === "7d"
    ? new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" })
    : new Date(iso).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

function loadClass(value: number | null) {
  if (value !== null && value >= 90) return "load-bar-fill critical";
  if (value !== null && value >= 75) return "load-bar-fill warn";
  return "load-bar-fill";
}

export function Dashboard() {
  const [range, setRange] = useState<DashboardRange>("24h");
  const [data, setData] = useState<DashboardResponseDto | null>(null);
  const [events, setEvents] = useState<SecurityEventDto[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const rangeRef = useRef(range);
  rangeRef.current = range;

  const load = useCallback((selectedRange: DashboardRange) => {
    adminApi.getDashboard(selectedRange)
      .then((dashboard) => {
        if (rangeRef.current !== selectedRange) return;
        setData(dashboard); setError(null); setLastUpdated(new Date(dashboard.generated_at));
      })
      .catch(() => setError("Could not load the operations dashboard."));
    adminApi.listSecurityEvents({ limit: 5 }).then(setEvents).catch(() => setEvents([]));
  }, []);

  useEffect(() => {
    load(range);
    const timer = setInterval(() => load(rangeRef.current), POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [range, load]);

  if (error && !data) return <div className="page"><ErrorState action={<button className="btn btn-secondary btn-sm" onClick={() => load(range)}>Try again</button>}>{error}</ErrorState></div>;
  const chartPoints: LineChartPoint[] | null = data?.session_history.map((point) => ({ t: point.t, value: point.count })) ?? null;

  return (
    <div className="page">
      <PageHeader title="Dashboard" subtitle="Overview of your RBI environment, usage, and system health." actions={
        <div className="dashboard-refresh">
          {data?.telemetry_stale && <span className="badge badge-warning">Telemetry delayed</span>}
          <span className="text-muted">{lastUpdated ? `Last updated: ${formatDateTime(lastUpdated.toISOString())}` : "Loading…"}</span>
          <button type="button" className="icon-btn" aria-label="Refresh dashboard" onClick={() => load(range)}><Icons.RefreshCw /></button>
        </div>
      } />

      <div className="stat-grid dashboard-kpis">
        <StatCard icon={<Icons.Sessions />} label="Active sessions" value={data?.kpis.active_sessions ?? "—"} hint={data?.kpis.active_sessions_delta_last_hour == null ? "No hour-old comparison" : `${data.kpis.active_sessions_delta_last_hour >= 0 ? "+" : ""}${data.kpis.active_sessions_delta_last_hour} in the last hour`} />
        <StatCard icon={<Icons.Users />} label="Users" value={data?.kpis.users ?? "—"} hint="Registered accounts" />
        <StatCard tone="info" icon={<Icons.File />} label="Files processed (24h)" value={data?.kpis.files_processed_24h ?? "—"} hint="Real file lifecycle records" />
        <StatCard tone="danger" icon={<Icons.Quarantine />} label="Blocked files (24h)" value={data?.kpis.blocked_files_24h ?? "—"} hint="Rejected by review or policy" />
        <StatCard tone="warning" icon={<Icons.Incident />} label="Incidents (24h)" value={data?.kpis.incidents_24h ?? "—"} hint="Created in the last 24 hours" />
        <StatCard tone="success" icon={<Icons.Shield />} label="System health" value={data ? <StatusBadge value={data.kpis.system_health} /> : "—"} hint={data ? `${data.kpis.workers_healthy} / ${data.kpis.workers_total} workers healthy` : undefined} />
      </div>

      <div className="dashboard-ops-grid dashboard-ops-grid-top">
        <section className="card">
          <div className="section-header"><h2>Session activity</h2><div className="range-buttons">{RANGES.map((item) => <button key={item.key} className={`btn btn-sm ${range === item.key ? "btn-primary" : "btn-secondary"}`} onClick={() => setRange(item.key)}>{item.label}</button>)}</div></div>
          <LineChart data={chartPoints} error={error} yLabel="Active sessions" formatX={formatXForRange(range)} formatY={(value) => String(Math.round(value))} />
        </section>
        <section className="card">
          <div className="section-header"><h2>Files by status (24h)</h2><Link to="/quarantine">Open quarantine</Link></div>
          {!data || data.file_statuses_24h.length === 0 ? <EmptyState title="No files processed">No file lifecycle records were created in the last 24 hours.</EmptyState> : <div className="status-summary">{data.file_statuses_24h.map((item) => <div className="status-summary-row" key={item.status}><StatusBadge value={item.status} /><span>{STATUS_LABELS[item.status] ?? item.status}</span><strong>{item.count}</strong></div>)}</div>}
        </section>
      </div>

      <section className="card">
        <div className="section-header"><div><h2>Worker pool</h2><p className="text-muted">Current telemetry from registered workers.</p></div><Link to="/workers">View all workers</Link></div>
        {!data || data.workers.length === 0 ? <EmptyState title="No workers registered">Worker telemetry will appear when a node connects.</EmptyState> : <div className="table-shell"><table><thead><tr><th>Worker</th><th>Status</th><th>CPU</th><th>Memory</th><th>Sessions</th></tr></thead><tbody>{data.workers.map((worker) => <tr key={worker.id}><td><Link to={`/workers/${worker.id}`}>{worker.hostname}</Link></td><td><StatusBadge value={worker.health} /></td><td>{worker.cpu_percent == null ? "n/a" : `${worker.cpu_percent.toFixed(0)}%`}</td><td>{worker.ram_percent == null ? "n/a" : `${worker.ram_percent.toFixed(0)}%`}</td><td>{worker.active_sessions} / {worker.capacity}</td></tr>)}</tbody></table></div>}
      </section>

      <div className="dashboard-ops-grid dashboard-ops-grid-mid">
        <section className="card"><div className="section-header"><h2>Quarantine</h2><Link to="/quarantine">Review files</Link></div><div className="operations-metrics"><div><Icons.Quarantine /><span>Pending review</span><strong>{data?.quarantine_pending ?? "—"}</strong></div><div><Icons.Incident /><span>Open high-risk detections</span><strong>{data?.quarantine_high_risk ?? "—"}</strong></div></div></section>
        <section className="card"><div className="section-header"><h2>Recent incidents</h2><Link to="/incidents">View all</Link></div>{!data || data.recent_incidents.length === 0 ? <EmptyState title="No incidents">No incident records are available.</EmptyState> : <div className="compact-list">{data.recent_incidents.map((incident) => <Link to={`/incidents/${incident.id}`} key={incident.id}><StatusBadge value={incident.severity} /><span>{incident.title}</span><time>{formatDateTime(incident.created_at)}</time></Link>)}</div>}</section>
      </div>

      <div className="dashboard-ops-grid dashboard-ops-grid-bottom">
        <section className="card"><h2>System resources</h2><div className="resource-grid"><Resource label="CPU usage (avg)" value={data?.kpis.avg_cpu_percent ?? null} /><Resource label="Memory usage (avg)" value={data?.kpis.avg_ram_percent ?? null} /></div></section>
        <section className="card"><div className="section-header"><h2>Needs attention</h2></div>{!data || data.warnings.length === 0 ? <EmptyState icon={<Icons.Shield />} title="Nothing needs attention">No sustained load, worker, or repeated-login warning is active.</EmptyState> : <div className="attention-list">{data.warnings.map((warning, index) => <div className="attention-item" key={`${warning.kind}-${index}`}><div><div className="attention-label">{warning.kind.replaceAll("_", " ")}</div><div className="attention-meta">{warning.message}</div></div></div>)}</div>}</section>
      </div>

      <div className="dashboard-ops-grid dashboard-ops-grid-bottom">
        <section className="card"><div className="section-header"><h2>Recent activity</h2><Link to="/audit">View audit log</Link></div>{events.length === 0 ? <EmptyState title="No recent activity">Security events will appear here.</EmptyState> : <div className="activity-feed">{events.map((event) => <div className="activity-item" key={event.id}><div className="activity-dot" /><div style={{ flex: 1 }}><div className="activity-title">{EVENT_LABELS[event.event_type] ?? event.event_type.replaceAll("_", " ").toLowerCase()}</div><div className="activity-meta">{event.session_id ? `Session ${event.session_id.slice(0, 8)}` : event.user_id ? `User ${event.user_id.slice(0, 8)}` : "System event"}</div></div><time className="activity-time">{formatDateTime(event.created_at)}</time></div>)}</div>}</section>
        <section className="card"><h2>Quick actions</h2><div className="quick-action-grid"><Quick to="/users" icon={<Icons.Users />} label="Manage users" /><Quick to="/policies" icon={<Icons.Shield />} label="Create policy" /><Quick to="/sessions" icon={<Icons.Sessions />} label="Open sessions" /><Quick to="/audit" icon={<Icons.Audit />} label="Audit log" /><Quick to="/system" icon={<Icons.System />} label="System health" /><Quick to="/settings/ldap" icon={<Icons.Settings />} label="Settings" /></div></section>
      </div>
    </div>
  );
}

function Resource({ label, value }: { label: string; value: number | null }) {
  return <div className="resource-card"><span>{label}</span><strong>{value == null ? "n/a" : `${value.toFixed(0)}%`}</strong><div className="load-bar-track"><div className={loadClass(value)} style={{ width: `${value ?? 0}%` }} /></div></div>;
}

function Quick({ to, icon, label }: { to: string; icon: ReactNode; label: string }) {
  return <Link to={to}>{icon}<span>{label}</span></Link>;
}
