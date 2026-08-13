import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { StatusBadge } from "@shared/components/StatusBadge";
import { LoadingBlock, ErrorState } from "@shared/components/States";
import { PageHeader } from "@shared/components/PageHeader";
import type { SystemHealthDto } from "@shared/api/types";
import { adminApi } from "../api/adminApi";

const STATUS_PRIORITY: Record<string, number> = { UNAVAILABLE: 0, DEGRADED: 1, HEALTHY: 2 };
const POLL_INTERVAL_MS = 15_000;

/**
 * Real GET /admin/health only — no hardcoded green checks (section 37/38).
 * If a component check itself fails, the component list still renders with
 * that one entry UNAVAILABLE; only a full request failure (backend/DB down
 * entirely) falls back to the error state below. The per-worker table that
 * used to live here (bare drain/undrain, no telemetry) moved to its own
 * Workers page (Roadmap B1.10.3) — see the link below — since a worker
 * fleet is a distinct operational concern from component health checks,
 * and now has enough of its own surface (health, load, history, drain,
 * maintenance) to warrant that. Roadmap B1.10.7: added moderate polling +
 * a "Last updated" indicator, matching the Dashboard's own pattern — an
 * admin watching this page during an incident shouldn't need to manually
 * refresh to see a component recover.
 */
export function System() {
  const [health, setHealth] = useState<SystemHealthDto | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  function load() {
    adminApi
      .getHealth()
      .then((h) => {
        setHealth(h);
        setError(null);
        setLastUpdated(new Date());
      })
      .catch(() => setError("Could not load system status. The backend may be unavailable."));
  }

  useEffect(() => {
    load();
    const id = setInterval(load, POLL_INTERVAL_MS);
    return () => clearInterval(id);
  }, []);

  if (error && !health) {
    return (
      <div className="page">
        <ErrorState action={<button type="button" className="btn btn-secondary btn-sm" onClick={load}>Try again</button>}>
          {error}
        </ErrorState>
      </div>
    );
  }
  if (!health) return <LoadingBlock label="Loading system status…" />;

  const sortedComponents = [...health.components].sort(
    (a, b) => (STATUS_PRIORITY[a.status] ?? 9) - (STATUS_PRIORITY[b.status] ?? 9),
  );

  return (
    <div className="page">
      <PageHeader
        title="System"
        subtitle="Live health of every backend dependency."
        actions={
          <span className="text-muted" style={{ fontSize: "0.85rem" }}>
            {lastUpdated ? `Last updated ${lastUpdated.toLocaleTimeString()}` : ""}
          </span>
        }
      />

      <div className="card">
        <div className="section-header">
          <h2>Overall status</h2>
          <StatusBadge value={health.status} />
        </div>
        <table className="data-table">
          <thead>
            <tr>
              <th>Component</th>
              <th>Status</th>
              <th>Detail</th>
            </tr>
          </thead>
          <tbody>
            {sortedComponents.map((c) => (
              <tr key={c.name}>
                <td>{c.name}</td>
                <td><StatusBadge value={c.status} /></td>
                <td className="text-muted">{c.detail ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="text-muted">
        Per-worker health, load, and drain/maintenance controls have moved to <Link to="/workers">Workers</Link>.
      </p>
    </div>
  );
}
