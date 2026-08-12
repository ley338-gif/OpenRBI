import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { StatusBadge } from "@shared/components/StatusBadge";
import { LoadingBlock, EmptyState, ErrorState } from "@shared/components/States";
import { PageHeader } from "@shared/components/PageHeader";
import { TableToolbar } from "@shared/components/TableToolbar";
import { formatDateTime } from "@shared/format";
import type { IncidentDto, IncidentSeverity, IncidentStatus } from "@shared/api/types";
import { adminApi } from "../api/adminApi";

const STATUSES: IncidentStatus[] = ["NEW", "INVESTIGATING", "RESOLVED", "FALSE_POSITIVE"];
const SEVERITIES: IncidentSeverity[] = ["INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"];

export function Incidents() {
  const [incidents, setIncidents] = useState<IncidentDto[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState("");
  const [severityFilter, setSeverityFilter] = useState("");

  function load() {
    setError(null);
    adminApi
      .listIncidents({ status_filter: statusFilter || undefined, severity_filter: severityFilter || undefined })
      .then(setIncidents)
      .catch(() => setError("Could not load incidents."));
  }

  useEffect(load, [statusFilter, severityFilter]);

  if (error) {
    return (
      <div className="page">
        <ErrorState action={<button type="button" className="btn btn-secondary btn-sm" onClick={load}>Try again</button>}>
          {error}
        </ErrorState>
      </div>
    );
  }
  if (!incidents) return <LoadingBlock label="Loading incidents…" />;

  return (
    <div className="page">
      <PageHeader title="Incidents" subtitle="Security incidents opened automatically or by an admin/reviewer action." />

      <TableToolbar
        filters={
          <>
            <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)} aria-label="Filter by status">
              <option value="">All statuses</option>
              {STATUSES.map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
            <select value={severityFilter} onChange={(e) => setSeverityFilter(e.target.value)} aria-label="Filter by severity">
              <option value="">All severities</option>
              {SEVERITIES.map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
          </>
        }
        onRefresh={load}
      />

      {incidents.length === 0 ? (
        <EmptyState title="No incidents match">Try a different filter.</EmptyState>
      ) : (
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>Title</th>
                <th>Severity</th>
                <th>Status</th>
                <th>Created</th>
              </tr>
            </thead>
            <tbody>
              {incidents.map((i) => (
                <tr key={i.id}>
                  <td><Link to={`/incidents/${i.id}`}>{i.title}</Link></td>
                  <td><StatusBadge value={i.severity} /></td>
                  <td><StatusBadge value={i.status} /></td>
                  <td>{formatDateTime(i.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
