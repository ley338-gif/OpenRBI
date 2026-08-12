import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { StatusBadge } from "@shared/components/StatusBadge";
import { LoadingBlock, EmptyState, ErrorState } from "@shared/components/States";
import { formatBytes, formatDateTime } from "@shared/format";
import type { QuarantineFileDto, QuarantineStatus } from "@shared/api/types";
import { adminApi } from "../api/adminApi";

const STATUSES: QuarantineStatus[] = ["PENDING_SCAN", "SCANNING", "QUARANTINED", "RELEASED", "REJECTED", "DELETED"];

export function Quarantine() {
  const [files, setFiles] = useState<QuarantineFileDto[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<string>("QUARANTINED");

  function load(status: string) {
    adminApi
      .listQuarantine(status || undefined)
      .then(setFiles)
      .catch(() => setError("Could not load quarantine. The backend may be unavailable."));
  }

  useEffect(() => load(statusFilter), [statusFilter]);

  if (error) return <div className="page"><ErrorState>{error}</ErrorState></div>;
  if (!files) return <LoadingBlock label="Loading quarantine…" />;

  return (
    <div className="page">
      <h1>Quarantine</h1>

      <div className="filter-bar">
        <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
          <option value="">All statuses</option>
          {STATUSES.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
      </div>

      {files.length === 0 ? (
        <EmptyState>No files are currently in quarantine.</EmptyState>
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
