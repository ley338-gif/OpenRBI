import { Fragment, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { EmptyState, ErrorState, LoadingBlock } from "@shared/components/States";
import { PageHeader } from "@shared/components/PageHeader";
import { TableToolbar } from "@shared/components/TableToolbar";
import { formatDateTime } from "@shared/format";
import { SECURITY_EVENT_TYPES, type SecurityEventDto } from "@shared/api/types";
import { adminApi } from "../api/adminApi";

const PAGE_SIZE = 50;

/**
 * Structured event summary by default; raw metadata only behind an
 * explicit toggle (section 36) — never a JSON blob as the default view.
 * Roadmap B1.10.7: added the user filter and a datalist of known event
 * types (autocomplete only, not validated — the backend remains
 * authoritative on what's a real filter value) plus clickable user/session
 * links, reusing GET /admin/security-events' existing filters, never a
 * second audit store.
 */
export function Audit() {
  const [events, setEvents] = useState<SecurityEventDto[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [offset, setOffset] = useState(0);
  const [eventType, setEventType] = useState("");
  const [userId, setUserId] = useState("");
  const [expanded, setExpanded] = useState<string | null>(null);

  function load() {
    setError(null);
    adminApi
      .listSecurityEvents({
        event_type: eventType || undefined,
        user_id: userId || undefined,
        limit: PAGE_SIZE,
        offset,
      })
      .then(setEvents)
      .catch(() => setError("Could not load the audit trail. The backend may be unavailable."));
  }

  useEffect(load, [offset, eventType, userId]);

  if (error) {
    return (
      <div className="page">
        <ErrorState action={<button type="button" className="btn btn-secondary btn-sm" onClick={load}>Try again</button>}>
          {error}
        </ErrorState>
      </div>
    );
  }
  if (!events) return <LoadingBlock label="Loading audit trail…" />;

  return (
    <div className="page">
      <PageHeader title="Audit" subtitle="Append-only trail of every security-relevant action." />

      <TableToolbar
        search={eventType}
        onSearchChange={(v) => {
          setOffset(0);
          setEventType(v);
        }}
        searchPlaceholder="Filter by event type (e.g. SESSION_ISOLATED)…"
        searchListId="security-event-types"
        onRefresh={load}
        filters={
          <input
            placeholder="Filter by user ID"
            value={userId}
            onChange={(e) => {
              setOffset(0);
              setUserId(e.target.value);
            }}
            className="mono"
            style={{ width: "260px" }}
          />
        }
        actions={
          (eventType || userId) && (
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={() => {
                setOffset(0);
                setEventType("");
                setUserId("");
              }}
            >
              Clear filters
            </button>
          )
        }
      />
      <datalist id="security-event-types">
        {SECURITY_EVENT_TYPES.map((t) => (
          <option key={t} value={t} />
        ))}
      </datalist>

      {events.length === 0 ? (
        <EmptyState title="No security events match">Try a different event-type filter.</EmptyState>
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
                    <td className="mono" style={{ fontSize: "0.8rem" }}>
                      {e.user_id ? <Link to={`/users/${e.user_id}`}>{e.user_id.slice(0, 8)}</Link> : "—"}
                    </td>
                    <td className="mono" style={{ fontSize: "0.8rem" }}>
                      {e.session_id ? <Link to={`/sessions/${e.session_id}`}>{e.session_id.slice(0, 8)}</Link> : "—"}
                    </td>
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
