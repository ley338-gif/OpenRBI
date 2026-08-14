import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { EmptyState, ErrorState } from "@shared/components/States";
import { ConfirmDialog } from "@shared/components/ConfirmDialog";
import { PageHeader } from "@shared/components/PageHeader";
import { FormField } from "@shared/components/FormField";
import { StatCard } from "@shared/components/StatCard";
import { Icons } from "@shared/components/Icons";
import { useToast } from "@shared/components/Toast";
import { formatDateTime } from "@shared/format";
import type { GroupOverviewDto, GroupOverviewResponseDto, PolicySummaryDto } from "@shared/api/types";
import { adminApi } from "../api/adminApi";

const PAGE_SIZES = [10, 25, 50, 100];

export function Groups() {
  const { notify } = useToast();
  const [data, setData] = useState<GroupOverviewResponseDto | null>(null);
  const [policies, setPolicies] = useState<PolicySummaryDto[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<GroupOverviewDto | null>(null);
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [policyId, setPolicyId] = useState("");
  const [sortBy, setSortBy] = useState("name");
  const [sortDir, setSortDir] = useState("asc");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);

  useEffect(() => { const timer = setTimeout(() => { setSearch(searchInput.trim()); setPage(1); }, 300); return () => clearTimeout(timer); }, [searchInput]);
  function load() {
    setError(null);
    Promise.all([
      adminApi.getGroupsOverview({ search: search || undefined, policy_id: policyId || undefined, sort_by: sortBy, sort_dir: sortDir, offset: (page - 1) * pageSize, limit: pageSize }),
      adminApi.listPolicies(),
    ]).then(([overview, availablePolicies]) => { setData(overview); setPolicies(availablePolicies.items); }).catch(() => setError("Could not load groups."));
  }
  useEffect(load, [search, policyId, sortBy, sortDir, page, pageSize]);

  function sort(column: string) { if (sortBy === column) setSortDir((value) => value === "asc" ? "desc" : "asc"); else { setSortBy(column); setSortDir("asc"); } setPage(1); }
  function clearFilters() { setSearchInput(""); setSearch(""); setPolicyId(""); setPage(1); }
  async function submit(event: React.FormEvent) {
    event.preventDefault(); if (!name.trim()) return; setBusy(true);
    try { const group = await adminApi.createGroup(name.trim(), description.trim() || null); notify(`Group "${group.name}" created`); setName(""); setDescription(""); setShowCreate(false); load(); }
    catch { notify("Could not create group", "error"); } finally { setBusy(false); }
  }
  async function confirmDelete() {
    if (!pendingDelete) return; setBusy(true);
    try { await adminApi.deleteGroup(pendingDelete.id); notify(`Group "${pendingDelete.name}" deleted`); setPendingDelete(null); load(); }
    catch { notify("Could not delete group", "error"); } finally { setBusy(false); }
  }

  if (error && !data) return <div className="page"><ErrorState action={<button className="btn btn-secondary btn-sm" onClick={load}>Try again</button>}>{error}</ErrorState></div>;
  const hasFilters = Boolean(search || policyId);
  const totalPages = data ? Math.max(1, Math.ceil(data.total / pageSize)) : 1;

  return <div className="page">
    <PageHeader title="Groups" subtitle="Group users together to apply the same security policies." actions={<button className="btn btn-primary" onClick={() => setShowCreate(true)}><Icons.Groups /> Create Group</button>} />
    <div className="stat-grid groups-kpis">
      <StatCard icon={<Icons.Groups />} label="Total groups" value={data?.stats.total ?? "—"} />
      <StatCard tone="info" icon={<Icons.Users />} label="Total memberships" value={data?.stats.memberships ?? "—"} hint="Membership links, not unique users" />
      <StatCard tone="success" icon={<Icons.Shield />} label="Groups with policies" value={data?.stats.with_policies ?? "—"} />
    </div>

    {showCreate && <section className="card create-user-card"><div className="section-header"><div><h2>Create group</h2><p className="text-muted">Create a local OpenRBI security group. Policies can be assigned afterwards.</p></div></div><form className="group-create-form" onSubmit={submit}><FormField label="Name"><input value={name} onChange={(e) => setName(e.target.value)} required autoFocus /></FormField><FormField label="Description (optional)"><input value={description} onChange={(e) => setDescription(e.target.value)} /></FormField><div className="modal-actions"><button type="button" className="btn btn-secondary" onClick={() => setShowCreate(false)} disabled={busy}>Cancel</button><button className="btn btn-primary" disabled={busy}>{busy && <span className="spinner" />} Create group</button></div></form></section>}

    <section className="card groups-management-card">
      <div className="groups-filter-bar"><label className="users-search"><Icons.Search /><input value={searchInput} onChange={(e) => setSearchInput(e.target.value)} placeholder="Search by group name or description…" aria-label="Search groups" /></label><select className={policyId ? "filter-active" : ""} value={policyId} onChange={(e) => { setPolicyId(e.target.value); setPage(1); }} aria-label="Filter by policy"><option value="">All policies</option>{policies.map((policy) => <option value={policy.id} key={policy.id}>{policy.name}</option>)}</select><button className="btn btn-secondary btn-sm filter-reset" disabled={!hasFilters} onClick={clearFilters}>Clear filters</button></div>
      {!data ? <div className="dashboard-skeleton"><span /><span /><span /><span /></div> : data.items.length === 0 ? <EmptyState icon={<Icons.Groups />} title={hasFilters ? "No matching groups" : "No groups yet"}>{hasFilters ? <><p>Try changing your search or filters.</p><button className="btn btn-secondary btn-sm" onClick={clearFilters}>Clear filters</button></> : <><p>Create your first group to organize users and assign access policies.</p><button className="btn btn-primary btn-sm" onClick={() => setShowCreate(true)}>Create Group</button></>}</EmptyState> : <div className="table-wrap"><table className="data-table groups-table"><thead><tr><th><button onClick={() => sort("name")}>Group {sortBy === "name" ? (sortDir === "asc" ? "↑" : "↓") : ""}</button></th><th><button onClick={() => sort("members")}>Members {sortBy === "members" ? (sortDir === "asc" ? "↑" : "↓") : ""}</button></th><th>Policies</th><th className="groups-secondary"><button onClick={() => sort("created_at")}>Created {sortBy === "created_at" ? (sortDir === "asc" ? "↑" : "↓") : ""}</button></th><th>Actions</th></tr></thead><tbody>{data.items.map((group) => <tr key={group.id}><td><div className="identity-cell"><span className="identity-avatar"><Icons.Groups /></span><div className="identity-main"><span className="identity-title">{group.name}</span>{group.description && <span className="identity-meta">{group.description}</span>}</div></div></td><td><span className="table-count">{group.member_count}</span> <span className="text-muted">members</span></td><td><PolicyPills policies={group.policies} /></td><td className="groups-secondary">{formatDateTime(group.created_at)}</td><td><div className="row-actions"><Link className="icon-btn" to="/policies" title="Manage policies" aria-label={`Manage policies for ${group.name}`}><Icons.Shield /></Link><button className="icon-btn" onClick={() => setPendingDelete(group)} title="Delete group" aria-label={`Delete ${group.name}`}><Icons.Settings /></button></div></td></tr>)}</tbody></table></div>}
      {data && data.total > 0 && <div className="users-pagination"><span>Showing {data.offset + 1} to {Math.min(data.offset + data.items.length, data.total)} of {data.total} groups</span><div><button className="btn btn-secondary btn-sm" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</button><span>Page {page} of {totalPages}</span><button className="btn btn-secondary btn-sm" disabled={page >= totalPages} onClick={() => setPage(page + 1)}>Next</button><select value={pageSize} onChange={(e) => { setPageSize(Number(e.target.value)); setPage(1); }}>{PAGE_SIZES.map((size) => <option value={size} key={size}>{size} per page</option>)}</select></div></div>}
    </section>
    <aside className="dashboard-security-note"><Icons.Help /><div><strong>About groups</strong><p>Groups connect users to security policies. Deleting a group removes memberships and policy links, never user accounts.</p></div><a href="/docs/admin-guide.md">Learn more <Icons.ExternalLink /></a></aside>
    {pendingDelete && <ConfirmDialog title={`Delete group "${pendingDelete.name}"?`} description={`This group contains ${pendingDelete.member_count} membership link${pendingDelete.member_count === 1 ? "" : "s"} and ${pendingDelete.policies.length} policy assignment${pendingDelete.policies.length === 1 ? "" : "s"}. Deleting it does not delete user accounts, but all membership and policy links are removed.`} confirmLabel="Delete group" danger busy={busy} onConfirm={() => void confirmDelete()} onCancel={() => setPendingDelete(null)} />}
  </div>;
}

function PolicyPills({ policies }: { policies: string[] }) { if (policies.length === 0) return <span className="text-muted">—</span>; return <div className="group-pills" title={policies.join(", ")}>{policies.slice(0, 2).map((name) => <span key={name}>{name}</span>)}{policies.length > 2 && <span>+{policies.length - 2}</span>}</div>; }
