import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "@shared/auth/AuthContext";
import { StatusBadge } from "@shared/components/StatusBadge";
import { LoadingBlock, ErrorState } from "@shared/components/States";
import { formatDateTime } from "@shared/format";
import type { QuarantineFileDto, SessionResponseDto } from "@shared/api/types";
import { userApi } from "../api/userApi";

const LIVE_STATUSES = new Set(["QUEUED", "STARTING", "ACTIVE", "DISCONNECTED", "ISOLATING", "ISOLATED"]);

export function Dashboard() {
  const { user } = useAuth();
  const [sessions, setSessions] = useState<SessionResponseDto[] | null>(null);
  const [files, setFiles] = useState<QuarantineFileDto[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([userApi.mySessions(), userApi.myFiles()])
      .then(([s, f]) => {
        setSessions(s);
        setFiles(f);
      })
      .catch(() => setError("Could not load your dashboard. The backend may be unavailable."));
  }, []);

  if (error) return <div className="page"><ErrorState>{error}</ErrorState></div>;
  if (!sessions || !files) return <LoadingBlock label="Loading dashboard…" />;

  const liveSession = sessions.find((s) => LIVE_STATUSES.has(s.status));
  const recentFiles = files.slice(0, 5);

  return (
    <div className="page">
      <h1>Dashboard</h1>

      <div className="stat-grid">
        <div className="stat-card">
          <div className="label">MFA</div>
          <div className="value" style={{ fontSize: "1.1rem" }}>
            <StatusBadge value={user?.mfa_enabled ? "ENABLED" : "NOT ENABLED"} />
          </div>
        </div>
        <div className="stat-card">
          <div className="label">Downloads on file</div>
          <div className="value">{files.length}</div>
        </div>
        <div className="stat-card">
          <div className="label">Last session</div>
          <div className="value" style={{ fontSize: "1.1rem" }}>
            {sessions[0] ? formatDateTime(sessions[0].created_at) : "—"}
          </div>
        </div>
      </div>

      <div className="card">
        <div className="flex-between" style={{ marginBottom: 0 }}>
          <div>
            <h2 style={{ margin: 0, fontSize: "1.1rem" }}>Secure Browser</h2>
            {liveSession ? (
              <p className="text-muted" style={{ margin: "4px 0 0" }}>
                Current session: <StatusBadge value={liveSession.status} />
              </p>
            ) : (
              <p className="text-muted" style={{ margin: "4px 0 0" }}>No active session.</p>
            )}
          </div>
          <Link to="/browser" className="btn btn-primary">
            {liveSession ? "Open Secure Browser" : "Start Secure Browser"}
          </Link>
        </div>
      </div>

      <div className="card">
        <div className="flex-between" style={{ marginBottom: "8px" }}>
          <h2 style={{ margin: 0, fontSize: "1.1rem" }}>Recent downloads</h2>
          <Link to="/downloads">View all</Link>
        </div>
        {recentFiles.length === 0 ? (
          <p className="text-muted">No downloads yet.</p>
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th>File</th>
                <th>Status</th>
                <th>Date</th>
              </tr>
            </thead>
            <tbody>
              {recentFiles.map((f) => (
                <tr key={f.id}>
                  <td>{f.original_name}</td>
                  <td><StatusBadge value={f.status} /></td>
                  <td>{formatDateTime(f.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
