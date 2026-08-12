import { Fragment, useEffect, useState } from "react";
import { EmptyState, ErrorState, LoadingBlock } from "@shared/components/States";
import { formatDateTime } from "@shared/format";
import type { SecurityEventDto } from "@shared/api/types";
import { adminApi } from "../api/adminApi";

const PAGE_SIZE = 50;

/**
 * Structured event summary by default; raw metadata only behind an
 * explicit toggle (section 36) — never a JSON blob as the default view.
 */
export function Audit() {
  const [events, setEvents] = useState<SecurityEventDto[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [offset, setOffset] = useState(0);
  const [eventType, setEventType] = useState("");
  const [expanded, setExpanded] = useState<string | null>(null);

  function load() {
    adminApi
      .listSecurityEvents({ event_type: eventType || undefined, limit: PAGE_SIZE, offset })
      .then(setEvents)
      .catch(() => setError("Could not load the audit trail. The backend may be unavailable."));
  }

  useEffect(load, [offset, eventType]);

  if (error) return <div className="page"><ErrorState>{error}</ErrorState></div>;
  if (!events) return <LoadingBlock label="Loading audit trail…" />;

  return (
    <div className="page">
      <h1>Audit</h1>

      <div className="filter-bar">
        <input
          placeholder="Filter by event type (e.g. SESSION_ISOLATED)"
          value={eventType}
          onChange={(e) => {
            setOffset(0);
            setEventType(e.target.value);
          }}
          style={{ width: "280px" }}
        />
      </div>

      {events.length === 0 ? (
        <EmptyState>No security events match.</EmptyState>
      ) : (
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>Time</th>
                <th>Event</th>
                <th>User</th>
                <th>Session</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {events.map((e) => (
                <Fragment key={e.id}>
                  <tr>
                    <td>{formatDateTime(e.created_at)}</td>
                    <td>{e.event_type}</td>
                    <td className="mono" style={{ fontSize: "0.8rem" }}>{e.user_id?.slice(0, 8) ?? "—"}</td>
                    <td className="mono" style={{ fontSize: "0.8rem" }}>{e.session_id?.slice(0, 8) ?? "—"}</td>
                    <td>
                      <button
                        type="button"
                        className="btn btn-secondary btn-sm"
                        onClick={() => setExpanded(expanded === e.id ? null : e.id)}
                      >
                        {expanded === e.id ? "Hide" : "Show raw event"}
                      </button>
                    </td>
                  </tr>
                  {expanded === e.id && (
                    <tr>
                      <td colSpan={5}>
                        <pre className="mono" style={{ fontSize: "0.78rem", whiteSpace: "pre-wrap" }}>
                          {JSON.stringify(e, null, 2)}
                        </pre>
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div style={{ display: "flex", gap: "8px", marginTop: "12px" }}>
        <button type="button" className="btn btn-secondary btn-sm" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>
          Previous
        </button>
        <button type="button" className="btn btn-secondary btn-sm" disabled={events.length < PAGE_SIZE} onClick={() => setOffset(offset + PAGE_SIZE)}>
          Next
        </button>
      </div>
    </div>
  );
}
