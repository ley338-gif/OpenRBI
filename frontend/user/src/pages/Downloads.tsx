import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { StatusBadge } from "@shared/components/StatusBadge";
import { LoadingBlock, EmptyState, ErrorState } from "@shared/components/States";
import { PageHeader } from "@shared/components/PageHeader";
import { StatCard } from "@shared/components/StatCard";
import { Icons } from "@shared/components/Icons";
import { useToast } from "@shared/components/Toast";
import { formatBytes, formatDateTime } from "@shared/format";
import type { QuarantineFileDto, UserFilePageDto } from "@shared/api/types";
import { userApi } from "../api/userApi";

const PAGE_SIZE = 25;
type Filter = "all" | "pending" | "approved" | "blocked";

export function Downloads() {
  const [searchParams] = useSearchParams();
  const { notify } = useToast();
  const [data, setData] = useState<UserFilePageDto | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [downloadingId, setDownloadingId] = useState<string | null>(null);
  const [detail, setDetail] = useState<QuarantineFileDto | null>(null);
  const requestedFilter = searchParams.get("status");
  const [filter, setFilter] = useState<Filter>(requestedFilter === "pending" || requestedFilter === "approved" || requestedFilter === "blocked" ? requestedFilter : "all");
  const [search, setSearch] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [page, setPage] = useState(1);

  const params = useMemo(() => {
    const p = new URLSearchParams({ status_filter: filter, offset: String((page - 1) * PAGE_SIZE), limit: String(PAGE_SIZE) });
    if (search.trim()) p.set("search", search.trim());
    if (dateFrom) p.set("date_from", dateFrom);
    if (dateTo) p.set("date_to", dateTo);
    return p;
  }, [filter, search, dateFrom, dateTo, page]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setLoading(true); setError(null);
      userApi.myFilesPage(params).then(setData).catch(() => setError("Could not load your downloads. The backend may be unavailable.")).finally(() => setLoading(false));
    }, search ? 250 : 0);
    return () => window.clearTimeout(timer);
  }, [params]);

  async function handleDownload(file: QuarantineFileDto) {
    setDownloadingId(file.id);
    try {
      const { token } = await userApi.requestDownloadToken(file.id);
      window.location.assign(userApi.downloadUrl(token));
    } catch {
      notify("This file is not available for download", "error");
    } finally { setDownloadingId(null); }
  }

  const totalPages = data ? Math.max(1, Math.ceil(data.total_filtered / PAGE_SIZE)) : 1;
  const hasFilters = filter !== "all" || !!search || !!dateFrom || !!dateTo;

  if (error && !data) return <div className="page"><ErrorState>{error}</ErrorState></div>;

  return (
    <div className="page downloads-page">
      <PageHeader title="Downloads" subtitle="Files downloaded during your Secure Browser sessions and their security review status." />

      {data && <div className="stat-grid download-stats">
        <StatCard icon={<Icons.Download />} label="Total downloads" value={data.summary.total} hint="All recorded files" />
        <StatCard icon={<Icons.Shield />} label="Pending review" value={data.summary.pending} hint="Scanning or awaiting review" />
        <StatCard icon={<Icons.Shield />} label="Approved" value={data.summary.approved} hint="Available to download" />
        <StatCard icon={<Icons.Quarantine />} label="Blocked" value={data.summary.blocked} hint="Rejected by security" />
      </div>}

      <div className="downloads-controls">
        <div className="status-tabs" role="tablist" aria-label="File status">
          {(["all", "pending", "approved", "blocked"] as Filter[]).map((value) => (
            <button key={value} type="button" role="tab" aria-selected={filter === value} className={filter === value ? "active" : ""} onClick={() => { setFilter(value); setPage(1); }}>
              {value === "all" ? "All files" : value === "pending" ? "Pending review" : value[0].toUpperCase() + value.slice(1)}
            </button>
          ))}
        </div>
        <div className="download-filter-fields">
          <label><span>From</span><input className={dateFrom ? "filter-active" : ""} type="date" value={dateFrom} max={dateTo || undefined} onChange={(e) => { setDateFrom(e.target.value); setPage(1); }} /></label>
          <label><span>To</span><input className={dateTo ? "filter-active" : ""} type="date" value={dateTo} min={dateFrom || undefined} onChange={(e) => { setDateTo(e.target.value); setPage(1); }} /></label>
          <input className="table-toolbar-search" type="search" placeholder="Search file name…" aria-label="Search file name" value={search} onChange={(e) => { setSearch(e.target.value); setPage(1); }} />
          <button className="btn btn-secondary btn-sm filter-reset" disabled={!hasFilters} onClick={() => { setFilter("all"); setSearch(""); setDateFrom(""); setDateTo(""); setPage(1); }}>Clear filters</button>
        </div>
      </div>

      {loading && !data ? <LoadingBlock label="Loading downloads…" /> : data?.summary.total === 0 ? (
        <EmptyState icon={<Icons.Download />} title="No downloads yet" action={<Link to="/browser" className="btn btn-primary btn-sm">Open Secure Browser</Link>}>
          Files downloaded during a Secure Browser session will appear here after security processing.
        </EmptyState>
      ) : data?.items.length === 0 ? (
        <EmptyState icon={<Icons.Search />} title="No matching files" action={hasFilters ? <button className="btn btn-secondary btn-sm" onClick={() => { setFilter("all"); setSearch(""); setDateFrom(""); setDateTo(""); setPage(1); }}>Clear filters</button> : undefined}>
          Try changing your filters or search query.
        </EmptyState>
      ) : data && (
        <>
          <div className={`table-wrap downloads-table${loading ? " is-loading" : ""}`}>
            <table className="data-table">
              <thead><tr><th>File name</th><th>Session</th><th>Download date</th><th>File size</th><th>Status</th><th>Action</th></tr></thead>
              <tbody>{data.items.map((f) => (
                <tr key={f.id}>
                  <td><div className="file-cell"><div className="file-type-icon"><Icons.File /></div><div><span className="identity-title">{f.original_name}</span><span className="identity-meta">{fileTypeLabel(f)}</span></div></div></td>
                  <td><span className="table-primary mono">{f.session_id.slice(0, 8)}</span><span className="identity-meta">Secure Browser session</span></td>
                  <td>{formatDateTime(f.created_at)}</td>
                  <td>{formatBytes(f.size_bytes)}</td>
                  <td><StatusBadge value={displayStatus(f.status)} /></td>
                  <td><div className="table-actions"><button type="button" className="btn btn-secondary btn-sm" onClick={() => setDetail(f)}>Details</button>{f.status === "RELEASED" && <button type="button" className="btn btn-primary btn-sm" onClick={() => void handleDownload(f)} disabled={downloadingId === f.id}>{downloadingId === f.id && <span className="spinner" />} Download</button>}</div></td>
                </tr>
              ))}</tbody>
            </table>
          </div>
          <div className="pagination"><span>Showing {data.offset + 1}–{Math.min(data.offset + data.items.length, data.total_filtered)} of {data.total_filtered}</span><div><button className="btn btn-secondary btn-sm" disabled={page === 1} onClick={() => setPage((p) => p - 1)}>Previous</button><span>Page {page} of {totalPages}</span><button className="btn btn-secondary btn-sm" disabled={page >= totalPages} onClick={() => setPage((p) => p + 1)}>Next</button></div></div>
        </>
      )}

      <div className="download-security-note"><Icons.Shield /><p>Files downloaded through Secure Browser are scanned and processed according to your organization’s security policies before they can leave the isolated environment.</p></div>
      {detail && <FileDetails file={detail} onClose={() => setDetail(null)} onDownload={handleDownload} />}
    </div>
  );
}

function displayStatus(status: string): string { return ({ PENDING_SCAN: "PENDING", SCANNING: "SCANNING", QUARANTINED: "PENDING REVIEW", RELEASED: "APPROVED", REJECTED: "BLOCKED", DELETED: "DELETED" } as Record<string, string>)[status] ?? status; }
function fileTypeLabel(file: QuarantineFileDto): string { return file.detected_mime ?? file.declared_mime ?? (file.extension ? `${file.extension.toUpperCase()} file` : "Unknown file type"); }

function FileDetails({ file, onClose, onDownload }: { file: QuarantineFileDto; onClose: () => void; onDownload: (file: QuarantineFileDto) => void }) {
  return <div className="modal-overlay" role="presentation" onClick={onClose}><div className="modal file-details-modal" role="dialog" aria-modal="true" aria-labelledby="file-details-title" onClick={(e) => e.stopPropagation()}>
    <div className="section-header"><h2 id="file-details-title">File details</h2><button className="icon-btn" aria-label="Close details" onClick={onClose}>×</button></div>
    <div className="file-details-name"><div className="file-type-icon"><Icons.File /></div><div><strong>{file.original_name}</strong><span>{fileTypeLabel(file)}</span></div></div>
    <div className="profile-detail-list">
      <DetailRow label="Status" value={<StatusBadge value={displayStatus(file.status)} />} />
      <DetailRow label="Malware scan" value={<StatusBadge value={file.scanner_status} />} />
      <DetailRow label="Policy decision" value={file.policy_action ?? "Not decided"} />
      <DetailRow label="Size" value={formatBytes(file.size_bytes)} />
      <DetailRow label="Session" value={<span className="mono">{file.session_id.slice(0, 8)}</span>} />
      <DetailRow label="Downloaded" value={formatDateTime(file.created_at)} />
      <DetailRow label="Source" value={file.source_host ?? "Not recorded"} />
      <DetailRow label="SHA-256" value={<span className="mono hash-value">{file.sha256}</span>} />
    </div>
    {file.status === "REJECTED" && <div className="form-error-banner">{file.review_comment || file.scanner_result || "This file was blocked by the security workflow."}</div>}
    <div className="modal-actions"><button className="btn btn-secondary" onClick={onClose}>Close</button>{file.status === "RELEASED" && <button className="btn btn-primary" onClick={() => void onDownload(file)}>Download</button>}</div>
  </div></div>;
}
function DetailRow({ label, value }: { label: string; value: React.ReactNode }) { return <div className="profile-detail-row"><span>{label}</span><strong>{value}</strong></div>; }
