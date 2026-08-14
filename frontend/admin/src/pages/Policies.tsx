import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import type { PolicyListResponseDto, PolicySummaryDto, PolicyType } from "@shared/api/types";
import { EmptyState, ErrorState, LoadingBlock } from "@shared/components/States";
import { FormField } from "@shared/components/FormField";
import { Icons } from "@shared/components/Icons";
import { PageHeader } from "@shared/components/PageHeader";
import { StatCard } from "@shared/components/StatCard";
import { AttachList, type AttachListItem } from "@shared/components/AttachList";
import { StatusBadge } from "@shared/components/StatusBadge";
import { useToast } from "@shared/components/Toast";
import { adminApi } from "../api/adminApi";

const POLICY_TYPES: PolicyType[] = ["MIME", "SOURCE", "NETWORK", "DOWNLOADS", "UPLOADS", "CLIPBOARD", "BROWSER", "SESSION"];
const PAGE_SIZES = [10, 25, 50, 100];
// The four real, grounded categories a policy_type actually falls into —
// this replaces treating all eight values as equivalent choices in the
// creation UI (docs/policies.md's "What a Policy's policy_type actually
// does"). FILE_TRANSFER_TYPES controls downloads/uploads via FilePolicyRule
// rows; SESSION_TYPES controls screen resolution; CLIPBOARD_TYPES controls
// the display relay's protocol-level clipboard filtering
// (app/core/rfb_clipboard_filter.py); everything else is stored but has
// zero runtime effect today.
const FILE_TRANSFER_TYPES: PolicyType[] = ["MIME", "SOURCE"];
const SESSION_TYPES: PolicyType[] = ["SESSION"];
const CLIPBOARD_TYPES: PolicyType[] = ["CLIPBOARD"];
const NOT_ENFORCED_TYPES: PolicyType[] = ["NETWORK", "DOWNLOADS", "UPLOADS", "BROWSER"];
type PolicyCategory = "FILE_TRANSFER" | "SESSION" | "CLIPBOARD" | "NOT_ENFORCED";
function categoryOf(type: PolicyType): PolicyCategory {
  if (SESSION_TYPES.includes(type)) return "SESSION";
  if (CLIPBOARD_TYPES.includes(type)) return "CLIPBOARD";
  if (FILE_TRANSFER_TYPES.includes(type)) return "FILE_TRANSFER";
  return "NOT_ENFORCED";
}
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
  const [policyCategory, setPolicyCategory] = useState<PolicyCategory>("FILE_TRANSFER");
  const [policyType, setPolicyType] = useState<PolicyType>("MIME");
  const [busy, setBusy] = useState(false);
  const [assignPolicy, setAssignPolicy] = useState<PolicySummaryDto | null>(null);
  const [assignBusy, setAssignBusy] = useState(false);

  function load() {
    setError(null);
    adminApi.listPolicies({ search: search || undefined, policy_type: type || undefined, status_filter: status || undefined, usage: usage || undefined, sort_by: sortBy, sort_dir: sortDir, offset: (page - 1) * pageSize, limit: pageSize }).then(setData).catch(() => setError("Could not load policies."));
  }
  useEffect(load, [search, type, status, usage, sortBy, sortDir, page, pageSize]);

  function clearFilters() { setSearch(""); setType(""); setStatus(""); setUsage(""); setPage(1); }
  function selectCategory(category: PolicyCategory) {
    setPolicyCategory(category);
    if (category === "SESSION") setPolicyType("SESSION");
    else if (category === "CLIPBOARD") setPolicyType("CLIPBOARD");
    else if (category === "FILE_TRANSFER") setPolicyType(FILE_TRANSFER_TYPES[0]);
    else setPolicyType(NOT_ENFORCED_TYPES[0]);
  }
  function sort(field: string) { if (sortBy === field) setSortDir((current) => current === "asc" ? "desc" : "asc"); else { setSortBy(field); setSortDir("asc"); } setPage(1); }
  async function create(event: React.FormEvent) {
    event.preventDefault(); if (!name.trim()) return; setBusy(true);
    try { const policy = await adminApi.createPolicy(name.trim(), policyType, description.trim()); notify(`Policy "${policy.name}" created`); setName(""); setDescription(""); setShowCreate(false); load(); }
    catch { notify("Could not create policy", "error"); } finally { setBusy(false); }
  }

  function refreshAssignPolicy(policyId: string) {
    adminApi.getPolicy(policyId).then(setAssignPolicy).catch(() => notify("Could not refresh this policy", "error"));
    load();
  }
  async function searchGroupsForPolicy(query: string): Promise<AttachListItem[]> {
    const groups = await adminApi.listGroups();
    const needle = query.toLowerCase();
    return groups
      .filter((g) => g.name.toLowerCase().includes(needle))
      .slice(0, 10)
      .map((g) => ({ id: g.id, label: g.name, meta: `${g.member_count} member${g.member_count === 1 ? "" : "s"}` }));
  }
  async function addPolicyGroup(groupId: string) {
    if (!assignPolicy) return;
    setAssignBusy(true);
    try { await adminApi.attachToGroup(assignPolicy.id, groupId); notify("Group attached"); refreshAssignPolicy(assignPolicy.id); }
    catch { notify("Could not attach this group", "error"); } finally { setAssignBusy(false); }
  }
  async function removePolicyGroup(groupId: string) {
    if (!assignPolicy) return;
    setAssignBusy(true);
    try { await adminApi.detachFromGroup(assignPolicy.id, groupId); notify("Group detached"); refreshAssignPolicy(assignPolicy.id); }
    catch { notify("Could not detach this group", "error"); } finally { setAssignBusy(false); }
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
      {data.items.length === 0 ? <EmptyState title={hasFilters ? "No matching policies" : "No policies yet"}><p>{hasFilters ? "Try changing your search or filters." : "Create a policy to define file security rules for the isolated browser."}</p><button className="btn btn-primary btn-sm" onClick={hasFilters ? clearFilters : () => setShowCreate(true)}>{hasFilters ? "Clear filters" : "Create Policy"}</button></EmptyState> : <div className="table-wrap"><table className="data-table policy-table"><thead><tr><th><button onClick={() => sort("name")}>Name</button></th><th><button onClick={() => sort("policy_type")}>Type</button></th><th><button onClick={() => sort("status")}>Status</button></th><th>Current version</th><th className="policy-secondary">Assigned to</th><th className="policy-secondary"><button onClick={() => sort("updated_at")}>Updated</button></th><th>Actions</th></tr></thead><tbody>{data.items.map((policy) => <tr key={policy.id}><td><div className="identity-cell"><span className="policy-row-icon"><Icons.Shield /></span><div className="identity-main"><Link className="identity-title" to={`/policies/${policy.id}`}>{policy.name}</Link>{policy.description && <span className="identity-meta">{policy.description}</span>}</div></div></td><td><strong className="policy-type">{policy.policy_type}</strong>{categoryOf(policy.policy_type) === "NOT_ENFORCED" ? <StatusBadge value="NOT ENFORCED" /> : <small>{policy.policy_type === "SESSION" ? "Enforced screen resolution" : policy.policy_type === "CLIPBOARD" ? "Enforced clipboard control" : "Enforced file rules"}</small>}</td><td><div className="policy-statuses">{policy.current_version_id ? <span className="status-badge status-active">● PUBLISHED</span> : <span className="status-badge status-neutral">NOT PUBLISHED</span>}{policy.has_draft && <span className="status-badge status-warning">● DRAFT</span>}</div></td><td>{policy.current_version_number ? <><strong>v{policy.current_version_number}</strong>{policy.has_draft && <small>New draft available</small>}</> : <span className="text-muted">No published version</span>}</td><td className="policy-secondary">{policy.assigned_groups.length ? <div className="group-pills">{policy.assigned_groups.slice(0, 2).map((group) => <span key={group.id}>{group.name}</span>)}{policy.assigned_groups.length > 2 && <span>+{policy.assigned_groups.length - 2}</span>}</div> : <span className="text-muted">Unassigned</span>}</td><td className="policy-secondary"><strong>{formatDate(policy.updated_at)}</strong>{policy.updated_by && <small>{policy.updated_by}</small>}</td><td><div className="row-actions"><button type="button" className="icon-btn" onClick={() => setAssignPolicy(policy)} title="Assign to a group" aria-label={`Assign ${policy.name} to a group`}><Icons.Groups /></button><Link className="btn btn-secondary btn-sm" to={`/policies/${policy.id}`}>{policy.has_draft ? "Edit" : "View"}</Link></div></td></tr>)}</tbody></table></div>}
      <footer className="table-footer"><span>Showing {data.total ? (page - 1) * pageSize + 1 : 0}–{Math.min(page * pageSize, data.total)} of {data.total} policies</span><div className="pagination"><button disabled={page === 1} onClick={() => setPage((value) => value - 1)}>‹</button><span>{page} / {pages}</span><button disabled={page === pages} onClick={() => setPage((value) => value + 1)}>›</button><select value={pageSize} onChange={(e) => { setPageSize(Number(e.target.value)); setPage(1); }}>{PAGE_SIZES.map((size) => <option key={size} value={size}>{size} per page</option>)}</select></div></footer>
    </section>
    <aside className="dashboard-security-note"><Icons.Help /><div><strong>About policies</strong><p>Published MIME and SOURCE rules are evaluated through group assignments. When rules conflict, DENY wins over QUARANTINE, which wins over AUTO_RELEASE. A published SESSION policy's screen resolution applies to new sessions from users in its assigned groups — when more than one applies, the smallest resolution wins. A published CLIPBOARD policy's mode applies the same way — when more than one applies, the most restrictive direction(s) win.</p></div><a href="/docs/policies.md">Learn more <Icons.ExternalLink /></a></aside>

    {showCreate && <div className="modal-overlay" onClick={() => setShowCreate(false)}><div className="modal create-policy-modal" onClick={(e) => e.stopPropagation()}><h2>Create Policy</h2><p>Create the stable policy record first, then configure and publish its first version.</p><form onSubmit={create}><FormField label="Name"><input autoFocus value={name} onChange={(e) => setName(e.target.value)} required /></FormField><FormField label="Description" hint="Optional context shown in the policy overview."><textarea value={description} onChange={(e) => setDescription(e.target.value)} /></FormField><FormField label="What does this policy control?">
                <div className="policy-category-picker">
                  {/* aria-label (not implicit label-wrapping) on purpose: this
                      radio picker sits inside FormField's own <label>, and
                      wrapping each option in a second, nested <label> is
                      invalid HTML that browsers fail to associate — screen
                      readers and getByLabel()-style queries would otherwise
                      see these as unnamed "on"/"on"/"on" radios. */}
                  <label className={policyCategory === "FILE_TRANSFER" ? "policy-category-option active" : "policy-category-option"}>
                    <input type="radio" name="policy-category" aria-label="File transfer rules" checked={policyCategory === "FILE_TRANSFER"} onChange={() => selectCategory("FILE_TRANSFER")} />
                    <div><strong>File transfer rules</strong><span>Controls downloads/uploads by MIME type or source host. Enforced today.</span></div>
                  </label>
                  <label className={policyCategory === "SESSION" ? "policy-category-option active" : "policy-category-option"}>
                    <input type="radio" name="policy-category" aria-label="Session resolution" checked={policyCategory === "SESSION"} onChange={() => selectCategory("SESSION")} />
                    <div><strong>Session resolution</strong><span>Sets the screen resolution for new sessions. Enforced today.</span></div>
                  </label>
                  <label className={policyCategory === "CLIPBOARD" ? "policy-category-option active" : "policy-category-option"}>
                    <input type="radio" name="policy-category" aria-label="Clipboard control" checked={policyCategory === "CLIPBOARD"} onChange={() => selectCategory("CLIPBOARD")} />
                    <div><strong>Clipboard control</strong><span>Controls which direction(s) the remote session's clipboard can be used. Enforced today at the display relay's protocol level.</span></div>
                  </label>
                  <label className={policyCategory === "NOT_ENFORCED" ? "policy-category-option active policy-category-planned" : "policy-category-option policy-category-planned"}>
                    <input type="radio" name="policy-category" aria-label="Not yet enforced" checked={policyCategory === "NOT_ENFORCED"} onChange={() => selectCategory("NOT_ENFORCED")} />
                    <div><strong>Not yet enforced <StatusBadge value="NOT ENFORCED" /></strong><span>Network, downloads/uploads, and browser categories are stored but have no runtime effect (docs/policies.md).</span></div>
                  </label>
                </div>
              </FormField>
              {policyCategory === "FILE_TRANSFER" && (
                <FormField label="Rule basis" hint="MIME matches the file's declared/detected content type; SOURCE matches the download/upload's hostname.">
                  <select value={policyType} onChange={(e) => setPolicyType(e.target.value as PolicyType)}>{FILE_TRANSFER_TYPES.map((item) => <option key={item}>{item}</option>)}</select>
                </FormField>
              )}
              {policyCategory === "NOT_ENFORCED" && (
                <FormField label="Category" hint="Creating this only stores a label for future enforcement work — it does not change anything a session can do.">
                  <select value={policyType} onChange={(e) => setPolicyType(e.target.value as PolicyType)}>{NOT_ENFORCED_TYPES.map((item) => <option key={item}>{item}</option>)}</select>
                </FormField>
              )}<div className="modal-actions"><button type="button" className="btn btn-secondary" onClick={() => setShowCreate(false)}>Cancel</button><button className="btn btn-primary" disabled={busy}>{busy && <span className="spinner" />}Create draft policy</button></div></form></div></div>}

    {assignPolicy && <div className="modal-overlay" onClick={() => setAssignPolicy(null)}><section className="modal group-details-modal" role="dialog" aria-modal="true" aria-labelledby="assign-policy-title" onClick={(e) => e.stopPropagation()}>
      <div className="section-header">
        <div><h2 id="assign-policy-title">{assignPolicy.name}</h2><p className="text-muted">Assign this policy to groups.</p></div>
        <button type="button" className="icon-btn" onClick={() => setAssignPolicy(null)} title="Close" aria-label="Close">×</button>
      </div>
      <div className="attach-list-section">
        <AttachList
          entityLabel="group"
          attached={assignPolicy.assigned_groups.map((g) => ({ id: g.id, label: g.name }))}
          onSearch={searchGroupsForPolicy}
          onAdd={addPolicyGroup}
          onRemove={removePolicyGroup}
          busy={assignBusy}
          emptyLabel="No groups attached to this policy yet."
        />
      </div>
      <div className="modal-actions">
        <button type="button" className="btn btn-secondary" onClick={() => setAssignPolicy(null)}>Close</button>
      </div>
    </section></div>}
  </div>;
}
