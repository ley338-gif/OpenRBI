import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { StatusBadge } from "@shared/components/StatusBadge";
import { LoadingBlock, ErrorState, EmptyState } from "@shared/components/States";
import { FormField } from "@shared/components/FormField";
import { PageHeader } from "@shared/components/PageHeader";
import { DefinitionList } from "@shared/components/DefinitionList";
import { useToast } from "@shared/components/Toast";
import { formatDateTime } from "@shared/format";
import type { IncidentDto, SecurityEventDto } from "@shared/api/types";
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
  const [events, setEvents] = useState<SecurityEventDto[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [resolution, setResolution] = useState("");
  const [busy, setBusy] = useState(false);

  function load() {
    if (!id) return;
    adminApi
      .getIncident(id)
      .then((i) => {
        setIncident(i);
        setResolution(i.resolution ?? "");
        // No incident->events link on the backend — approximated from the
        // same session/user this incident is actually about, using the
        // real filters GET /admin/security-events already supports.
        if (i.session_id) return adminApi.listSecurityEvents({ session_id: i.session_id, limit: 20 }).then(setEvents);
        if (i.user_id) return adminApi.listSecurityEvents({ user_id: i.user_id, limit: 20 }).then(setEvents);
      })
      .catch(() => setError("Could not load this incident."));
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
      <PageHeader
        title={incident.title}
        meta={
          <>
            <StatusBadge value={incident.severity} /> <StatusBadge value={incident.status} />
          </>
        }
      />

      <div className="card">
        <div className="section-header"><h2>Summary</h2></div>
        <DefinitionList
          items={[
            { label: "Created", value: formatDateTime(incident.created_at) },
            { label: "Updated", value: formatDateTime(incident.updated_at) },
          ]}
        />
        <p>{incident.description}</p>
      </div>

      {(incident.user_id || incident.session_id || incident.quarantine_file_id) && (
        <div className="card">
          <div className="section-header"><h2>Related</h2></div>
          <DefinitionList
            items={[
              ...(incident.user_id ? [{ label: "User", value: <Link to={`/users/${incident.user_id}`}>{incident.user_id.slice(0, 8)}</Link> }] : []),
              ...(incident.session_id
                ? [{ label: "Session", value: <Link to={`/sessions/${incident.session_id}`} className="mono">{incident.session_id.slice(0, 8)}</Link> }]
                : []),
              ...(incident.quarantine_file_id
                ? [{ label: "File", value: <Link to={`/quarantine/${incident.quarantine_file_id}`} className="mono">{incident.quarantine_file_id.slice(0, 8)}</Link> }]
                : []),
            ]}
          />
        </div>
      )}

      <div className="card">
        <div className="section-header"><h2>Security events</h2></div>
        {events.length === 0 ? (
          <EmptyState title="No related events found">
            {incident.session_id || incident.user_id
              ? "Nothing else was recorded for the related session/user."
              : "This incident has no related session or user to look events up by."}
          </EmptyState>
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th>Event</th>
                <th>Time</th>
              </tr>
            </thead>
            <tbody>
              {events.map((e) => (
                <tr key={e.id}>
                  <td>{e.event_type}</td>
                  <td>{formatDateTime(e.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {availableTransitions.length > 0 && (
        <div className="card">
          <div className="section-header"><h2>Resolution</h2></div>
          <FormField label="Resolution note (optional)">
            <textarea value={resolution} onChange={(e) => setResolution(e.target.value)} rows={3} />
          </FormField>
          <div style={{ display: "flex", gap: "8px" }}>
            {availableTransitions.map((t) => (
              <button key={t} type="button" className="btn btn-secondary" disabled={busy} onClick={() => void transition(t)}>
                {t === "INVESTIGATING" ? "Start investigation" : t === "RESOLVED" ? "Resolve" : "Mark false positive"}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
