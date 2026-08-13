import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { StatusBadge } from "@shared/components/StatusBadge";
import { ErrorState } from "@shared/components/States";
import { LineChart, type LineChartPoint } from "@shared/components/LineChart";
import { formatDateTime } from "@shared/format";
import type { DashboardRange, DashboardResponseDto, SecurityEventDto } from "@shared/api/types";
import { adminApi } from "../api/adminApi";

const RANGES: { key: DashboardRange; label: string }[] = [
  { key: "1h", label: "1h" },
  { key: "6h", label: "6h" },
  { key: "24h", label: "24h" },
  { key: "7d", label: "7d" },
];

const POLL_INTERVAL_MS = 15_000;

function loadBarClass(percent: number | null): string {
  if (percent === null) return "load-bar-fill";
  if (percent >= 90) return "load-bar-fill critical";
  if (percent >= 75) return "load-bar-fill warn";
  return "load-bar-fill";
}

function formatXForRange(range: DashboardRange) {
  return (iso: string) => {
    const d = new Date(iso);
    if (range === "7d") return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
    return d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
  };
}

/**
 * Roadmap B1.10.2 — real operations dashboard backed by GET /admin/dashboard
 * (backend/app/api/admin_dashboard.py). Every number here is computed
 * server-side from real session/worker/audit data — this component only
 * renders what the endpoint returns, it never fabricates a KPI or a chart
 * point. Uses moderate polling (task's own "robustes Polling ist für MVP
 * vollkommen akzeptabel" guidance) rather than WebSocket/SSE, with a visible
 * "Last updated" clock and a "Telemetry delayed" indicator driven by the
 * response's own `telemetry_stale` field, so stale data is never shown as
 * fresh.
 */
export function Dashboard() {
  const [range, setRange] = useState<DashboardRange>("24h");
  const [data, setData] = useState<DashboardResponseDto | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [recentEvents, setRecentEvents] = useState<SecurityEventDto[] | null>(null);
  const rangeRef = useRef(range);
  rangeRef.current = range;

  const load = useCallback((r: DashboardRange) => {
    adminApi
      .getDashboard(r)
      .then((d) => {
        // Guard against a stale response landing after the user has since
        // switched ranges (poll tick fired mid-flight).
        if (rangeRef.current !== r) return;
        setData(d);
        setError(null);
        setLastUpdated(new Date());
      })
      .catch(() => setError("Could not load the dashboard. The backend may be unavailable."));
  }, []);

  useEffect(() => {
    load(range);
    const id = setInterval(() => load(rangeRef.current), POLL_INTERVAL_MS);
    return () => clearInterval(id);
  }, [range, load]);

  useEffect(() => {
    adminApi
      .listSecurityEvents({ limit: 10 })
      .then(setRecentEvents)
      .catch(() => setRecentEvents([]));
  }, []);

  if (error && !data) {
    return (
      <div className="page">
        <ErrorState>{error}</ErrorState>
      </div>
    );
  }

  const chartPoints: LineChartPoint[] | null = data
    ? data.session_history.map((p) => ({ t: p.t, value: p.count }))
    : null;

  return (
    <div className="page">
      <div className="flex-between" style={{ marginBottom: "16px" }}>
        <h1 style={{ margin: 0 }}>Dashboard</h1>
        <div style={{ display: "flex", gap: "12px", alignItems: "center" }}>
          {data?.telemetry_stale && <span className="badge badge-warning">Telemetry delayed</span>}
          <span className="text-muted" style={{ fontSize: "0.85rem" }}>
            {lastUpdated ? `Last updated ${lastUpdated.toLocaleTimeString()}` : "Loading…"}
          </span>
        </div>
      </div>

      <div className="stat-grid">
        <div className="stat-card">
          <div className="label">Active sessions</div>
          <div className="value">{data ? data.kpis.active_sessions : "—"}</div>
          {data && (
            <div className="text-muted" style={{ fontSize: "0.8rem" }}>
              {data.kpis.active_sessions_delta_last_hour === null
                ? "no hour-old history yet"
                : `${data.kpis.active_sessions_delta_last_hour >= 0 ? "+" : ""}${data.kpis.active_sessions_delta_last_hour} last hour`}
            </div>
          )}
        </div>
        <div className="stat-card">
          <div className="label">Workers healthy</div>
          <div className="value">
            {data ? `${data.kpis.workers_healthy} / ${data.kpis.workers_total}` : "—"}
          </div>
        </div>
        <div className="stat-card">
          <div className="label">System health</div>
          <div className="value" style={{ fontSize: "1.1rem" }}>
            {data ? <StatusBadge value={data.kpis.system_health} /> : "—"}
          </div>
        </div>
        <div className="stat-card">
          <div className="label">Avg CPU</div>
          <div className="value">{data && data.kpis.avg_cpu_percent !== null ? `${data.kpis.avg_cpu_percent.toFixed(0)}%` : "—"}</div>
        </div>
        <div className="stat-card">
          <div className="label">Avg RAM</div>
          <div className="value">{data && data.kpis.avg_ram_percent !== null ? `${data.kpis.avg_ram_percent.toFixed(0)}%` : "—"}</div>
        </div>
      </div>

      <div className="card">
        <div className="flex-between" style={{ marginBottom: "8px" }}>
          <h2 style={{ margin: 0, fontSize: "1.1rem" }}>Session history</h2>
          <div style={{ display: "flex", gap: "4px" }}>
            {RANGES.map((r) => (
              <button
                key={r.key}
                className={`btn btn-sm ${range === r.key ? "btn-primary" : "btn-secondary"}`}
                onClick={() => setRange(r.key)}
              >
                {r.label}
              </button>
            ))}
          </div>
        </div>
        <LineChart
          data={chartPoints}
          error={error}
          yLabel="Active sessions"
          formatX={formatXForRange(range)}
          formatY={(v) => String(Math.round(v))}
        />
      </div>

      <div className="card">
        <h2 style={{ margin: "0 0 8px 0", fontSize: "1.1rem" }}>Worker load</h2>
        {!data ? (
          <p className="text-muted">Loading…</p>
        ) : data.workers.length === 0 ? (
          <p className="text-muted">No workers registered.</p>
        ) : (
          data.workers.map((w) => (
            <div key={w.id} className="load-bar-row">
              <div>
                <div>{w.hostname}</div>
                <StatusBadge value={w.health} />
              </div>
              <div>
                <div className="text-muted" style={{ fontSize: "0.75rem", marginBottom: "2px" }}>
                  CPU {w.cpu_percent !== null ? `${w.cpu_percent.toFixed(0)}%` : "n/a"}
                </div>
                <div className="load-bar-track">
                  <div className={loadBarClass(w.cpu_percent)} style={{ width: `${w.cpu_percent ?? 0}%` }} />
                </div>
                <div className="text-muted" style={{ fontSize: "0.75rem", margin: "6px 0 2px" }}>
                  RAM {w.ram_percent !== null ? `${w.ram_percent.toFixed(0)}%` : "n/a"}
                </div>
                <div className="load-bar-track">
                  <div className={loadBarClass(w.ram_percent)} style={{ width: `${w.ram_percent ?? 0}%` }} />
                </div>
              </div>
              <div className="text-muted" style={{ fontSize: "0.85rem", whiteSpace: "nowrap" }}>
                {w.active_sessions} / {w.capacity} sessions
              </div>
            </div>
          ))
        )}
      </div>

      {data && data.warnings.length > 0 && (
        <div className="card">
          <h2 style={{ margin: "0 0 8px 0", fontSize: "1.1rem" }}>Warnings</h2>
          {data.warnings.map((w, i) => (
            <div key={i} className="dashboard-warning-row">
              <span className="badge badge-warning">{w.kind}</span>
              <span>{w.message}</span>
            </div>
          ))}
        </div>
      )}

      <div className="card">
        <div className="flex-between" style={{ marginBottom: "8px" }}>
          <h2 style={{ margin: 0, fontSize: "1.1rem" }}>Recent security events</h2>
          <Link to="/audit" className="btn btn-secondary btn-sm">
            View all
          </Link>
        </div>
        {recentEvents === null ? (
          <p className="text-muted">Loading…</p>
        ) : recentEvents.length === 0 ? (
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
              {recentEvents.map((e) => (
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
