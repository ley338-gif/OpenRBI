import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import type { PolicyListResponseDto, PolicyType } from "@shared/api/types";
import { EmptyState, ErrorState, LoadingBlock } from "@shared/components/States";
import { FormField } from "@shared/components/FormField";
import { Icons } from "@shared/components/Icons";
import { PageHeader } from "@shared/components/PageHeader";
import { StatCard } from "@shared/components/StatCard";
import { useToast } from "@shared/components/Toast";
import { adminApi } from "../api/adminApi";

const POLICY_TYPES: PolicyType[] = ["MIME", "SOURCE", "NETWORK", "DOWNLOADS", "UPLOADS", "CLIPBOARD", "BROWSER", "SESSION"];
const PAGE_SIZES = [10, 25, 50, 100];
const formatDate = (value: string | null) => value ? new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(value)) : "No changes yet";

export function Policies() {
  const { notify } = useToast();
  const [data, setData] = useState<PolicyListResponseDto | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [type, setType] = useState("");
  const [status, setStatus] = useState("");
  const [usage, setUsage] = useState("");
  const [sortBy, setSortBy] = useState("updated_at");
  const [sortDir, setSortDir] = useState("desc");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [showCreate, setShowCreate] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [policyType, setPolicyType] = useState<PolicyType>("MIME");
  const [busy, setBusy] = useState(false);

  function load() {
    setError(null);
    adminApi.listPolicies({ search: search || undefined, policy_type: type || undefined, status_filter: status || undefined, usage: usage || undefined, sort_by: sortBy, sort_dir: sortDir, offset: (page - 1) * pageSize, limit: pageSize }).then(setData).catch(() => setError("Could not load policies."));
  }
  useEffect(load, [search, type, status, usage, sortBy, sortDir, page, pageSize]);

  function clearFilters() { setSearch(""); setType(""); setStatus(""); setUsage(""); setPage(1); }
  function sort(field: string) { if (sortBy === field) setSortDir((current) => current === "asc" ? "desc" : "asc"); else { setSortBy(field); setSortDir("asc"); } setPage(1); }
  async function create(event: React.FormEvent) {
    event.preventDefault(); if (!name.trim()) return; setBusy(true);
    try { const policy = await adminApi.createPolicy(name.trim(), policyType, description.trim()); notify(`Policy "${policy.name}" created`); setName(""); setDescription(""); setShowCreate(false); load(); }
    catch { notify("Could not create policy", "error"); } finally { setBusy(false); }
  }

  if (error) return <div className="page"><ErrorState action={<button className="btn btn-secondary btn-sm" onClick={load}>Try again</button>}>{error}</ErrorState></div>;
  if (!data) return <LoadingBlock label="Loading policies…" />;
  const pages = Math.max(1, Math.ceil(data.total / pageSize));
  const hasFilters = !!(search || type || status || usage);

  return <div className="page policies-page">
    <PageHeader title="Policies" subtitle="Versioned MIME and source rules controlling downloads, uploads, and file handling." actions={<button className="btn btn-primary" onClick={() => setShowCreate(true)}>+ Create Policy</button>} />
    <div className="stat-grid policy-kpis">
      <StatCard compact icon={<Icons.Shield />} label="Total policies" value={data.stats.total} hint={`${data.stats.total_versions} version${data.stats.total_versions === 1 ? "" : "s"}`} />
      <StatCard compact tone="success" icon={<Icons.Clipboard />} label="Published policies" value={data.stats.published} hint="Current live versions" />
      <StatCard compact tone="warning" icon={<Icons.File />} label="Draft policies" value={data.stats.drafts} hint="Unpublished changes" />
      <StatCard compact tone="info" icon={<Icons.Groups />} label="Policies in use" value={data.stats.in_use} hint="Assigned to groups" />
      <StatCard compact icon={<Icons.RefreshCw />} label="Last updated" value={formatDate(data.stats.last_updated_at)} hint={data.stats.last_updated_by ? `By ${data.stats.last_updated_by}` : "Actor unavailable"} />
    </div>

    <section className="card policy-console">
      <div className="policy-filters"><label className="search-input"><Icons.Search /><input value={search} placeholder="Search policy name or description…" aria-label="Search policies" onChange={(e) => { setSearch(e.target.value); setPage(1); }} /></label><select className={type ? "filter-active" : ""} value={type} onChange={(e) => { setType(e.target.value); setPage(1); }} aria-label="Filter by policy type"><option value="">All types</option>{POLICY_TYPES.map((item) => <option key={item}>{item}</option>)}</select><select className={status ? "filter-active" : ""} value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }} aria-label="Filter by publication status"><option value="">All statuses</option><option value="PUBLISHED">Published</option><option value="DRAFT">Draft available</option></select><select className={usage ? "filter-active" : ""} value={usage} onChange={(e) => { setUsage(e.target.value); setPage(1); }} aria-label="Filter by assignment"><option value="">All assignments</option><option value="IN_USE">In use</option><option value="UNASSIGNED">Unassigned</option></select><button className="btn btn-secondary btn-sm filter-reset" disabled={!hasFilters} onClick={clearFilters}>Clear filters</button></div>
      {data.items.length === 0 ? <EmptyState title={hasFilters ? "No matching policies" : "No policies yet"}><p>{hasFilters ? "Try changing your search or filters." : "Create a policy to define file security rules for the isolated browser."}</p><button className="btn btn-primary btn-sm" onClick={hasFilters ? clearFilters : () => setShowCreate(true)}>{hasFilters ? "Clear filters" : "Create Policy"}</button></EmptyState> : <div className="table-wrap"><table className="data-table policy-table"><thead><tr><th><button onClick={() => sort("name")}>Name</button></th><th><button onClick={() => sort("policy_type")}>Type</button></th><th><button onClick={() => sort("status")}>Status</button></th><th>Current version</th><th className="policy-secondary">Assigned to</th><th className="policy-secondary"><button onClick={() => sort("updated_at")}>Updated</button></th><th>Actions</th></tr></thead><tbody>{data.items.map((policy) => <tr key={policy.id}><td><div className="identity-cell"><span className="policy-row-icon"><Icons.Shield /></span><div className="identity-main"><Link className="identity-title" to={`/policies/${policy.id}`}>{policy.name}</Link>{policy.description && <span className="identity-meta">{policy.description}</span>}</div></div></td><td><strong className="policy-type">{policy.policy_type}</strong><small>{policy.policy_type === "MIME" || policy.policy_type === "SOURCE" ? "Enforced file rules" : "Stored label only"}</small></td><td><div className="policy-statuses">{policy.current_version_id ? <span className="status-badge status-active">● PUBLISHED</span> : <span className="status-badge status-neutral">NOT PUBLISHED</span>}{policy.has_draft && <span className="status-badge status-warning">● DRAFT</span>}</div></td><td>{policy.current_version_number ? <><strong>v{policy.current_version_number}</strong>{policy.has_draft && <small>New draft available</small>}</> : <span className="text-muted">No published version</span>}</td><td className="policy-secondary">{policy.assigned_groups.length ? <div className="group-pills">{policy.assigned_groups.slice(0, 2).map((group) => <span key={group}>{group}</span>)}{policy.assigned_groups.length > 2 && <span>+{policy.assigned_groups.length - 2}</span>}</div> : <span className="text-muted">Unassigned</span>}</td><td className="policy-secondary"><strong>{formatDate(policy.updated_at)}</strong>{policy.updated_by && <small>{policy.updated_by}</small>}</td><td><Link className="btn btn-secondary btn-sm" to={`/policies/${policy.id}`}>{policy.has_draft ? "Edit" : "View"}</Link></td></tr>)}</tbody></table></div>}
      <footer className="table-footer"><span>Showing {data.total ? (page - 1) * pageSize + 1 : 0}–{Math.min(page * pageSize, data.total)} of {data.total} policies</span><div className="pagination"><button disabled={page === 1} onClick={() => setPage((value) => value - 1)}>‹</button><span>{page} / {pages}</span><button disabled={page === pages} onClick={() => setPage((value) => value + 1)}>›</button><select value={pageSize} onChange={(e) => { setPageSize(Number(e.target.value)); setPage(1); }}>{PAGE_SIZES.map((size) => <option key={size} value={size}>{size} per page</option>)}</select></div></footer>
    </section>
    <aside className="dashboard-security-note"><Icons.Help /><div><strong>About policies</strong><p>Published MIME and SOURCE rules are evaluated through group assignments. When rules conflict, DENY wins over QUARANTINE, which wins over AUTO_RELEASE.</p></div><a href="/docs/policies.md">Learn more <Icons.ExternalLink /></a></aside>

    {showCreate && <div className="modal-overlay" onClick={() => setShowCreate(false)}><div className="modal create-policy-modal" onClick={(e) => e.stopPropagation()}><h2>Create Policy</h2><p>Create the stable policy record first, then configure and publish its first version.</p><form onSubmit={create}><FormField label="Name"><input autoFocus value={name} onChange={(e) => setName(e.target.value)} required /></FormField><FormField label="Description" hint="Optional context shown in the policy overview."><textarea value={description} onChange={(e) => setDescription(e.target.value)} /></FormField><FormField label="Type" hint={policyType === "MIME" || policyType === "SOURCE" ? "This type supports enforced file rules." : "This type is stored for future enforcement; it has no runtime effect today."}><select value={policyType} onChange={(e) => setPolicyType(e.target.value as PolicyType)}>{POLICY_TYPES.map((item) => <option key={item}>{item}</option>)}</select></FormField><div className="modal-actions"><button type="button" className="btn btn-secondary" onClick={() => setShowCreate(false)}>Cancel</button><button className="btn btn-primary" disabled={busy}>{busy && <span className="spinner" />}Create draft policy</button></div></form></div></div>}
  </div>;
}
