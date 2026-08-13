import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { StatusBadge } from "@shared/components/StatusBadge";
import { LoadingBlock, EmptyState, ErrorState } from "@shared/components/States";
import { formatDateTime } from "@shared/format";
import type { BrowserNodeDto, WorkerHealthLabel } from "@shared/api/types";
import { adminApi } from "../api/adminApi";

const HEALTH_VALUES: WorkerHealthLabel[] = ["HEALTHY", "DEGRADED", "DRAINING", "MAINTENANCE", "OFFLINE"];

type SortKey = "hostname" | "cpu_percent" | "ram_percent" | "active_sessions";

function ramPercent(n: BrowserNodeDto): number | null {
  return n.ram_total_mb && n.ram_used_mb !== null ? (n.ram_used_mb / n.ram_total_mb) * 100 : null;
}

/**
 * Roadmap B1.10.3 — Worker Overview. Reads the same `GET /admin/nodes`
 * B1.10.1 already extended with real telemetry/health; this page is the
 * first UI surface to actually list every worker with that data (System.tsx
 * only ever showed a bare drain/undrain table). Filtering/sorting is
 * client-side over the full node list, same documented-gap pattern as
 * Sessions.tsx — there's no pagination need yet at MVP 1's node counts.
 */
export function Workers() {
  const [nodes, setNodes] = useState<BrowserNodeDto[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [healthFilter, setHealthFilter] = useState<string>("");
  const [sortKey, setSortKey] = useState<SortKey>("hostname");

  function load() {
    adminApi.listNodes().then(setNodes).catch(() => setError("Could not load workers. The backend may be unavailable."));
  }
  useEffect(load, []);

  const filtered = useMemo(() => {
    if (!nodes) return [];
    const rows = healthFilter ? nodes.filter((n) => n.health === healthFilter) : nodes.slice();
    rows.sort((a, b) => {
      if (sortKey === "hostname") return a.hostname.localeCompare(b.hostname);
      if (sortKey === "cpu_percent") return (b.cpu_percent ?? -1) - (a.cpu_percent ?? -1);
      if (sortKey === "ram_percent") return (ramPercent(b) ?? -1) - (ramPercent(a) ?? -1);
      return b.active_sessions - a.active_sessions;
    });
    return rows;
  }, [nodes, healthFilter, sortKey]);

  if (error) return <div className="page"><ErrorState>{error}</ErrorState></div>;
  if (!nodes) return <LoadingBlock label="Loading workers…" />;

  return (
    <div className="page">
      <h1>Workers</h1>

      <div className="filter-bar">
        <select value={healthFilter} onChange={(e) => setHealthFilter(e.target.value)}>
          <option value="">All health states</option>
          {HEALTH_VALUES.map((h) => (
            <option key={h} value={h}>
              {h}
            </option>
          ))}
        </select>
        <select value={sortKey} onChange={(e) => setSortKey(e.target.value as SortKey)}>
          <option value="hostname">Sort: hostname</option>
          <option value="cpu_percent">Sort: CPU (highest first)</option>
          <option value="ram_percent">Sort: RAM (highest first)</option>
          <option value="active_sessions">Sort: active sessions (highest first)</option>
        </select>
        <button type="button" className="btn btn-secondary btn-sm" onClick={load}>
          Refresh
        </button>
      </div>

      {filtered.length === 0 ? (
        <EmptyState>No workers match.</EmptyState>
      ) : (
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>Hostname</th>
                <th>Health</th>
                <th>CPU</th>
                <th>RAM</th>
                <th>Sessions</th>
                <th>Runtime</th>
                <th>Last heartbeat</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((n) => {
                const ram = ramPercent(n);
                return (
                  <tr key={n.id}>
                    <td>
                      <Link to={`/workers/${n.id}`}>{n.hostname}</Link>
                    </td>
                    <td>
                      <StatusBadge value={n.health} />
                    </td>
                    <td>{n.cpu_percent !== null ? `${n.cpu_percent.toFixed(0)}%` : "—"}</td>
                    <td>{ram !== null ? `${ram.toFixed(0)}%` : "—"}</td>
                    <td>
                      {n.active_sessions} / {n.capacity}
                    </td>
                    <td>
                      {n.runtime} {n.version}
                    </td>
                    <td>{formatDateTime(n.last_heartbeat)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
