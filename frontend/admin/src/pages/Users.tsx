import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "@shared/auth/AuthContext";
import { StatusBadge } from "@shared/components/StatusBadge";
import { StatCard } from "@shared/components/StatCard";
import { EmptyState, ErrorState } from "@shared/components/States";
import { ErrorBanner, FormField } from "@shared/components/FormField";
import { PageHeader } from "@shared/components/PageHeader";
import { ConfirmDialog } from "@shared/components/ConfirmDialog";
import { Icons } from "@shared/components/Icons";
import { useToast } from "@shared/components/Toast";
import { ApiError } from "@shared/api/client";
import { formatDateTime } from "@shared/format";
import type { GroupSummaryDto, Role, UserListResponseDto, UserSummaryDto } from "@shared/api/types";
import { adminApi } from "../api/adminApi";

const PAGE_SIZES = [10, 25, 50, 100];

export function Users() {
  const { user: currentUser } = useAuth();
  const { notify } = useToast();
  const [data, setData] = useState<UserListResponseDto | null>(null);
  const [groups, setGroups] = useState<GroupSummaryDto[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [pendingAction, setPendingAction] = useState<UserSummaryDto | null>(null);
  const [busy, setBusy] = useState(false);
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [role, setRole] = useState("");
  const [groupId, setGroupId] = useState("");
  const [status, setStatus] = useState("");
  const [source, setSource] = useState("");
  const [mfa, setMfa] = useState("");
  const [sortBy, setSortBy] = useState("username");
  const [sortDir, setSortDir] = useState("asc");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);

  useEffect(() => { const timer = setTimeout(() => { setSearch(searchInput.trim()); setPage(1); }, 300); return () => clearTimeout(timer); }, [searchInput]);

  function load() {
    setError(null);
    Promise.all([
      adminApi.listUsers({ search: search || undefined, role: role || undefined, group_id: groupId || undefined, status: status || undefined, auth_source: source || undefined, mfa: mfa || undefined, sort_by: sortBy, sort_dir: sortDir, offset: (page - 1) * pageSize, limit: pageSize }),
      adminApi.listGroups(),
    ]).then(([users, availableGroups]) => { setData(users); setGroups(availableGroups); }).catch(() => setError("Could not load users. The backend may be unavailable."));
  }

  useEffect(load, [search, role, groupId, status, source, mfa, sortBy, sortDir, page, pageSize]);

  function clearFilters() { setSearchInput(""); setSearch(""); setRole(""); setGroupId(""); setStatus(""); setSource(""); setMfa(""); setPage(1); }
  function sort(column: string) { if (sortBy === column) setSortDir((value) => value === "asc" ? "desc" : "asc"); else { setSortBy(column); setSortDir("asc"); } setPage(1); }
  async function confirmToggle() {
    if (!pendingAction) return;
    setBusy(true);
    try {
      await (pendingAction.is_active ? adminApi.disableUser(pendingAction.id) : adminApi.enableUser(pendingAction.id));
      notify(`${pendingAction.username} ${pendingAction.is_active ? "disabled" : "enabled"}`); setPendingAction(null); load();
    } catch (err) { notify(err instanceof ApiError ? err.detail : "Could not update this user", "error"); } finally { setBusy(false); }
  }

  if (error && !data) return <div className="page"><ErrorState action={<button className="btn btn-secondary btn-sm" onClick={load}>Try again</button>}>{error}</ErrorState></div>;
  const totalPages = data ? Math.max(1, Math.ceil(data.total / pageSize)) : 1;
  const hasFilters = Boolean(search || role || groupId || status || source || mfa);
  const mfaPercent = data?.stats.total ? Math.round((data.stats.mfa_enabled / data.stats.total) * 100) : 0;

  return <div className="page">
    <PageHeader title="Users" subtitle="Manage user accounts, roles, groups and MFA across the organization." actions={<button className="btn btn-primary" onClick={() => setShowCreate(true)}><Icons.Users /> Create local user</button>} />
    <div className="stat-grid users-kpis">
      <StatCard icon={<Icons.Users />} label="Total users" value={data?.stats.total ?? "—"} />
      <StatCard icon={<Icons.User />} label="Active users" value={data?.stats.active ?? "—"} hint="Active account status" />
      <StatCard icon={<Icons.Shield />} label="MFA enabled" value={data ? `${data.stats.mfa_enabled} (${mfaPercent}%)` : "—"} />
      <StatCard icon={<Icons.Settings />} label="Administrators" value={data?.stats.administrators ?? "—"} />
      <StatCard icon={<Icons.Groups />} label="Groups" value={data?.stats.groups ?? "—"} />
    </div>

    {showCreate && <CreateUserForm groups={groups} onClose={() => setShowCreate(false)} onCreated={() => { setShowCreate(false); notify("Local user created"); load(); }} />}

    <section className="card users-management-card">
      <div className="users-filter-grid">
        <label className="users-search"><Icons.Search /><input value={searchInput} onChange={(event) => setSearchInput(event.target.value)} placeholder="Search by username…" aria-label="Search users" /></label>
        <select value={role} onChange={(e) => { setRole(e.target.value); setPage(1); }} aria-label="Filter by role"><option value="">All roles</option>{data?.roles.map((item) => <option key={item} value={item}>{item}</option>)}</select>
        <select value={groupId} onChange={(e) => { setGroupId(e.target.value); setPage(1); }} aria-label="Filter by group"><option value="">All groups</option>{groups.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select>
        <select value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }} aria-label="Filter by status"><option value="">All statuses</option><option value="ACTIVE">Active</option><option value="DISABLED">Disabled</option></select>
        <select value={source} onChange={(e) => { setSource(e.target.value); setPage(1); }} aria-label="Filter by authentication source"><option value="">All sources</option><option value="LOCAL">Local</option><option value="LDAP">LDAP</option></select>
        <select value={mfa} onChange={(e) => { setMfa(e.target.value); setPage(1); }} aria-label="Filter by MFA"><option value="">All MFA</option><option value="ENABLED">Enabled</option><option value="NOT_ENABLED">Not enabled</option></select>
        {hasFilters && <button className="btn btn-ghost btn-sm" onClick={clearFilters}>Clear all</button>}
      </div>

      {!data ? <div className="dashboard-skeleton"><span /><span /><span /><span /></div> : data.items.length === 0 ? <EmptyState title={hasFilters ? "No matching users" : "No users yet"}>{hasFilters ? <><p>Try changing your search or filters.</p><button className="btn btn-secondary btn-sm" onClick={clearFilters}>Clear filters</button></> : "Create a local user or configure LDAP to get started."}</EmptyState> : <div className="table-wrap"><table className="data-table users-table"><thead><tr><th><button onClick={() => sort("username")}>User {sortBy === "username" ? (sortDir === "asc" ? "↑" : "↓") : ""}</button></th><th className="users-secondary">Source</th><th><button onClick={() => sort("role")}>Role {sortBy === "role" ? (sortDir === "asc" ? "↑" : "↓") : ""}</button></th><th className="users-secondary">Groups</th><th><button onClick={() => sort("status")}>Status {sortBy === "status" ? (sortDir === "asc" ? "↑" : "↓") : ""}</button></th><th>MFA</th><th className="users-secondary">Last login</th><th>Actions</th></tr></thead><tbody>{data.items.map((item) => <tr key={item.id}><td><div className="identity-cell"><span className="identity-avatar">{item.username.slice(0, 2).toUpperCase()}</span><div className="identity-main"><Link className="identity-title" to={`/users/${item.id}`}>{item.username}</Link><span className="identity-meta">{item.auth_source === "LOCAL" ? "Local OpenRBI account" : "Directory-managed account"}</span></div></div></td><td className="users-secondary"><span className="identity-source">{item.auth_source}</span></td><td><span className={`role-pill role-${item.role.toLowerCase()}`}>{item.role}</span></td><td className="users-secondary"><GroupPills groups={item.groups} /></td><td><StatusBadge value={item.is_active ? "ACTIVE" : "DISABLED"} /></td><td><span className="mfa-cell"><Icons.Shield /> {item.mfa_enabled ? "ENABLED" : "NOT ENABLED"}</span></td><td className="users-secondary">{item.last_login_at ? formatDateTime(item.last_login_at) : "Never"}</td><td><div className="row-actions"><Link className="icon-btn" to={`/users/${item.id}`} title="Edit user" aria-label={`Edit ${item.username}`}><Icons.User /></Link><Link className="icon-btn" to={`/users/${item.id}`} title="Security and sessions" aria-label={`Security settings for ${item.username}`}><Icons.Shield /></Link><button className="icon-btn" title={item.is_active ? "Disable user" : "Enable user"} aria-label={`${item.is_active ? "Disable" : "Enable"} ${item.username}`} disabled={item.id === currentUser?.id} onClick={() => setPendingAction(item)}><Icons.Settings /></button></div></td></tr>)}</tbody></table></div>}

      {data && data.total > 0 && <div className="users-pagination"><span>Showing {data.offset + 1} to {Math.min(data.offset + data.items.length, data.total)} of {data.total} users</span><div><button className="btn btn-secondary btn-sm" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</button><span>Page {page} of {totalPages}</span><button className="btn btn-secondary btn-sm" disabled={page >= totalPages} onClick={() => setPage(page + 1)}>Next</button><select value={pageSize} onChange={(e) => { setPageSize(Number(e.target.value)); setPage(1); }} aria-label="Users per page">{PAGE_SIZES.map((size) => <option key={size} value={size}>{size} per page</option>)}</select></div></div>}
    </section>

    <aside className="dashboard-security-note"><Icons.Help /><div><strong>About user management</strong><p>Manage OpenRBI access with roles and groups. MFA helps protect local and LDAP-backed accounts.</p></div><a href="/docs/admin-guide.md">Learn more <Icons.ExternalLink /></a></aside>
    {pendingAction && <ConfirmDialog title={`${pendingAction.is_active ? "Disable" : "Enable"} ${pendingAction.username}?`} description={pendingAction.is_active ? "The user will no longer be able to sign in to OpenRBI. Existing browser sessions are not automatically terminated by this action." : "The user will be allowed to sign in to OpenRBI again."} confirmLabel={pendingAction.is_active ? "Disable user" : "Enable user"} danger={pendingAction.is_active} busy={busy} onConfirm={() => void confirmToggle()} onCancel={() => setPendingAction(null)} />}
  </div>;
}

function GroupPills({ groups }: { groups: string[] }) { if (groups.length === 0) return <span className="text-muted">—</span>; return <div className="group-pills" title={groups.join(", ")}>{groups.slice(0, 2).map((name) => <span key={name}>{name}</span>)}{groups.length > 2 && <span>+{groups.length - 2}</span>}</div>; }

function CreateUserForm({ groups, onClose, onCreated }: { groups: GroupSummaryDto[]; onClose: () => void; onCreated: () => void }) {
  const [username, setUsername] = useState(""); const [password, setPassword] = useState(""); const [role, setRole] = useState<Role>("USER"); const [groupIds, setGroupIds] = useState<string[]>([]); const [error, setError] = useState<string | null>(null); const [busy, setBusy] = useState(false);
  async function submit(event: React.FormEvent) { event.preventDefault(); setError(null); setBusy(true); try { await adminApi.createUser({ username, password, role, group_ids: groupIds }); onCreated(); } catch (err) { setError(err instanceof ApiError ? err.detail : "Could not create user."); } finally { setBusy(false); } }
  return <div className="card create-user-card"><div className="section-header"><div><h2>Create local user</h2><p className="text-muted">Creates an OpenRBI-managed account. LDAP identities are provisioned through the configured directory.</p></div></div>{error && <ErrorBanner>{error}</ErrorBanner>}<form onSubmit={submit}><FormField label="Username"><input value={username} onChange={(e) => setUsername(e.target.value)} required autoFocus /></FormField><FormField label="Initial password" hint="OpenRBI validates the password policy server-side."><input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required /></FormField><FormField label="Role"><select value={role} onChange={(e) => setRole(e.target.value as Role)}><option value="USER">USER</option><option value="SECURITY_REVIEWER">SECURITY_REVIEWER</option><option value="ADMIN">ADMIN</option></select></FormField><FormField label="Groups"><select multiple value={groupIds} onChange={(e) => setGroupIds(Array.from(e.target.selectedOptions, (option) => option.value))}>{groups.map((group) => <option key={group.id} value={group.id}>{group.name}</option>)}</select></FormField><div className="modal-actions"><button type="button" className="btn btn-secondary" onClick={onClose}>Cancel</button><button className="btn btn-primary" disabled={busy}>{busy && <span className="spinner" />} Create local user</button></div></form></div>;
}
