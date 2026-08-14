import { useEffect, useState } from "react";
import { EmptyState, ErrorState } from "@shared/components/States";
import { ConfirmDialog } from "@shared/components/ConfirmDialog";
import { PageHeader } from "@shared/components/PageHeader";
import { FormField } from "@shared/components/FormField";
import { StatCard } from "@shared/components/StatCard";
import { Icons } from "@shared/components/Icons";
import { AttachList, type AttachListItem } from "@shared/components/AttachList";
import { useToast } from "@shared/components/Toast";
import { formatDateTime } from "@shared/format";
import type { GroupDetailDto, GroupOverviewDto, GroupOverviewResponseDto, PolicySummaryDto } from "@shared/api/types";
import { adminApi } from "../api/adminApi";

const PAGE_SIZES = [10, 25, 50, 100];

/**
 * Group assignment (members, policies) is deliberately all done from one
 * modal opened by clicking the group, not a separate page — an Active
 * Directory "Properties" dialog, not a drill-down navigation. Policy
 * assignment mirrors this same modal-first approach from the Policies
 * page (see Policies.tsx's own AssignGroupsModal).
 */
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
  const [selectedGroup, setSelectedGroup] = useState<GroupOverviewDto | null>(null);
  const [groupDetail, setGroupDetail] = useState<GroupDetailDto | null>(null);
  const [attachBusy, setAttachBusy] = useState(false);
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

  function openGroup(group: GroupOverviewDto) {
    setSelectedGroup(group);
    setGroupDetail(null);
    adminApi.getGroup(group.id).then(setGroupDetail).catch(() => notify("Could not load group details", "error"));
  }
  function closeGroup() { setSelectedGroup(null); setGroupDetail(null); }
  function refreshGroupDetail(groupId: string) {
    adminApi.getGroup(groupId).then(setGroupDetail).catch(() => notify("Could not refresh group details", "error"));
    load();
  }

  async function searchUsers(query: string): Promise<AttachListItem[]> {
    const result = await adminApi.listUsers({ search: query, limit: 10 });
    return result.items.map((u) => ({ id: u.id, label: u.username, meta: u.role }));
  }
  async function addMember(userId: string) {
    if (!selectedGroup) return;
    setAttachBusy(true);
    try { await adminApi.addGroupMember(selectedGroup.id, userId); notify("Member added"); refreshGroupDetail(selectedGroup.id); }
    catch { notify("Could not add this member", "error"); } finally { setAttachBusy(false); }
  }
  async function removeMember(userId: string) {
    if (!selectedGroup) return;
    setAttachBusy(true);
    try { await adminApi.removeGroupMember(selectedGroup.id, userId); notify("Member removed"); refreshGroupDetail(selectedGroup.id); }
    catch { notify("Could not remove this member", "error"); } finally { setAttachBusy(false); }
  }

  async function searchGroupPolicies(query: string): Promise<AttachListItem[]> {
    const result = await adminApi.listPolicies({ search: query, limit: 10 });
    return result.items.map((p) => ({ id: p.id, label: p.name, meta: p.policy_type }));
  }
  async function addGroupPolicy(policyId: string) {
    if (!selectedGroup) return;
    setAttachBusy(true);
    try { await adminApi.attachToGroup(policyId, selectedGroup.id); notify("Policy attached"); refreshGroupDetail(selectedGroup.id); }
    catch { notify("Could not attach this policy", "error"); } finally { setAttachBusy(false); }
  }
  async function removeGroupPolicy(policyId: string) {
    if (!selectedGroup) return;
    setAttachBusy(true);
    try { await adminApi.detachFromGroup(policyId, selectedGroup.id); notify("Policy detached"); refreshGroupDetail(selectedGroup.id); }
    catch { notify("Could not detach this policy", "error"); } finally { setAttachBusy(false); }
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

    {showCreate && <section className="card create-user-card"><div className="section-header"><div><h2>Create group</h2><p className="text-muted">Create a local OpenRBI security group. Members and policies can be assigned afterwards by clicking the group.</p></div></div><form className="group-create-form" onSubmit={submit}><FormField label="Name"><input value={name} onChange={(e) => setName(e.target.value)} required autoFocus /></FormField><FormField label="Description (optional)"><input value={description} onChange={(e) => setDescription(e.target.value)} /></FormField><div className="modal-actions"><button type="button" className="btn btn-secondary" onClick={() => setShowCreate(false)} disabled={busy}>Cancel</button><button className="btn btn-primary" disabled={busy}>{busy && <span className="spinner" />} Create group</button></div></form></section>}

    <section className="card groups-management-card">
      <div className="management-filters groups-filter-bar"><label className="search-input"><Icons.Search /><input value={searchInput} onChange={(e) => setSearchInput(e.target.value)} placeholder="Search by group name or description…" aria-label="Search groups" /></label><select className={policyId ? "filter-active" : ""} value={policyId} onChange={(e) => { setPolicyId(e.target.value); setPage(1); }} aria-label="Filter by policy"><option value="">All policies</option>{policies.map((policy) => <option value={policy.id} key={policy.id}>{policy.name}</option>)}</select><button className="btn btn-secondary btn-sm filter-reset" disabled={!hasFilters} onClick={clearFilters}>Clear filters</button></div>
      {!data ? <div className="dashboard-skeleton"><span /><span /><span /><span /></div> : data.items.length === 0 ? <EmptyState icon={<Icons.Groups />} title={hasFilters ? "No matching groups" : "No groups yet"}>{hasFilters ? <><p>Try changing your search or filters.</p><button className="btn btn-secondary btn-sm" onClick={clearFilters}>Clear filters</button></> : <><p>Create your first group to organize users and assign access policies.</p><button className="btn btn-primary btn-sm" onClick={() => setShowCreate(true)}>Create Group</button></>}</EmptyState> : <div className="table-wrap"><table className="data-table groups-table"><thead><tr><th><button onClick={() => sort("name")}>Group {sortBy === "name" ? (sortDir === "asc" ? "↑" : "↓") : ""}</button></th><th><button onClick={() => sort("members")}>Members {sortBy === "members" ? (sortDir === "asc" ? "↑" : "↓") : ""}</button></th><th>Policies</th><th className="groups-secondary"><button onClick={() => sort("created_at")}>Created {sortBy === "created_at" ? (sortDir === "asc" ? "↑" : "↓") : ""}</button></th><th>Actions</th></tr></thead><tbody>{data.items.map((group) => <tr key={group.id}><td><div className="identity-cell"><span className="identity-avatar"><Icons.Groups /></span><div className="identity-main"><button type="button" className="identity-title identity-title-button" onClick={() => openGroup(group)}>{group.name}</button>{group.description && <span className="identity-meta">{group.description}</span>}</div></div></td><td><span className="table-count">{group.member_count}</span> <span className="text-muted">members</span></td><td><PolicyPills policies={group.policies} /></td><td className="groups-secondary">{formatDateTime(group.created_at)}</td><td><div className="row-actions"><button type="button" className="icon-btn" onClick={() => openGroup(group)} title="Assign members & policies" aria-label={`Assign members and policies for ${group.name}`}><Icons.Shield /></button><button className="icon-btn danger" onClick={() => setPendingDelete(group)} title="Delete group" aria-label={`Delete ${group.name}`}><Icons.Trash /></button></div></td></tr>)}</tbody></table></div>}
      {data && data.total > 0 && <div className="users-pagination"><span>Showing {data.offset + 1} to {Math.min(data.offset + data.items.length, data.total)} of {data.total} groups</span><div><button className="btn btn-secondary btn-sm" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</button><span>Page {page} of {totalPages}</span><button className="btn btn-secondary btn-sm" disabled={page >= totalPages} onClick={() => setPage(page + 1)}>Next</button><select value={pageSize} onChange={(e) => { setPageSize(Number(e.target.value)); setPage(1); }}>{PAGE_SIZES.map((size) => <option value={size} key={size}>{size} per page</option>)}</select></div></div>}
    </section>
    <aside className="dashboard-security-note"><Icons.Help /><div><strong>About groups</strong><p>Groups connect users to security policies. Click a group to add or remove its members and policies — deleting a group removes those links, never user accounts.</p></div><a href="/docs/admin-guide.md">Learn more <Icons.ExternalLink /></a></aside>

    {selectedGroup && <div className="modal-overlay" onClick={closeGroup}><section className="modal group-details-modal" role="dialog" aria-modal="true" aria-labelledby="group-details-title" onClick={(event) => event.stopPropagation()}>
      <div className="section-header">
        <div><h2 id="group-details-title">{selectedGroup.name}</h2><p className="text-muted">{selectedGroup.description || "No description provided."}</p></div>
        <button type="button" className="icon-btn" onClick={closeGroup} title="Close" aria-label="Close group details">×</button>
      </div>

      {!groupDetail ? <div className="dashboard-skeleton"><span /><span /></div> : <>
        <div className="group-details-grid">
          <div><span>Members</span><strong>{groupDetail.member_count}</strong></div>
          <div><span>Created</span><strong>{formatDateTime(groupDetail.created_at)}</strong></div>
        </div>

        <div className="attach-list-section">
          <h3>Members</h3>
          <AttachList
            entityLabel="user"
            attached={groupDetail.members.map((m) => ({ id: m.id, label: m.username }))}
            onSearch={searchUsers}
            onAdd={addMember}
            onRemove={removeMember}
            busy={attachBusy}
            emptyLabel="No members in this group yet."
          />
        </div>

        <div className="attach-list-section">
          <h3>Policies</h3>
          <AttachList
            entityLabel="policy"
            entityLabelPlural="policies"
            attached={groupDetail.policies.map((p) => ({ id: p.id, label: p.name, meta: p.policy_type }))}
            onSearch={searchGroupPolicies}
            onAdd={addGroupPolicy}
            onRemove={removeGroupPolicy}
            busy={attachBusy}
            emptyLabel="No policies attached to this group yet."
          />
        </div>
      </>}

      <div className="modal-actions">
        <button type="button" className="btn btn-secondary" onClick={closeGroup}>Close</button>
        <button type="button" className="btn btn-danger" onClick={() => { setPendingDelete(selectedGroup); closeGroup(); }}><Icons.Trash /> Delete group</button>
      </div>
    </section></div>}

    {pendingDelete && <ConfirmDialog title={`Delete group "${pendingDelete.name}"?`} description={`This group contains ${pendingDelete.member_count} membership link${pendingDelete.member_count === 1 ? "" : "s"} and ${pendingDelete.policies.length} policy assignment${pendingDelete.policies.length === 1 ? "" : "s"}. Deleting it does not delete user accounts, but all membership and policy links are removed.`} confirmLabel="Delete group" danger busy={busy} onConfirm={() => void confirmDelete()} onCancel={() => setPendingDelete(null)} />}
  </div>;
}

function PolicyPills({ policies }: { policies: string[] }) { if (policies.length === 0) return <span className="text-muted">—</span>; return <div className="group-pills" title={policies.join(", ")}>{policies.slice(0, 2).map((name) => <span key={name}>{name}</span>)}{policies.length > 2 && <span>+{policies.length - 2}</span>}</div>; }
