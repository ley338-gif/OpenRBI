import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { StatusBadge } from "@shared/components/StatusBadge";
import { EmptyState, ErrorState } from "@shared/components/States";
import { PageHeader } from "@shared/components/PageHeader";
import { StatCard } from "@shared/components/StatCard";
import { Icons } from "@shared/components/Icons";
import { formatDateTime, formatDuration } from "@shared/format";
import type { AdminSessionListDto, BrowserNodeDto } from "@shared/api/types";
import { adminApi } from "../api/adminApi";

const PAGE_SIZES = [10, 25, 50, 100];
const LIVE_STATUSES = new Set(["QUEUED", "STARTING", "ACTIVE", "DISCONNECTED", "ISOLATING", "ISOLATED"]);

function secondsDuration(value: number | null) {
  if (value === null) return "—";
  const seconds = Math.round(value); const minutes = Math.floor(seconds / 60); const hours = Math.floor(minutes / 60);
  if (hours) return `${hours}h ${minutes % 60}m`; if (minutes) return `${minutes}m ${seconds % 60}s`; return `${seconds}s`;
}

export function Sessions() {
  const [data, setData] = useState<AdminSessionListDto | null>(null);
  const [workers, setWorkers] = useState<BrowserNodeDto[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [searchInput, setSearchInput] = useState(""); const [search, setSearch] = useState("");
  const [status, setStatus] = useState(""); const [workerId, setWorkerId] = useState(""); const [dateRange, setDateRange] = useState("");
  const [sortBy, setSortBy] = useState("started_at"); const [sortDir, setSortDir] = useState("desc");
  const [page, setPage] = useState(1); const [pageSize, setPageSize] = useState(25); const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const filtersRef = useRef({ search, status, workerId, dateRange, sortBy, sortDir, page, pageSize });
  filtersRef.current = { search, status, workerId, dateRange, sortBy, sortDir, page, pageSize };

  useEffect(() => { const timer = setTimeout(() => { setSearch(searchInput.trim()); setPage(1); }, 300); return () => clearTimeout(timer); }, [searchInput]);
  function sinceIso(range: string) { if (!range) return undefined; const now = new Date(); if (range === "today") now.setHours(0, 0, 0, 0); else now.setTime(now.getTime() - Number(range) * 60 * 60 * 1000); return now.toISOString(); }
  function load() {
    const current = filtersRef.current; setError(null);
    adminApi.listSessions({ search: current.search || undefined, session_status: current.status || undefined, worker_id: current.workerId || undefined, since: sinceIso(current.dateRange), sort_by: current.sortBy, sort_dir: current.sortDir, offset: (current.page - 1) * current.pageSize, limit: current.pageSize }).then((result) => { setData(result); setLastUpdated(new Date()); }).catch(() => setError("Could not load sessions."));
  }
  useEffect(() => { adminApi.listNodes().then(setWorkers).catch(() => setWorkers([])); }, []);
  useEffect(() => { load(); const timer = setInterval(load, 15_000); return () => clearInterval(timer); }, [search, status, workerId, dateRange, sortBy, sortDir, page, pageSize]);
  function clearFilters() { setSearchInput(""); setSearch(""); setStatus(""); setWorkerId(""); setDateRange(""); setPage(1); }
  function sort(column: string) { if (sortBy === column) setSortDir((value) => value === "asc" ? "desc" : "asc"); else { setSortBy(column); setSortDir(column === "started_at" ? "desc" : "asc"); } setPage(1); }

  if (error && !data) return <div className="page"><ErrorState action={<button className="btn btn-secondary btn-sm" onClick={load}>Try again</button>}>{error}</ErrorState></div>;
  const totalPages = data ? Math.max(1, Math.ceil(data.total / pageSize)) : 1; const hasFilters = Boolean(search || status || workerId || dateRange);
  return <div className="page">
    <PageHeader title="Sessions" subtitle="Monitor and manage isolated browser sessions across all users." actions={<div className="dashboard-refresh"><span className="text-muted">{lastUpdated ? `Last updated: ${lastUpdated.toLocaleTimeString()}` : "Loading…"}</span><button className="icon-btn" aria-label="Refresh sessions" onClick={load}><Icons.RefreshCw /></button></div>} />
    <div className="stat-grid sessions-kpis">
      <StatCard icon={<Icons.Sessions />} label="Active sessions" value={data?.stats.active ?? "—"} hint="Includes active, disconnected and isolated sandboxes" />
      <StatCard tone="success" icon={<Icons.Browser />} label="Sessions today" value={data?.stats.sessions_today ?? "—"} />
      <StatCard tone="warning" icon={<Icons.Audit />} label="Average duration" value={data ? secondsDuration(data.stats.average_duration_seconds_24h) : "—"} hint="Sessions ended in the last 24h" />
      <StatCard tone="danger" icon={<Icons.Incident />} label="Failed (24h)" value={data?.stats.failed_24h ?? "—"} />
      <StatCard tone="info" icon={<Icons.Shield />} label="Terminated (24h)" value={data?.stats.terminated_24h ?? "—"} hint="Not classified as failures" />
    </div>
    <section className="card sessions-management-card">
      <div className="sessions-filter-bar"><label className="users-search"><Icons.Search /><input value={searchInput} onChange={(e) => setSearchInput(e.target.value)} placeholder="Search username or session ID…" aria-label="Search sessions" /></label><select className={status ? "filter-active" : ""} value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }} aria-label="Filter by session status"><option value="">All statuses</option>{data?.statuses.map((item) => <option key={item}>{item}</option>)}</select><select className={workerId ? "filter-active" : ""} value={workerId} onChange={(e) => { setWorkerId(e.target.value); setPage(1); }} aria-label="Filter by worker"><option value="">All workers</option>{workers.map((worker) => <option value={worker.id} key={worker.id}>{worker.hostname}</option>)}</select><select className={dateRange ? "filter-active" : ""} value={dateRange} onChange={(e) => { setDateRange(e.target.value); setPage(1); }} aria-label="Filter by start date"><option value="">All dates</option><option value="today">Today</option><option value="24">Last 24 hours</option><option value="168">Last 7 days</option><option value="720">Last 30 days</option></select><button className="btn btn-secondary btn-sm filter-reset" disabled={!hasFilters} onClick={clearFilters}>Clear filters</button></div>
      {!data ? <div className="dashboard-skeleton"><span /><span /><span /><span /></div> : data.items.length === 0 ? <EmptyState icon={<Icons.Sessions />} title={hasFilters ? "No matching sessions" : "No sessions yet"}>{hasFilters ? <><p>Try changing your search or filters.</p><button className="btn btn-secondary btn-sm" onClick={clearFilters}>Clear filters</button></> : "Secure Browser sessions will appear here when users start isolated browser sessions."}</EmptyState> : <div className="table-wrap"><table className="data-table sessions-table"><thead><tr><th>Session</th><th><button onClick={() => sort("username")}>User</button></th><th><button onClick={() => sort("status")}>Status</button></th><th>Worker</th><th className="sessions-secondary">Browser</th><th className="sessions-secondary"><button onClick={() => sort("started_at")}>Started {sortBy === "started_at" ? (sortDir === "asc" ? "↑" : "↓") : ""}</button></th><th><button onClick={() => sort("duration")}>Duration</button></th><th>Actions</th></tr></thead><tbody>{data.items.map((session) => <tr key={session.id}><td><div className="identity-cell"><span className={`identity-avatar session-avatar ${LIVE_STATUSES.has(session.status) ? "live" : ""}`}><Icons.Browser /></span><div className="identity-main"><Link to={`/sessions/${session.id}`} className="identity-title mono">{session.id.slice(0, 8)}</Link><span className="identity-meta">Browser session</span></div></div></td><td><Link className="identity-title" to={`/users/${session.user_id}`}>{session.username}</Link></td><td><StatusBadge value={session.status} /></td><td>{session.node_id ? <Link to={`/workers/${session.node_id}`}>{session.worker_hostname ?? session.node_id.slice(0, 8)}</Link> : <span className="text-muted">Unassigned</span>}</td><td className="sessions-secondary">{session.browser}</td><td className="sessions-secondary">{formatDateTime(session.started_at)}</td><td>{formatDuration(session.started_at, session.ended_at)}</td><td><Link to={`/sessions/${session.id}`} className="btn btn-secondary btn-sm"><Icons.Eye /> View</Link></td></tr>)}</tbody></table></div>}
      {data && data.total > 0 && <div className="users-pagination"><span>Showing {data.offset + 1} to {Math.min(data.offset + data.items.length, data.total)} of {data.total} sessions</span><div><button className="btn btn-secondary btn-sm" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</button><span>Page {page} of {totalPages}</span><button className="btn btn-secondary btn-sm" disabled={page >= totalPages} onClick={() => setPage(page + 1)}>Next</button><select value={pageSize} onChange={(e) => { setPageSize(Number(e.target.value)); setPage(1); }}>{PAGE_SIZES.map((size) => <option value={size} key={size}>{size} per page</option>)}</select></div></div>}
    </section>
    <aside className="dashboard-security-note"><Icons.Help /><div><strong>About sessions</strong><p>DISCONNECTED means the sandbox remains running without an active viewer connection. Termination stops and removes the isolated workspace.</p></div><a href="/docs/admin-guide.md">Learn more <Icons.ExternalLink /></a></aside>
  </div>;
}
