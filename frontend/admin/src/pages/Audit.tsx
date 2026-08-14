import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { EmptyState, ErrorState } from "@shared/components/States";
import { PageHeader } from "@shared/components/PageHeader";
import { TableToolbar } from "@shared/components/TableToolbar";
import { StatusBadge } from "@shared/components/StatusBadge";
import { Icons } from "@shared/components/Icons";
import { formatDateTime } from "@shared/format";
import { SECURITY_EVENT_TYPES, type SecurityEventDto } from "@shared/api/types";
import { adminApi } from "../api/adminApi";
import { AUDIT_CATEGORIES, AUDIT_OUTCOMES, auditActor, auditTarget, categoryIcon, eventCategory, eventLabel, eventOutcome, searchableEvent } from "../auditFormatting";

const LOAD_LIMIT = 500;
const PAGE_SIZES = [25, 50, 100];
type DateRange = "all" | "24h" | "7d" | "30d";

export function Audit() {
  const [events, setEvents] = useState<SecurityEventDto[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [eventType, setEventType] = useState("");
  const [actor, setActor] = useState("");
  const [category, setCategory] = useState("");
  const [outcome, setOutcome] = useState("");
  const [dateRange, setDateRange] = useState<DateRange>("7d");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);
  const [selected, setSelected] = useState<SecurityEventDto | null>(null);

  function load() {
    setError(null);
    adminApi.listSecurityEvents({ limit: LOAD_LIMIT, offset: 0 }).then(setEvents).catch(() => setError("Could not load the audit log. The backend may be unavailable."));
  }
  useEffect(load, []);

  const filtered = useMemo(() => {
    const query = search.trim().toLowerCase();
    const actorQuery = actor.trim().toLowerCase();
    const after = dateRange === "all" ? 0 : Date.now() - ({ "24h": 1, "7d": 7, "30d": 30 }[dateRange] * 86_400_000);
    return (events ?? []).filter((event) => {
      const eventActor = auditActor(event);
      return (!query || searchableEvent(event).includes(query))
        && (!eventType || event.event_type === eventType)
        && (!actorQuery || `${eventActor.label} ${eventActor.id ?? ""} ${event.user_id ?? ""}`.toLowerCase().includes(actorQuery))
        && (!category || eventCategory(event.event_type) === category)
        && (!outcome || eventOutcome(event.event_type) === outcome)
        && (!after || new Date(event.created_at).getTime() >= after);
    });
  }, [events, search, eventType, actor, category, outcome, dateRange]);

  const pages = Math.max(1, Math.ceil(filtered.length / pageSize));
  const visible = filtered.slice((page - 1) * pageSize, page * pageSize);
  const hasFilters = Boolean(search || eventType || actor || category || outcome || dateRange !== "7d");
  function updateFilter(setter: (value: string) => void, value: string) { setter(value); setPage(1); }
  function clearFilters() { setSearch(""); setEventType(""); setActor(""); setCategory(""); setOutcome(""); setDateRange("7d"); setPage(1); }

  if (error && !events) return <div className="page"><ErrorState action={<button type="button" className="btn btn-secondary btn-sm" onClick={load}>Try again</button>}>{error}</ErrorState></div>;

  return <div className="page audit-page">
    <PageHeader title="Audit Log" subtitle="Security and administration activity across OpenRBI." meta={<span className="audit-immutable-note"><Icons.Shield /> Append-only history</span>} actions={<button type="button" className="btn btn-secondary" onClick={load}><Icons.RefreshCw /> Refresh</button>} />

    {events && <div className="audit-summary" aria-label="Audit summary"><span><strong>{filtered.length}</strong> matching events</span><span><strong>{filtered.filter((event) => eventCategory(event.event_type) === "Security").length}</strong> security events</span><span><strong>{filtered.filter((event) => eventOutcome(event.event_type) !== "Success").length}</strong> attention outcomes</span>{events.length === LOAD_LIMIT && <span className="audit-limit-note">Showing the latest {LOAD_LIMIT} recorded events</span>}</div>}

    <section className="card audit-log-card">
      <TableToolbar search={search} onSearchChange={(value) => updateFilter(setSearch, value)} searchPlaceholder="Search events, users, sessions…" filters={<>
        <select value={eventType} className={eventType ? "filter-active" : ""} onChange={(event) => updateFilter(setEventType, event.target.value)} aria-label="Filter by event type"><option value="">All event types</option>{AUDIT_CATEGORIES.map((group) => <optgroup label={group} key={group}>{SECURITY_EVENT_TYPES.filter((type) => eventCategory(type) === group).map((type) => <option value={type} key={type}>{eventLabel(type)}</option>)}</optgroup>)}</select>
        <input value={actor} className={actor ? "filter-active" : ""} onChange={(event) => updateFilter(setActor, event.target.value)} placeholder="Actor or user ID" aria-label="Filter by actor or user ID" />
        <select value={category} className={category ? "filter-active" : ""} onChange={(event) => updateFilter(setCategory, event.target.value)} aria-label="Filter by category"><option value="">All categories</option>{AUDIT_CATEGORIES.map((value) => <option key={value}>{value}</option>)}</select>
        <select value={outcome} className={outcome ? "filter-active" : ""} onChange={(event) => updateFilter(setOutcome, event.target.value)} aria-label="Filter by outcome"><option value="">All outcomes</option>{AUDIT_OUTCOMES.map((value) => <option key={value}>{value}</option>)}</select>
        <select value={dateRange} className={dateRange !== "7d" ? "filter-active" : ""} onChange={(event) => { setDateRange(event.target.value as DateRange); setPage(1); }} aria-label="Filter by time range"><option value="24h">Last 24 hours</option><option value="7d">Last 7 days</option><option value="30d">Last 30 days</option><option value="all">All loaded events</option></select>
      </>} actions={<button type="button" className="btn btn-secondary btn-sm filter-reset" disabled={!hasFilters} onClick={clearFilters}>Clear filters</button>} />

      {!events ? <AuditSkeleton /> : visible.length === 0 ? <EmptyState icon={<Icons.Audit />} title={hasFilters ? "No events match your filters" : "No audit events found"} action={hasFilters ? <button className="btn btn-secondary btn-sm" onClick={clearFilters}>Clear filters</button> : undefined}>{hasFilters ? "Try changing or clearing your search criteria." : "Security and administration events will appear here."}</EmptyState> : <div className="table-wrap"><table className="data-table audit-table"><thead><tr><th>Time</th><th>Event</th><th>Actor</th><th>Target</th><th className="audit-session-column">Session</th><th>Outcome</th><th><span className="sr-only">Details</span></th></tr></thead><tbody>{visible.map((event) => <AuditRow event={event} onOpen={() => setSelected(event)} key={event.id} />)}</tbody></table></div>}

      {events && filtered.length > 0 && <footer className="table-footer"><span>Showing {(page - 1) * pageSize + 1}–{Math.min(page * pageSize, filtered.length)} of {filtered.length} matching events</span><div className="pagination"><button disabled={page === 1} onClick={() => setPage((value) => value - 1)} aria-label="Previous page">‹</button><span>{page} / {pages}</span><button disabled={page === pages} onClick={() => setPage((value) => value + 1)} aria-label="Next page">›</button><select value={pageSize} onChange={(event) => { setPageSize(Number(event.target.value)); setPage(1); }} aria-label="Events per page">{PAGE_SIZES.map((size) => <option key={size} value={size}>{size} per page</option>)}</select></div></footer>}
    </section>
    <aside className="dashboard-security-note"><Icons.Help /><div><strong>About the audit log</strong><p>Audit events are append-only and cannot be edited or deleted. Technical metadata is available in event details.</p></div><a href="/docs/admin-guide.md">Learn more <Icons.ExternalLink /></a></aside>
    {selected && <AuditEventModal event={selected} onClose={() => setSelected(null)} />}
  </div>;
}

function AuditRow({ event, onOpen }: { event: SecurityEventDto; onOpen: () => void }) {
  const actor = auditActor(event); const target = auditTarget(event); const category = eventCategory(event.event_type); const date = new Date(event.created_at);
  return <tr className="audit-row" tabIndex={0} onClick={onOpen} onKeyDown={(keyEvent) => { if (keyEvent.key === "Enter" || keyEvent.key === " ") { keyEvent.preventDefault(); onOpen(); } }} aria-label={`View details for ${eventLabel(event.event_type)}`}><td><time dateTime={event.created_at}><strong>{new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" }).format(date)}</strong><small>{new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(date)}</small></time></td><td><div className="audit-event-cell"><span className={`audit-event-icon audit-category-${category.toLowerCase().replaceAll(" ", "-")}`}>{categoryIcon(category)}</span><div><strong>{eventLabel(event.event_type)}</strong><small className="mono">{event.event_type}</small></div></div></td><td><strong>{actor.label}</strong>{actor.id && <small className="mono" title={actor.id}>{shortId(actor.id)}</small>}</td><td>{target.href ? <Link to={target.href} onClick={(clickEvent) => clickEvent.stopPropagation()}><strong>{target.label}</strong><small className="mono">{target.id ? shortId(target.id) : ""}</small></Link> : <><strong>{target.label}</strong>{target.id && <small className="mono">{shortId(target.id)}</small>}</>}</td><td className="audit-session-column">{event.session_id ? <Link to={`/sessions/${event.session_id}`} className="mono" onClick={(clickEvent) => clickEvent.stopPropagation()}>{shortId(event.session_id)}</Link> : <span className="text-muted">—</span>}</td><td><StatusBadge value={eventOutcome(event.event_type)} /></td><td><button type="button" className="icon-btn" onClick={(clickEvent) => { clickEvent.stopPropagation(); onOpen(); }} aria-label={`View details for ${eventLabel(event.event_type)}`} title="View details"><Icons.ChevronsRight /></button></td></tr>;
}

function AuditEventModal({ event, onClose }: { event: SecurityEventDto; onClose: () => void }) {
  const [showRaw, setShowRaw] = useState(false); const closeRef = useRef<HTMLButtonElement>(null); const actor = auditActor(event); const target = auditTarget(event); const outcome = eventOutcome(event.event_type);
  useEffect(() => { closeRef.current?.focus(); const close = (keyEvent: KeyboardEvent) => { if (keyEvent.key === "Escape") onClose(); }; window.addEventListener("keydown", close); return () => window.removeEventListener("keydown", close); }, [onClose]);
  return <div className="modal-overlay audit-detail-overlay" onClick={onClose}><section className="modal audit-detail-modal" role="dialog" aria-modal="true" aria-labelledby="audit-detail-title" onClick={(clickEvent) => clickEvent.stopPropagation()}><header className="audit-detail-header"><div className="audit-event-cell"><span className="audit-event-icon">{categoryIcon(eventCategory(event.event_type))}</span><div><span className="audit-detail-eyebrow">Audit event</span><h2 id="audit-detail-title">{eventLabel(event.event_type)}</h2><p>{formatDateTime(event.created_at)}</p></div></div><button ref={closeRef} type="button" className="icon-btn" onClick={onClose} aria-label="Close event details">×</button></header><div className="audit-detail-body"><div className="audit-detail-grid"><Detail label="Outcome"><StatusBadge value={outcome} /></Detail><Detail label="Category">{eventCategory(event.event_type)}</Detail><Detail label="Actor"><strong>{actor.label}</strong>{actor.id && <code>{actor.id}</code>}</Detail><Detail label="Target"><strong>{target.label}</strong>{target.id && <code>{target.id}</code>}</Detail>{event.session_id && <Detail label="Session"><Link to={`/sessions/${event.session_id}`} className="mono">{event.session_id}</Link></Detail>}{event.quarantine_file_id && <Detail label="Quarantine file"><Link to={`/quarantine/${event.quarantine_file_id}`} className="mono">{event.quarantine_file_id}</Link></Detail>}<Detail label="Event type"><code>{event.event_type}</code></Detail><Detail label="Event ID"><code>{event.id}</code></Detail></div>{event.metadata_json && Object.keys(event.metadata_json).length > 0 && <MetadataDetails metadata={event.metadata_json} />}<div className="audit-raw-section"><button type="button" className="btn btn-secondary btn-sm" onClick={() => setShowRaw((value) => !value)}>{showRaw ? <Icons.EyeOff /> : <Icons.Eye />} {showRaw ? "Hide raw event" : "Show raw event"}</button>{showRaw && <><button type="button" className="btn btn-secondary btn-sm" onClick={() => void navigator.clipboard.writeText(JSON.stringify(event, null, 2))}><Icons.Clipboard /> Copy JSON</button><pre><code>{JSON.stringify(event, null, 2)}</code></pre></>}</div></div></section></div>;
}

function MetadataDetails({ metadata }: { metadata: Record<string, unknown> }) { return <section className="audit-metadata"><h3>Event metadata</h3><dl>{Object.entries(metadata).map(([key, value]) => <div key={key}><dt>{eventLabel(key)}</dt><dd>{typeof value === "object" ? <code>{JSON.stringify(value)}</code> : String(value)}</dd></div>)}</dl></section>; }
function Detail({ label, children }: { label: string; children: ReactNode }) { return <div><span>{label}</span>{children}</div>; }
function AuditSkeleton() { return <div className="audit-skeleton" aria-label="Loading audit log"><span /><span /><span /><span /><span /><span /></div>; }
function shortId(value: string) { return value.length > 12 ? `${value.slice(0, 8)}…` : value; }
