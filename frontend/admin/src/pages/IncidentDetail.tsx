import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { StatusBadge } from "@shared/components/StatusBadge";
import { LoadingBlock, ErrorState } from "@shared/components/States";
import { FormField } from "@shared/components/FormField";
import { useToast } from "@shared/components/Toast";
import { formatDateTime } from "@shared/format";
import type { IncidentDto } from "@shared/api/types";
import { adminApi } from "../api/adminApi";

const TRANSITIONS: Record<string, string[]> = {
  NEW: ["INVESTIGATING", "RESOLVED", "FALSE_POSITIVE"],
  INVESTIGATING: ["RESOLVED", "FALSE_POSITIVE"],
  RESOLVED: [],
  FALSE_POSITIVE: [],
};

export function IncidentDetail() {
  const { id } = useParams<{ id: string }>();
  const { notify } = useToast();
  const [incident, setIncident] = useState<IncidentDto | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [resolution, setResolution] = useState("");
  const [busy, setBusy] = useState(false);

  function load() {
    if (!id) return;
    adminApi.getIncident(id).then((i) => {
      setIncident(i);
      setResolution(i.resolution ?? "");
    }).catch(() => setError("Could not load this incident."));
  }
  useEffect(load, [id]);

  async function transition(status: string) {
    if (!id) return;
    setBusy(true);
    try {
      const updated = await adminApi.updateIncident(id, { status, resolution: resolution || undefined });
      setIncident(updated);
      notify(`Incident marked ${status}`);
    } catch {
      notify("Could not update incident", "error");
    } finally {
      setBusy(false);
    }
  }

  if (error) return <div className="page"><ErrorState>{error}</ErrorState></div>;
  if (!incident) return <LoadingBlock label="Loading incident…" />;

  const availableTransitions = TRANSITIONS[incident.status] ?? [];

  return (
    <div className="page">
      <p><Link to="/incidents">← Incidents</Link></p>
      <h1>{incident.title}</h1>

      <div className="card">
        <dl className="detail-grid">
          <div><dt>Severity</dt><dd><StatusBadge value={incident.severity} /></dd></div>
          <div><dt>Status</dt><dd><StatusBadge value={incident.status} /></dd></div>
          <div><dt>Created</dt><dd>{formatDateTime(incident.created_at)}</dd></div>
          <div><dt>Updated</dt><dd>{formatDateTime(incident.updated_at)}</dd></div>
          {incident.user_id && <div><dt>User</dt><dd><Link to={`/users/${incident.user_id}`}>{incident.user_id.slice(0, 8)}</Link></dd></div>}
          {incident.session_id && (
            <div><dt>Session</dt><dd><Link to={`/sessions/${incident.session_id}`} className="mono">{incident.session_id.slice(0, 8)}</Link></dd></div>
          )}
          {incident.quarantine_file_id && (
            <div><dt>File</dt><dd><Link to={`/quarantine/${incident.quarantine_file_id}`} className="mono">{incident.quarantine_file_id.slice(0, 8)}</Link></dd></div>
          )}
        </dl>
        <p>{incident.description}</p>

        {availableTransitions.length > 0 && (
          <>
            <FormField label="Resolution note">
              <textarea value={resolution} onChange={(e) => setResolution(e.target.value)} rows={3} />
            </FormField>
            <div style={{ display: "flex", gap: "8px" }}>
              {availableTransitions.map((t) => (
                <button key={t} type="button" className="btn btn-secondary" disabled={busy} onClick={() => void transition(t)}>
                  {t === "INVESTIGATING" ? "Start investigation" : t === "RESOLVED" ? "Resolve" : "Mark false positive"}
                </button>
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
