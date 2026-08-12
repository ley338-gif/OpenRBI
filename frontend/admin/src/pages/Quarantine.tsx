import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { StatusBadge } from "@shared/components/StatusBadge";
import { LoadingBlock, EmptyState, ErrorState } from "@shared/components/States";
import { PageHeader } from "@shared/components/PageHeader";
import { TableToolbar } from "@shared/components/TableToolbar";
import { Icons } from "@shared/components/Icons";
import { formatBytes, formatDateTime } from "@shared/format";
import type { QuarantineFileDto, QuarantineStatus } from "@shared/api/types";
import { adminApi } from "../api/adminApi";

const STATUSES: QuarantineStatus[] = ["PENDING_SCAN", "SCANNING", "QUARANTINED", "RELEASED", "REJECTED", "DELETED"];

export function Quarantine() {
  const [files, setFiles] = useState<QuarantineFileDto[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<string>("QUARANTINED");

  function load(status: string) {
    setError(null);
    adminApi
      .listQuarantine(status || undefined)
      .then(setFiles)
      .catch(() => setError("Could not load quarantine. The backend may be unavailable."));
  }

  useEffect(() => load(statusFilter), [statusFilter]);

  if (error) {
    return (
      <div className="page">
        <ErrorState action={<button type="button" className="btn btn-secondary btn-sm" onClick={() => load(statusFilter)}>Try again</button>}>
          {error}
        </ErrorState>
      </div>
    );
  }
  if (!files) return <LoadingBlock label="Loading quarantine…" />;

  return (
    <div className="page">
      <PageHeader title="Quarantine" subtitle="Files intercepted by policy or scan result that aren't automatically released." />

      <TableToolbar
        filters={
          <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)} aria-label="Filter by status">
            <option value="">All statuses</option>
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        }
        onRefresh={() => load(statusFilter)}
      />

      {files.length === 0 ? (
        <EmptyState icon={<Icons.Quarantine width={20} height={20} />} title="No files are currently in quarantine">
          Files awaiting review will appear here.
        </EmptyState>
      ) : (
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>File</th>
                <th>Type</th>
                <th>Size</th>
                <th>Scan</th>
                <th>Status</th>
                <th>Received</th>
              </tr>
            </thead>
            <tbody>
              {files.map((f) => (
                <tr key={f.id}>
                  <td>
                    <Link to={`/quarantine/${f.id}`}>{f.original_name}</Link>
                  </td>
                  <td className="mono" style={{ fontSize: "0.82rem" }}>{f.detected_mime ?? "—"}</td>
                  <td>{formatBytes(f.size_bytes)}</td>
                  <td><StatusBadge value={f.scanner_status} /></td>
                  <td><StatusBadge value={f.status} /></td>
                  <td>{formatDateTime(f.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
