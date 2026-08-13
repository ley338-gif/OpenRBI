import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "@shared/auth/AuthContext";
import { StatusBadge } from "@shared/components/StatusBadge";
import { StatCard } from "@shared/components/StatCard";
import { PageHeader } from "@shared/components/PageHeader";
import { EmptyState } from "@shared/components/States";
import { Icons } from "@shared/components/Icons";
import { formatBytes, formatDateTime } from "@shared/format";
import type { SessionResponseDto, UserFilePageDto } from "@shared/api/types";
import { userApi } from "../api/userApi";

const LIVE_STATUSES = new Set(["QUEUED", "STARTING", "ACTIVE", "DISCONNECTED", "ISOLATING", "ISOLATED"]);

function sessionPresentation(session?: SessionResponseDto) {
  if (!session) return { state: "NO SESSION", connection: "DISCONNECTED", body: "Start an isolated browser session when you are ready.", action: "Start Secure Browser" };
  if (session.status === "QUEUED" || session.status === "STARTING") return { state: "STARTING", connection: "WAITING", body: "Your isolated browser environment is being prepared.", action: "View session" };
  if (session.status === "FAILED") return { state: "FAILED", connection: "DISCONNECTED", body: "The last browser session could not be started.", action: "Try again" };
  if (session.status === "ISOLATED" || session.status === "ISOLATING") return { state: "ISOLATED", connection: "DISCONNECTED", body: "This session was isolated by an administrator.", action: "Open Secure Browser" };
  return { state: "READY", connection: session.status === "DISCONNECTED" ? "DISCONNECTED" : "CONNECTED", body: session.status === "DISCONNECTED" ? "Your session is running. Open it to reconnect the viewer." : "Your isolated browser session is ready to continue.", action: session.status === "DISCONNECTED" ? "Resume session" : "Open Secure Browser" };
}

function displayFileStatus(status: string): string { return ({ PENDING_SCAN: "PENDING", QUARANTINED: "PENDING REVIEW", RELEASED: "APPROVED", REJECTED: "BLOCKED" } as Record<string, string>)[status] ?? status; }

export function Dashboard() {
  const { user } = useAuth();
  const [sessions, setSessions] = useState<SessionResponseDto[] | null>(null);
  const [downloads, setDownloads] = useState<UserFilePageDto | null>(null);
  const [sessionError, setSessionError] = useState(false);
  const [downloadError, setDownloadError] = useState(false);

  function loadSessions() { setSessionError(false); userApi.mySessions().then(setSessions).catch(() => setSessionError(true)); }
  function loadDownloads() {
    setDownloadError(false);
    userApi.myFilesPage(new URLSearchParams({ status_filter: "all", offset: "0", limit: "5" })).then(setDownloads).catch(() => setDownloadError(true));
  }
  useEffect(() => { loadSessions(); loadDownloads(); }, []);

  const liveSession = sessions?.find((s) => LIVE_STATUSES.has(s.status));
  const lastSession = sessions?.[0];
  const session = sessionPresentation(liveSession);
  const summary = downloads?.summary;

  return <div className="page user-dashboard">
    <PageHeader title="Dashboard" subtitle="Current overview of your secure browsing environment." />

    <div className="stat-grid dashboard-kpis">
      <StatCard icon={<Icons.Shield />} label="MFA status" value={<StatusBadge value={user?.mfa_enabled ? "ENABLED" : "DISABLED"} />} hint={user?.mfa_enabled ? "Multi-factor authentication is active." : "Add a second factor to protect your account."} action={!user?.mfa_enabled ? <Link to="/profile">Set up MFA →</Link> : undefined} />
      <StatCard icon={<Icons.Download />} label="Downloads" value={summary?.total ?? "—"} hint="Files recorded" action={<Link to="/downloads">View all downloads →</Link>} />
      <StatCard icon={<Icons.Shield />} label="Files in review" value={summary?.pending ?? "—"} hint="Processing or awaiting review" action={<Link to="/downloads?status=pending">Go to Downloads →</Link>} />
      <StatCard icon={<Icons.Shield />} label="Approved files" value={summary?.approved ?? "—"} hint="Released for download" action={<Link to="/downloads?status=approved">Go to Downloads →</Link>} />
      <StatCard icon={<Icons.Quarantine />} label="Blocked files" value={summary?.blocked ?? "—"} hint="Rejected by security" action={<Link to="/downloads?status=blocked">Go to Downloads →</Link>} />
    </div>
    {downloadError && <div className="inline-error">Download status is currently unavailable. <button onClick={loadDownloads}>Retry</button></div>}

    <section className="card session-hero surface-emphasis">
      <div className="session-hero-main"><div className="session-hero-icon"><Icons.Browser /></div><div><h2>Secure Browser session</h2><StatusBadge value={session.state} /><p>{session.body}</p></div></div>
      {sessionError ? <div className="session-hero-status"><span>Session status</span><strong>Unavailable</strong><button className="btn btn-secondary btn-sm" onClick={loadSessions}>Retry</button></div> : <>
        <div className="session-hero-status"><span>Last session</span><strong>{lastSession ? formatDateTime(lastSession.created_at) : "None yet"}</strong></div>
        <div className="session-hero-status"><span>Connection</span><StatusBadge value={session.connection} /></div>
      </>}
      <Link to="/browser" className="btn btn-primary">{session.action}</Link>
    </section>

    <div className="dashboard-content-grid">
      <section className="card dashboard-recent">
        <div className="section-header"><h2>Recent downloads</h2><Link to="/downloads" className="btn btn-secondary btn-sm">View all</Link></div>
        {downloadError ? <div className="error-state">Recent downloads are currently unavailable.</div> : !downloads ? <DashboardRowsSkeleton /> : downloads.items.length === 0 ? <EmptyState icon={<Icons.Download />} title="No downloads yet">Files downloaded during a Secure Browser session will appear here after security processing.</EmptyState> : <div className="dashboard-file-list">{downloads.items.map((file) => <div className="dashboard-file-row" key={file.id}>
          <div className="file-type-icon"><Icons.File /></div><div className="dashboard-file-name"><strong>{file.original_name}</strong><span>{file.detected_mime ?? file.declared_mime ?? "Unknown file type"}</span></div><span>{formatDateTime(file.created_at)}</span><span>{formatBytes(file.size_bytes)}</span><StatusBadge value={displayFileStatus(file.status)} />
        </div>)}</div>}
      </section>

      <div className="dashboard-side-column">
        <section className="card security-summary"><div className="section-header"><h2>Security summary</h2></div>
          {summary ? <div className="summary-list"><SummaryRow label="Released" value={summary.approved} tone="healthy" /><SummaryRow label="Pending review" value={summary.pending} tone="warning" /><SummaryRow label="Blocked" value={summary.blocked} tone="critical" /><SummaryRow label="Other states" value={Math.max(0, summary.total - summary.approved - summary.pending - summary.blocked)} tone="neutral" /></div> : <DashboardRowsSkeleton />}
        </section>
        <section className="card quick-actions"><div className="section-header"><h2>Quick actions</h2></div><div className="quick-action-grid">
          <Link to="/browser"><Icons.Browser /><span>Open Secure Browser</span></Link><Link to="/downloads"><Icons.Download /><span>Downloads</span></Link><Link to="/profile"><Icons.Shield /><span>Profile & Security</span></Link>
        </div></section>
      </div>
    </div>

    <div className="dashboard-security-note"><Icons.Shield /><div><strong>Your security is our priority</strong><p>Files downloaded through Secure Browser are processed according to your organization’s security policies before they are released.</p></div><a href="/docs/user-guide.md">Learn more</a></div>
  </div>;
}

function SummaryRow({ label, value, tone }: { label: string; value: number; tone: string }) { return <div className="summary-row"><span className={`summary-dot ${tone}`} /><span>{label}</span><strong>{value}</strong></div>; }
function DashboardRowsSkeleton() { return <div className="dashboard-skeleton" aria-label="Loading"><span /><span /><span /></div>; }
