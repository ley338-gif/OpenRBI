import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { StatusBadge } from "@shared/components/StatusBadge";
import { LoadingBlock, EmptyState, ErrorState } from "@shared/components/States";
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

  useEffect(() => {
    adminApi
      .listIncidents({ status_filter: statusFilter || undefined, severity_filter: severityFilter || undefined })
      .then(setIncidents)
      .catch(() => setError("Could not load incidents."));
  }, [statusFilter, severityFilter]);

  if (error) return <div className="page"><ErrorState>{error}</ErrorState></div>;
  if (!incidents) return <LoadingBlock label="Loading incidents…" />;

  return (
    <div className="page">
      <h1>Incidents</h1>

      <div className="filter-bar">
        <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
          <option value="">All statuses</option>
          {STATUSES.map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
        <select value={severityFilter} onChange={(e) => setSeverityFilter(e.target.value)}>
          <option value="">All severities</option>
          {SEVERITIES.map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
      </div>

      {incidents.length === 0 ? (
        <EmptyState>No incidents match.</EmptyState>
      ) : (
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
      )}
    </div>
  );
}
