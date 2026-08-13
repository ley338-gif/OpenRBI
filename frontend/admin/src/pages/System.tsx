import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { StatusBadge } from "@shared/components/StatusBadge";
import { LoadingBlock, ErrorState } from "@shared/components/States";
import type { SystemHealthDto } from "@shared/api/types";
import { adminApi } from "../api/adminApi";

/**
 * Real GET /admin/health only — no hardcoded green checks (section 37/38).
 * If a component check itself fails, the component list still renders with
 * that one entry UNAVAILABLE; only a full request failure (backend/DB down
 * entirely) falls back to the error state below. The per-worker table that
 * used to live here (bare drain/undrain, no telemetry) moved to its own
 * Workers page (Roadmap B1.10.3) — see the link below — since a worker
 * fleet is a distinct operational concern from component health checks,
 * and now has enough of its own surface (health, load, history, drain,
 * maintenance) to warrant that.
 */
export function System() {
  const [health, setHealth] = useState<SystemHealthDto | null>(null);
  const [error, setError] = useState<string | null>(null);

  function load() {
    adminApi.getHealth().then(setHealth).catch(() => setError("Could not load system status. The backend may be unavailable."));
  }
  useEffect(load, []);

  if (error) return <div className="page"><ErrorState>{error}</ErrorState></div>;
  if (!health) return <LoadingBlock label="Loading system status…" />;

  return (
    <div className="page">
      <h1>System</h1>

      <div className="card">
        <div className="flex-between" style={{ marginBottom: "8px" }}>
          <h2 style={{ margin: 0, fontSize: "1.1rem" }}>Overall status</h2>
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
            {health.components.map((c) => (
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
