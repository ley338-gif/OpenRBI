import { useEffect, useState } from "react";
import { StatusBadge } from "@shared/components/StatusBadge";
import { LoadingBlock, ErrorState } from "@shared/components/States";
import { ConfirmDialog } from "@shared/components/ConfirmDialog";
import { useToast } from "@shared/components/Toast";
import { formatDateTime } from "@shared/format";
import type { BrowserNodeDto, SystemHealthDto } from "@shared/api/types";
import { adminApi } from "../api/adminApi";

/**
 * Real GET /admin/health / GET /admin/nodes only — no hardcoded green
 * checks (section 37/38). If a component check itself fails, the
 * component list still renders with that one entry UNAVAILABLE; only a
 * full request failure (backend/DB down entirely) falls back to the error
 * state below.
 */
export function System() {
  const { notify } = useToast();
  const [health, setHealth] = useState<SystemHealthDto | null>(null);
  const [nodes, setNodes] = useState<BrowserNodeDto[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pendingDrain, setPendingDrain] = useState<{ node: BrowserNodeDto; action: "drain" | "undrain" } | null>(null);
  const [busy, setBusy] = useState(false);

  function load() {
    Promise.all([adminApi.getHealth(), adminApi.listNodes()])
      .then(([h, n]) => {
        setHealth(h);
        setNodes(n);
      })
      .catch(() => setError("Could not load system status. The backend may be unavailable."));
  }
  useEffect(load, []);

  async function confirmDrain() {
    if (!pendingDrain) return;
    setBusy(true);
    try {
      const updated =
        pendingDrain.action === "drain" ? await adminApi.drainNode(pendingDrain.node.id) : await adminApi.undrainNode(pendingDrain.node.id);
      setNodes((prev) => prev!.map((n) => (n.id === updated.id ? updated : n)));
      notify(`Node ${pendingDrain.action === "drain" ? "draining" : "undrained"}`);
    } catch {
      notify("Could not update this node", "error");
    } finally {
      setBusy(false);
      setPendingDrain(null);
    }
  }

  if (error) return <div className="page"><ErrorState>{error}</ErrorState></div>;
  if (!health || !nodes) return <LoadingBlock label="Loading system status…" />;

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

      <div className="card">
        <h2 style={{ margin: "0 0 8px", fontSize: "1.1rem" }}>Browser nodes</h2>
        {nodes.length === 0 ? (
          <p className="text-muted">No nodes reporting.</p>
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th>Hostname</th>
                <th>Status</th>
                <th>Capacity</th>
                <th>Active sessions</th>
                <th>Runtime</th>
                <th>Last heartbeat</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {nodes.map((n) => (
                <tr key={n.id}>
                  <td>{n.hostname}</td>
                  <td><StatusBadge value={n.status} /></td>
                  <td>{n.capacity}</td>
                  <td>{n.active_sessions}</td>
                  <td>{n.runtime} {n.version}</td>
                  <td>{formatDateTime(n.last_heartbeat)}</td>
                  <td>
                    {n.status === "DRAINING" ? (
                      <button type="button" className="btn btn-secondary btn-sm" onClick={() => setPendingDrain({ node: n, action: "undrain" })}>
                        Undrain
                      </button>
                    ) : (
                      <button type="button" className="btn btn-secondary btn-sm" onClick={() => setPendingDrain({ node: n, action: "drain" })}>
                        Drain
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {pendingDrain && (
        <ConfirmDialog
          title={`${pendingDrain.action === "drain" ? "Drain" : "Undrain"} ${pendingDrain.node.hostname}?`}
          description={
            pendingDrain.action === "drain"
              ? "Stops new sessions from being scheduled onto this node. Sessions already running on it are not affected."
              : "Allows new sessions to be scheduled onto this node again."
          }
          confirmLabel={pendingDrain.action === "drain" ? "Drain" : "Undrain"}
          busy={busy}
          onConfirm={() => void confirmDrain()}
          onCancel={() => setPendingDrain(null)}
        />
      )}
    </div>
  );
}
