import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { StatusBadge } from "@shared/components/StatusBadge";
import { ConfirmDialog } from "@shared/components/ConfirmDialog";
import { LoadingBlock, ErrorState } from "@shared/components/States";
import { useToast } from "@shared/components/Toast";
import { LineChart, type LineChartPoint } from "@shared/components/LineChart";
import { formatDateTime } from "@shared/format";
import type { BrowserNodeDto, DashboardRange, NodeHistoryPointDto } from "@shared/api/types";
import { adminApi } from "../api/adminApi";

type Action = "drain" | "undrain" | "maintenance" | "unmaintenance";

const RANGES: { key: DashboardRange; label: string }[] = [
  { key: "1h", label: "1h" },
  { key: "6h", label: "6h" },
  { key: "24h", label: "24h" },
  { key: "7d", label: "7d" },
];

function formatUptime(seconds: number | null): string {
  if (seconds === null) return "—";
  const hours = Math.floor(seconds / 3600);
  const days = Math.floor(hours / 24);
  if (days > 0) return `${days}d ${hours % 24}h`;
  if (hours > 0) return `${hours}h ${Math.floor((seconds % 3600) / 60)}m`;
  return `${Math.floor(seconds / 60)}m`;
}

function formatXForRange(range: DashboardRange) {
  return (iso: string) => {
    const d = new Date(iso);
    if (range === "7d") return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
    return d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
  };
}

/**
 * Roadmap B1.10.3 — Worker Detail view. Drain and Maintenance are kept as
 * two visibly distinct controls (never merged into one toggle) because
 * they're two distinct, centrally-defined states (see ADR 0018): Drain lets
 * existing sessions finish naturally, Maintenance excludes the node from
 * scheduling outright. Neither one here terminates a session as a side
 * effect — session termination is its own explicit, audited action
 * (Roadmap B1.10.4).
 */
export function WorkerDetail() {
  const { id } = useParams<{ id: string }>();
  const { notify } = useToast();
  const [node, setNode] = useState<BrowserNodeDto | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [range, setRange] = useState<DashboardRange>("24h");
  const [history, setHistory] = useState<NodeHistoryPointDto[] | null>(null);
  const [pendingAction, setPendingAction] = useState<Action | null>(null);
  const [busy, setBusy] = useState(false);

  const loadNode = useCallback(() => {
    if (!id) return;
    adminApi.getNode(id).then(setNode).catch(() => setError("Could not load this worker."));
  }, [id]);

  useEffect(loadNode, [loadNode]);

  useEffect(() => {
    if (!id) return;
    setHistory(null);
    adminApi
      .getNodeMetrics(id, range)
      .then(setHistory)
      .catch(() => setHistory([]));
  }, [id, range]);

  async function confirm() {
    if (!pendingAction || !id) return;
    setBusy(true);
    try {
      const call = {
        drain: adminApi.drainNode,
        undrain: adminApi.undrainNode,
        maintenance: adminApi.maintenanceNode,
        unmaintenance: adminApi.unmaintenanceNode,
      }[pendingAction];
      const updated = await call(id);
      setNode(updated);
      notify(`Worker ${pendingAction === "undrain" ? "undrained" : pendingAction === "unmaintenance" ? "taken out of maintenance" : `set to ${pendingAction}`}`);
    } catch {
      notify("Action failed", "error");
    } finally {
      setBusy(false);
      setPendingAction(null);
    }
  }

  if (error) return <div className="page"><ErrorState>{error}</ErrorState></div>;
  if (!node) return <LoadingBlock label="Loading worker…" />;

  const cpuPoints: LineChartPoint[] | null = history
    ? history.map((p) => ({ t: p.t, value: p.cpu_percent ?? 0 }))
    : null;
  const ramPoints: LineChartPoint[] | null = history
    ? history.map((p) => ({ t: p.t, value: p.ram_percent ?? 0 }))
    : null;

  const copy: Record<Action, { title: string; description: string; danger?: boolean }> = {
    drain: {
      title: `Drain ${node.hostname}?`,
      description: "Stops new sessions from being scheduled onto this worker. Sessions already running on it are not affected.",
    },
    undrain: {
      title: `Undrain ${node.hostname}?`,
      description: "Allows new sessions to be scheduled onto this worker again.",
    },
    maintenance: {
      title: `Put ${node.hostname} into maintenance?`,
      description:
        "Fully excludes this worker from scheduling, regardless of capacity — for planned host-level work. Sessions already running on it are not affected.",
      danger: true,
    },
    unmaintenance: {
      title: `Take ${node.hostname} out of maintenance?`,
      description: "Allows this worker to be scheduled again.",
    },
  };

  return (
    <div className="page">
      <p><Link to="/workers">← Workers</Link></p>
      <div className="flex-between">
        <h1 style={{ marginBottom: 0 }}>{node.hostname}</h1>
        <div style={{ display: "flex", gap: "8px" }}>
          {node.status === "MAINTENANCE" ? (
            <button type="button" className="btn btn-secondary" onClick={() => setPendingAction("unmaintenance")}>
              Take out of maintenance
            </button>
          ) : (
            <>
              {node.status === "DRAINING" ? (
                <button type="button" className="btn btn-secondary" onClick={() => setPendingAction("undrain")}>
                  Undrain
                </button>
              ) : (
                <button type="button" className="btn btn-secondary" onClick={() => setPendingAction("drain")}>
                  Drain
                </button>
              )}
              <button type="button" className="btn btn-danger" onClick={() => setPendingAction("maintenance")}>
                Maintenance
              </button>
            </>
          )}
        </div>
      </div>

      <div className="card">
        <dl className="detail-grid">
          <div>
            <dt>Health</dt>
            <dd><StatusBadge value={node.health} /></dd>
          </div>
          <div>
            <dt>Scheduling status</dt>
            <dd><StatusBadge value={node.status} /></dd>
          </div>
          <div>
            <dt>Enrollment</dt>
            <dd><StatusBadge value={node.enrollment_status} /></dd>
          </div>
          {node.endpoint_url && (
            <div>
              <dt>Endpoint</dt>
              <dd className="mono">{node.endpoint_url}</dd>
            </div>
          )}
          <div>
            <dt>CPU</dt>
            <dd>{node.cpu_percent !== null ? `${node.cpu_percent.toFixed(0)}%` : "not yet reported"}</dd>
          </div>
          <div>
            <dt>RAM</dt>
            <dd>
              {node.ram_used_mb !== null && node.ram_total_mb ? `${node.ram_used_mb} / ${node.ram_total_mb} MB` : "not yet reported"}
            </dd>
          </div>
          <div>
            <dt>Sessions</dt>
            <dd>
              {node.active_sessions} / {node.capacity}
            </dd>
          </div>
          {node.capacity_bound && (
            <div>
              <dt>Capacity limited by</dt>
              <dd>
                {node.capacity_bound === "ceiling" ? (
                  "Capacity ceiling (OPENRBI_AGENT_CAPACITY) — real headroom would allow more"
                ) : node.capacity_bound === "ram" ? (
                  `RAM (${node.ram_capacity} slots) — CPU headroom alone would allow ${node.cpu_capacity}`
                ) : (
                  `CPU (${node.cpu_capacity} slots) — RAM headroom alone would allow ${node.ram_capacity}`
                )}
              </dd>
            </div>
          )}
          <div>
            <dt>Uptime</dt>
            <dd>{formatUptime(node.uptime_seconds)}</dd>
          </div>
          <div>
            <dt>Runtime</dt>
            <dd>
              {node.runtime} {node.version}
            </dd>
          </div>
          <div>
            <dt>Last heartbeat</dt>
            <dd>{formatDateTime(node.last_heartbeat)}</dd>
          </div>
        </dl>
      </div>

      <div className="card">
        <div className="flex-between" style={{ marginBottom: "8px" }}>
          <h2 style={{ margin: 0, fontSize: "1.1rem" }}>CPU history</h2>
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
        <LineChart data={cpuPoints} yLabel="CPU percent" formatX={formatXForRange(range)} formatY={(v) => `${Math.round(v)}%`} />
      </div>

      <div className="card">
        <h2 style={{ margin: "0 0 8px 0", fontSize: "1.1rem" }}>RAM history</h2>
        <LineChart data={ramPoints} yLabel="RAM percent" formatX={formatXForRange(range)} formatY={(v) => `${Math.round(v)}%`} />
      </div>

      {pendingAction && (
        <ConfirmDialog
          title={copy[pendingAction].title}
          description={copy[pendingAction].description}
          confirmLabel={pendingAction === "undrain" ? "Undrain" : pendingAction === "unmaintenance" ? "Take out of maintenance" : pendingAction[0].toUpperCase() + pendingAction.slice(1)}
          danger={copy[pendingAction].danger}
          busy={busy}
          onConfirm={() => void confirm()}
          onCancel={() => setPendingAction(null)}
        />
      )}
    </div>
  );
}
