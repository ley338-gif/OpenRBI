import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import type { BrowserNodeDto, WorkerOverviewDto } from "@shared/api/types";
import { EmptyState, ErrorState, LoadingBlock } from "@shared/components/States";
import { Icons } from "@shared/components/Icons";
import { PageHeader } from "@shared/components/PageHeader";
import { StatCard } from "@shared/components/StatCard";
import { StatusBadge } from "@shared/components/StatusBadge";
import { useToast } from "@shared/components/Toast";
import { formatDateTime } from "@shared/format";
import { adminApi } from "../api/adminApi";

// Roadmap B2.1 (docs/adr/0023-node-enrollment-and-trust-model.md) — shown
// exactly once, the same "shown once" rule as MFA recovery codes: the
// token isn't retrievable again once this dialog closes.
function RegisterNodeModal({ onClose }: { onClose: () => void }) {
  const [token, setToken] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { adminApi.createNodeEnrollmentToken().then((r) => setToken(r.enrollment_token)).catch(() => setError("Could not generate an enrollment token.")); }, []);
  return <div className="modal-overlay" onClick={onClose}><div className="modal" onClick={(e) => e.stopPropagation()}>
    <h2>Register a new node</h2>
    {error ? <p className="text-danger">{error}</p> : !token ? <p>Generating…</p> : <>
      <p>Copy this token into the new host's session-agent <code>.env</code> as <code>OPENRBI_AGENT_ENROLLMENT_TOKEN</code>, alongside a freshly generated agent API token (see <code>.env.example</code> for the exact variable name). Start the agent — it registers itself automatically and appears below as Pending until you approve it.</p>
      <p className="mono" style={{ wordBreak: "break-all", padding: "8px", background: "var(--color-bg-subtle)", borderRadius: "4px" }}>{token}</p>
      <p><strong>This token is shown once and expires in an hour.</strong> Generate a new one if you lose it.</p>
    </>}
    <div className="modal-actions"><button className="btn btn-primary" onClick={onClose}>Done</button></div>
  </div></div>;
}

// Roadmap B2.1 — a Pending node needs an endpoint URL to be approved
// (the operator-known, externally-reachable address — never self-reported
// by the agent, see the ADR's rationale).
function ApproveNodeModal({ node, onDone, onClose }: { node: BrowserNodeDto; onDone: (n: BrowserNodeDto) => void; onClose: () => void }) {
  const { notify } = useToast();
  const [endpointUrl, setEndpointUrl] = useState("");
  const [busy, setBusy] = useState(false);
  async function approve() {
    if (!endpointUrl.trim()) return;
    setBusy(true);
    try {
      onDone(await adminApi.approveNode(node.id, endpointUrl.trim()));
      notify(`${node.hostname} approved`);
      onClose();
    } catch {
      notify("Could not approve this node", "error");
    } finally {
      setBusy(false);
    }
  }
  return <div className="modal-overlay" onClick={onClose}><div className="modal" onClick={(e) => e.stopPropagation()}>
    <h2>Approve {node.hostname}?</h2>
    <p>This node will become schedulable once approved. Enter the externally-reachable address the control plane should dial for it.</p>
    <label>Endpoint URL<input autoFocus value={endpointUrl} placeholder="https://node2.example.internal:8100" onChange={(e) => setEndpointUrl(e.target.value)} /></label>
    <div className="modal-actions"><button className="btn btn-secondary" onClick={onClose} disabled={busy}>Cancel</button><button className="btn btn-primary" onClick={() => void approve()} disabled={busy || !endpointUrl.trim()}>{busy ? "Approving…" : "Approve"}</button></div>
  </div></div>;
}

const PAGE_SIZES = [10, 25, 50, 100];
const ramPercent = (node: BrowserNodeDto) => node.ram_total_mb && node.ram_used_mb !== null ? node.ram_used_mb / node.ram_total_mb * 100 : null;
const relativeTime = (value: string | null) => { if (!value) return "Never"; const seconds = Math.max(0, Math.floor((Date.now() - new Date(value).getTime()) / 1000)); if (seconds < 60) return `${seconds}s ago`; if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`; return `${Math.floor(seconds / 3600)}h ago`; };

export function Workers() {
  const { notify } = useToast();
  const [data, setData] = useState<WorkerOverviewDto | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState(""); const [health, setHealth] = useState(""); const [status, setStatus] = useState("");
  const [sortBy, setSortBy] = useState("hostname"); const [sortDir, setSortDir] = useState("asc");
  const [page, setPage] = useState(1); const [pageSize, setPageSize] = useState(10); const [refreshing, setRefreshing] = useState(false);
  const [showRegister, setShowRegister] = useState(false);
  const [approveTarget, setApproveTarget] = useState<BrowserNodeDto | null>(null);
  function load(background = false) { if (background) setRefreshing(true); setError(null); adminApi.getWorkersOverview({ search: search || undefined, health: health || undefined, node_status: status || undefined, sort_by: sortBy, sort_dir: sortDir, offset: (page - 1) * pageSize, limit: pageSize }).then(setData).catch(() => setError("Could not load workers.")).finally(() => setRefreshing(false)); }
  useEffect(() => { load(); const timer = window.setInterval(() => load(true), 30000); return () => window.clearInterval(timer); }, [search, health, status, sortBy, sortDir, page, pageSize]);
  const clear = () => { setSearch(""); setHealth(""); setStatus(""); setPage(1); };
  async function revoke(node: BrowserNodeDto) {
    try {
      await adminApi.revokeNode(node.id);
      notify(`${node.hostname} revoked`);
      load(true);
    } catch {
      notify("Could not revoke this node", "error");
    }
  }
  if (error && !data) return <div className="page"><ErrorState action={<button className="btn btn-secondary" onClick={() => load()}>Try again</button>}>{error}</ErrorState></div>;
  if (!data) return <LoadingBlock label="Loading workers…" />;
  const pages = Math.max(1, Math.ceil(data.total / pageSize)); const hasFilters = !!(search || health || status);
  return <div className="page workers-page">
    <PageHeader title="Workers" subtitle="Monitor and manage workers running isolated Secure Browser sessions." actions={<><button className="btn btn-secondary" onClick={() => setShowRegister(true)}><Icons.Worker /> Register node</button><button className="btn btn-secondary" onClick={() => load(true)} disabled={refreshing}><Icons.RefreshCw /> {refreshing ? "Refreshing…" : "Refresh"}</button></>} />
    {showRegister && <RegisterNodeModal onClose={() => { setShowRegister(false); load(true); }} />}
    {approveTarget && <ApproveNodeModal node={approveTarget} onDone={() => load(true)} onClose={() => setApproveTarget(null)} />}
    <div className="stat-grid worker-kpis">
      <StatCard compact icon={<Icons.Worker />} label="Total workers" value={data.stats.total} hint={`${data.stats.healthy} healthy`} />
      <StatCard compact tone="success" icon={<Icons.Shield />} label="Healthy" value={data.stats.healthy} hint={`${data.stats.total ? Math.round(data.stats.healthy / data.stats.total * 100) : 0}% available`} />
      <StatCard compact tone={data.stats.needs_attention ? "warning" : "success"} icon={<Icons.Quarantine />} label="Needs attention" value={data.stats.needs_attention} hint="Degraded or offline" />
      <StatCard compact tone="info" icon={<Icons.Sessions />} label="Active sessions" value={data.stats.active_sessions} hint={`${data.stats.total_capacity} total capacity`} />
      <StatCard compact icon={<Icons.System />} label="Average CPU" value={data.stats.average_cpu_percent === null ? "—" : `${data.stats.average_cpu_percent.toFixed(0)}%`} hint="Reported workers" />
      <StatCard compact icon={<Icons.System />} label="Average RAM" value={data.stats.average_ram_percent === null ? "—" : `${data.stats.average_ram_percent.toFixed(0)}%`} hint="Reported workers" />
    </div>
    {data.stats.needs_attention > 0 && <div className="inline-alert warning"><Icons.Quarantine /><div><strong>{data.stats.needs_attention} worker{data.stats.needs_attention === 1 ? " needs" : "s need"} attention</strong><p>Review degraded or offline workers before scheduling additional sessions.</p></div></div>}
    <section className="card worker-console"><div className="worker-filters"><label className="search-input"><Icons.Search /><input value={search} placeholder="Search workers by hostname…" aria-label="Search workers" onChange={(e) => { setSearch(e.target.value); setPage(1); }} /></label><select className={health ? "filter-active" : ""} value={health} onChange={(e) => { setHealth(e.target.value); setPage(1); }} aria-label="Filter by worker health"><option value="">All health states</option>{["HEALTHY","DEGRADED","DRAINING","MAINTENANCE","OFFLINE"].map(v => <option key={v}>{v}</option>)}</select><select className={status ? "filter-active" : ""} value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }} aria-label="Filter by scheduling state"><option value="">All scheduling states</option>{["ONLINE","DRAINING","DEGRADED","MAINTENANCE","OFFLINE"].map(v => <option key={v}>{v}</option>)}</select><select value={sortBy} onChange={(e) => setSortBy(e.target.value)} aria-label="Sort workers by"><option value="hostname">Sort: hostname</option><option value="health">Sort: health</option><option value="cpu">Sort: CPU</option><option value="ram">Sort: RAM</option><option value="sessions">Sort: sessions</option><option value="heartbeat">Sort: last heartbeat</option></select><select value={sortDir} onChange={(e) => setSortDir(e.target.value)} aria-label="Worker sort direction"><option value="asc">Ascending</option><option value="desc">Descending</option></select><button className="btn btn-secondary btn-sm filter-reset" disabled={!hasFilters} onClick={clear}>Clear filters</button></div>
      {data.items.length === 0 ? <EmptyState title={hasFilters ? "No matching workers" : "No workers registered"}><p>{hasFilters ? "Try changing your search or filters." : "Workers appear here after automatic registration with the control plane."}</p>{hasFilters && <button className="btn btn-primary btn-sm" onClick={clear}>Clear filters</button>}</EmptyState> : <div className="table-wrap"><table className="data-table worker-table"><thead><tr><th>Hostname</th><th>Health</th><th>CPU</th><th>RAM</th><th>Sessions</th><th className="worker-secondary">Runtime</th><th>Last heartbeat</th><th className="worker-secondary">Status</th><th>Actions</th></tr></thead><tbody>{data.items.map(node => { const ram = ramPercent(node); return <tr key={node.id}><td><div className="identity-cell"><span className={`worker-dot ${node.health.toLowerCase()}`} /><div className="identity-main"><Link className="identity-title" to={`/workers/${node.id}`}>{node.hostname}</Link><span className="identity-meta mono">{node.id.slice(0, 8)}…</span>{node.enrollment_status !== "APPROVED" && <StatusBadge value={node.enrollment_status} />}</div></div></td><td><StatusBadge value={node.health} /></td><td><strong>{node.cpu_percent === null ? "—" : `${node.cpu_percent.toFixed(0)}%`}</strong><span className="metric-bar"><i style={{ width: `${node.cpu_percent ?? 0}%` }} /></span></td><td><strong>{ram === null ? "—" : `${ram.toFixed(0)}%`}</strong><span className="metric-bar"><i style={{ width: `${ram ?? 0}%` }} /></span></td><td><strong>{node.active_sessions} / {node.capacity}</strong><span className="metric-bar"><i style={{ width: `${node.capacity ? node.active_sessions / node.capacity * 100 : 0}%` }} /></span></td><td className="worker-secondary"><strong>{node.runtime}</strong>{node.version && <small>{node.version}</small>}</td><td title={node.last_heartbeat ? formatDateTime(node.last_heartbeat) : undefined}><strong>{formatDateTime(node.last_heartbeat)}</strong><small>{relativeTime(node.last_heartbeat)}</small></td><td className="worker-secondary"><StatusBadge value={node.status} /></td><td>{node.enrollment_status === "PENDING" && <button className="btn btn-primary btn-sm" onClick={() => setApproveTarget(node)}>Approve</button>}{node.enrollment_status === "APPROVED" && <button className="btn btn-danger btn-sm" onClick={() => void revoke(node)}>Revoke</button>}<Link className="btn btn-secondary btn-sm" to={`/workers/${node.id}`}><Icons.Eye /> Details</Link></td></tr>; })}</tbody></table></div>}
      <footer className="table-footer"><span>Showing {data.total ? (page - 1) * pageSize + 1 : 0}–{Math.min(page * pageSize, data.total)} of {data.total} workers</span><div className="pagination"><button disabled={page === 1} onClick={() => setPage(v => v - 1)}>‹</button><span>{page} / {pages}</span><button disabled={page === pages} onClick={() => setPage(v => v + 1)}>›</button><select value={pageSize} onChange={(e) => { setPageSize(Number(e.target.value)); setPage(1); }}>{PAGE_SIZES.map(size => <option key={size}>{size}</option>)}</select></div></footer>
    </section>
    <aside className="dashboard-security-note"><Icons.Help /><div><strong>About workers</strong><p>Health combines heartbeat freshness and telemetry. Draining stops new scheduling while existing sessions continue normally.</p></div><a href="/docs/admin-guide.md">Learn more <Icons.ExternalLink /></a></aside>
  </div>;
}
