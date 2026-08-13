import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "@shared/auth/AuthContext";
import { StatusBadge } from "@shared/components/StatusBadge";
import { StatCard } from "@shared/components/StatCard";
import { PageHeader } from "@shared/components/PageHeader";
import { LoadingBlock, ErrorState, EmptyState } from "@shared/components/States";
import { Icons } from "@shared/components/Icons";
import { formatDateTime } from "@shared/format";
import type { QuarantineFileDto, SessionResponseDto } from "@shared/api/types";
import { userApi } from "../api/userApi";

const LIVE_STATUSES = new Set(["QUEUED", "STARTING", "ACTIVE", "DISCONNECTED", "ISOLATING", "ISOLATED"]);

function secureBrowserCta(liveSession: SessionResponseDto | undefined): { title: string; body: string; button: string } {
  if (!liveSession) {
    return {
      title: "Secure Browser",
      body: "Start an isolated browser session to browse the web safely — nothing you see there ever reaches this device.",
      button: "Start Secure Browser",
    };
  }
  if (liveSession.status === "ISOLATED") {
    return {
      title: "Session isolated",
      body: "An administrator isolated this session. End it and start a new one to keep browsing.",
      button: "Open Secure Browser",
    };
  }
  return {
    title: "Secure Browser session running",
    body: "Your isolated browser session is ready — pick up where you left off.",
    button: "Open Secure Browser",
  };
}

export function Dashboard() {
  const { user } = useAuth();
  const [sessions, setSessions] = useState<SessionResponseDto[] | null>(null);
  const [files, setFiles] = useState<QuarantineFileDto[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  function load() {
    setError(null);
    Promise.all([userApi.mySessions(), userApi.myFiles()])
      .then(([s, f]) => {
        setSessions(s);
        setFiles(f);
      })
      .catch(() => setError("Could not load your dashboard. The backend may be unavailable."));
  }

  useEffect(load, []);

  if (error) {
    return (
      <div className="page">
        <ErrorState action={<button type="button" className="btn btn-secondary btn-sm" onClick={load}>Try again</button>}>
          {error}
        </ErrorState>
      </div>
    );
  }
  if (!sessions || !files) return <LoadingBlock label="Loading dashboard…" />;

  const liveSession = sessions.find((s) => LIVE_STATUSES.has(s.status));
  const recentFiles = files.slice(0, 5);
  const cta = secureBrowserCta(liveSession);

  return (
    <div className="page">
      <PageHeader title="Dashboard" subtitle="Current overview of your secure browsing environment." />

      <div className="stat-grid">
        <StatCard label="MFA" value={<StatusBadge value={user?.mfa_enabled ? "ENABLED" : "NOT ENABLED"} />} />
        <StatCard label="Downloads" value={files.length} hint="On file" />
        <StatCard
          label="Last session"
          value={sessions[0] ? formatDateTime(sessions[0].created_at) : "—"}
        />
      </div>

      <div className="card cta-card surface-emphasis">
        <div className="flex-between" style={{ marginBottom: 0 }}>
          <div style={{ display: "flex", gap: "16px", alignItems: "flex-start" }}>
            <div className="compact-row-icon" style={{ width: 44, height: 44, background: "var(--color-white)" }}>
              <Icons.Browser width={22} height={22} color="var(--color-accent-strong)" />
            </div>
            <div>
              <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{cta.title}</h2>
              <p className="text-muted" style={{ margin: "4px 0 0", maxWidth: "440px" }}>
                {cta.body}
              </p>
              {liveSession && (
                <p style={{ margin: "6px 0 0" }}>
                  <StatusBadge value={liveSession.status} />
                </p>
              )}
            </div>
          </div>
          <Link to="/browser" className="btn btn-primary">
            {cta.button}
          </Link>
        </div>
      </div>

      <div className="card">
        <div className="section-header">
          <h2>Recent downloads</h2>
          <Link to="/downloads" className="btn btn-secondary btn-sm">
            View all
          </Link>
        </div>
        {recentFiles.length === 0 ? (
          <EmptyState
            icon={<Icons.Download width={20} height={20} />}
            title="No downloads yet"
            action={
              <Link to="/downloads" className="btn btn-secondary btn-sm">
                Go to Downloads
              </Link>
            }
          >
            Files you download in a Secure Browser session and that get released appear here.
          </EmptyState>
        ) : (
          <div className="compact-list">
            {recentFiles.map((f) => (
              <div className="compact-row" key={f.id}>
                <div className="compact-row-icon">
                  <Icons.File width={16} height={16} />
                </div>
                <div className="compact-row-main">
                  <div className="compact-row-title">{f.original_name}</div>
                  <div className="compact-row-meta">
                    <StatusBadge value={f.status} />
                  </div>
                </div>
                <div className="compact-row-time">{formatDateTime(f.created_at)}</div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
