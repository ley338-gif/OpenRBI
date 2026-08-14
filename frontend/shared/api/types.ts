// Hand-written from the backend's actual OpenAPI schema (fetched from a
// running `both`-mode instance during this work, not assumed from docs —
// see docs/architecture.md#user-portal--admin-portal for why this project
// didn't introduce an OpenAPI-codegen toolchain for a schema this size).
// Keep in sync with backend/app/api/schemas/*.py if either changes.

export type Role = "USER" | "SECURITY_REVIEWER" | "ADMIN";

export interface CurrentUser {
  id: string;
  username: string;
  role: Role;
  mfa_enabled: boolean;
  auth_source: "LOCAL" | "LDAP";
  created_at: string;
}

export interface LoginResponse {
  status: "ok" | "mfa_required" | "mfa_enrollment_required";
  mfa_token: string | null;
}

export interface EnrollResponse {
  otpauth_uri: string;
  qr_code_png_base64: string;
}

export interface EnrollConfirmResponse {
  recovery_codes: string[];
}

export interface SetupConfirmResponse {
  status: string;
  recovery_codes: string[];
}

// Roadmap B1.9 — first-run bootstrap (backend/app/api/schemas/setup.py).
// Deliberately a different name/shape from SetupConfirmResponse above,
// which is the *mandatory-MFA-enrollment* response every ADMIN's first
// login can hit — these two are unrelated flows that happen to share the
// word "setup".
export interface FirstRunStatusResponse {
  setup_required: boolean;
}

export interface FirstRunAdminRequest {
  setup_token: string;
  username: string;
  password: string;
}

export interface FirstRunAdminResponse {
  mfa_token: string;
}

export interface FirstRunMfaConfirmResponse {
  status: string;
  recovery_codes: string[];
}

export type SessionStatus =
  | "QUEUED"
  | "STARTING"
  | "ACTIVE"
  | "DISCONNECTED"
  | "ISOLATING"
  | "ISOLATED"
  | "TERMINATING"
  | "TERMINATED"
  | "FAILED";

export interface SessionResponseDto {
  id: string;
  status: SessionStatus;
  browser: string;
  sandbox_backend: string;
  display_backend: string;
  cpu_limit: number;
  ram_limit_mb: number;
  pid_limit: number;
  disk_limit_mb: number;
  screen_width: number;
  screen_height: number;
  created_at: string;
  started_at: string | null;
  ended_at: string | null;
}

export interface AdminSessionDto extends SessionResponseDto {
  user_id: string;
  username: string;
  node_id: string | null;
  worker_hostname: string | null;
}

export interface AdminSessionListDto {
  items: AdminSessionDto[];
  total: number;
  offset: number;
  limit: number;
  stats: { active: number; sessions_today: number; average_duration_seconds_24h: number | null; failed_24h: number; terminated_24h: number };
  statuses: SessionStatus[];
}

// Roadmap B1.10.4 — bulk session revocation from the User Detail page
export interface RevokeSessionsResponseDto {
  terminated_count: number;
  session_ids: string[];
}

// Roadmap B1.10.5 — Account Lock/Unlock, the same brute-force-lockout
// state /auth/login itself checks (backend/app/api/schemas/admin.py's LockoutStatus)
export interface LockoutStatusDto {
  locked: boolean;
  failure_count: number;
  locked_seconds_remaining: number | null;
}

// Roadmap B1.10.6 — Login Diagnostics
export interface RecentFailedAttemptDto {
  event_type: string;
  created_at: string;
}

export interface LoginDiagnosticsResponseDto {
  username: string;
  user_id: string | null;
  account_exists: boolean;
  is_active: boolean | null;
  mfa_enabled: boolean | null;
  auth_source: string | null;
  ldap_enabled: boolean;
  lockout: LockoutStatusDto;
  recent_failed_attempts: RecentFailedAttemptDto[];
  possible_reasons: string[];
}

export type QuarantineStatus = "PENDING_SCAN" | "SCANNING" | "QUARANTINED" | "RELEASED" | "REJECTED" | "DELETED";
export type ScannerStatus = "PENDING" | "SCANNING" | "CLEAN" | "INFECTED" | "ERROR";
export type FileAction = "AUTO_RELEASE" | "QUARANTINE" | "DENY";

export interface QuarantineFileDto {
  id: string;
  session_id: string;
  user_id: string;
  original_name: string;
  extension: string | null;
  declared_mime: string | null;
  detected_mime: string | null;
  size_bytes: number;
  sha256: string;
  initial_url: string | null;
  final_url: string | null;
  source_host: string | null;
  tls_used: boolean | null;
  scanner_status: ScannerStatus;
  scanner_result: string | null;
  policy_action: FileAction | null;
  status: QuarantineStatus;
  created_at: string;
  reviewed_at: string | null;
  reviewed_by: string | null;
  review_comment: string | null;
}

export interface UserFilePageDto {
  items: QuarantineFileDto[];
  summary: { total: number; pending: number; approved: number; blocked: number };
  total_filtered: number;
  offset: number;
  limit: number;
}

export interface DownloadTokenResponse {
  token: string;
  expires_in_seconds: number;
}

export interface UserSummaryDto {
  id: string;
  username: string;
  role: Role;
  is_active: boolean;
  mfa_enabled: boolean;
  groups: GroupRefDto[];
  created_at: string;
  auth_source: "LOCAL" | "LDAP";
  last_login_at: string | null;
}

export interface UserListResponseDto {
  items: UserSummaryDto[];
  total: number;
  offset: number;
  limit: number;
  roles: Role[];
  stats: { total: number; active: number; mfa_enabled: number; administrators: number; groups: number };
}

export interface GroupSummaryDto {
  id: string;
  name: string;
  description: string | null;
  member_count: number;
}

export interface GroupOverviewDto extends GroupSummaryDto {
  policies: string[];
  created_at: string;
}

export interface GroupOverviewResponseDto {
  items: GroupOverviewDto[];
  total: number;
  offset: number;
  limit: number;
  stats: { total: number; memberships: number; with_policies: number };
}

export type PolicyType = "NETWORK" | "DOWNLOADS" | "UPLOADS" | "CLIPBOARD" | "BROWSER" | "SESSION" | "MIME" | "SOURCE";
export type PolicyVersionStatus = "DRAFT" | "PUBLISHED" | "SUPERSEDED";
export type FileRuleType = "MIME" | "SOURCE";

export interface GroupRefDto {
  id: string;
  name: string;
}

export interface PolicyRefDto {
  id: string;
  name: string;
  policy_type: PolicyType;
}

export interface UserRefDto {
  id: string;
  username: string;
}

export interface GroupDetailDto extends GroupSummaryDto {
  created_at: string;
  policies: PolicyRefDto[];
  members: UserRefDto[];
}

export interface PolicySummaryDto {
  id: string;
  name: string;
  policy_type: PolicyType;
  description: string | null;
  current_version_id: string | null;
  current_version_number: number | null;
  has_draft: boolean;
  version_count: number;
  assigned_groups: GroupRefDto[];
  created_at: string;
  updated_at: string;
  updated_by: string | null;
}

export interface PolicyListResponseDto {
  items: PolicySummaryDto[];
  total: number;
  offset: number;
  limit: number;
  stats: { total: number; published: number; drafts: number; in_use: number; total_versions: number; last_updated_at: string | null; last_updated_by: string | null };
}

export interface FileRuleResponseDto {
  id: string;
  rule_type: FileRuleType;
  match_pattern: string;
  action: FileAction;
  priority: number;
}

export interface PolicyVersionDto {
  id: string;
  version_number: number;
  status: PolicyVersionStatus;
  content: Record<string, unknown>;
  file_rules: FileRuleResponseDto[];
  created_at: string;
  published_at: string | null;
}

export interface PolicyDetailDto extends PolicySummaryDto {
  versions: PolicyVersionDto[];
}

export type IncidentSeverity = "INFO" | "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
export type IncidentStatus = "NEW" | "INVESTIGATING" | "RESOLVED" | "FALSE_POSITIVE";

export interface IncidentDto {
  id: string;
  severity: IncidentSeverity;
  status: IncidentStatus;
  title: string;
  description: string;
  user_id: string | null;
  session_id: string | null;
  quarantine_file_id: string | null;
  assigned_to: string | null;
  resolution: string | null;
  created_at: string;
  updated_at: string;
}

export interface SecurityEventDto {
  id: string;
  event_type: string;
  user_id: string | null;
  session_id: string | null;
  quarantine_file_id: string | null;
  metadata_json: Record<string, unknown> | null;
  created_at: string;
}

// Every value of backend/app/models/enums.py's SecurityEventType, kept in
// sync by hand like this project's other backend-enum mirrors (e.g.
// Sessions.tsx's own STATUSES constant) — used only to populate the Audit
// page's event-type filter suggestions, not to validate/reject anything;
// the backend remains authoritative on what's a real event type.
export const SECURITY_EVENT_TYPES = [
  "USER_CREATED",
  "USER_DISABLED",
  "USER_ENABLED",
  "USER_LOGIN",
  "USER_LOGIN_FAILED",
  "LOGIN_LOCKED",
  "MFA_ENROLLED",
  "MFA_FAILED",
  "MFA_RESET",
  "RECOVERY_CODE_USED",
  "SESSION_STARTED",
  "SESSION_DISCONNECTED",
  "SESSION_ISOLATED",
  "SESSION_RESTORED",
  "SESSION_TERMINATED",
  "NETWORK_ACCESS_BLOCKED",
  "DOWNLOAD_REQUESTED",
  "DOWNLOAD_BLOCKED",
  "FILE_QUARANTINED",
  "FILE_RELEASED",
  "FILE_REJECTED",
  "MALWARE_DETECTED",
  "POLICY_CHANGED",
  "POLICY_PUBLISHED",
  "NODE_DRAINED", // superseded by WORKER_DRAIN_ENABLED (B1.10.1) but kept for filtering older rows
  "USER_ROLE_CHANGED",
  "USER_GROUPS_CHANGED",
  "PASSWORD_RESET_BY_ADMIN",
  "PASSWORD_CHANGED",
  "GROUP_CREATED",
  "GROUP_DELETED",
  "UPLOAD_REQUESTED",
  "UPLOAD_BLOCKED",
  "USER_PROVISIONED_VIA_LDAP",
  "LDAP_CONFIG_CHANGED",
  "LDAP_ENABLED",
  "LDAP_DISABLED",
  "LDAP_CONNECTION_TESTED",
  "INITIAL_ADMIN_CREATED",
  "SYSTEM_INITIALIZED",
  "WORKER_DRAIN_ENABLED",
  "WORKER_DRAIN_DISABLED",
  "WORKER_MAINTENANCE_ENABLED",
  "WORKER_MAINTENANCE_DISABLED",
  "USER_SESSIONS_REVOKED",
  "ACCOUNT_LOCKED",
  "ACCOUNT_UNLOCKED",
] as const;

export type ComponentStatus = "HEALTHY" | "DEGRADED" | "UNAVAILABLE";

export interface ComponentHealthDto {
  name: string;
  status: ComponentStatus;
  detail: string | null;
}

export interface SystemHealthDto {
  status: ComponentStatus;
  components: ComponentHealthDto[];
}

export type BrowserNodeStatus = "ONLINE" | "DRAINING" | "OFFLINE" | "DEGRADED" | "MAINTENANCE";

export interface BrowserNodeDto {
  id: string;
  hostname: string;
  status: BrowserNodeStatus;
  // Roadmap B1.10.1 — the centrally-computed label; read this for display,
  // not `status` (the raw scheduling flag).
  health: WorkerHealthLabel;
  capacity: number;
  active_sessions: number;
  runtime: string;
  version: string | null;
  last_heartbeat: string | null;
  cpu_percent: number | null;
  ram_total_mb: number | null;
  ram_used_mb: number | null;
  uptime_seconds: number | null;
}

export interface WorkerOverviewDto {
  items: BrowserNodeDto[];
  total: number;
  offset: number;
  limit: number;
  stats: { total: number; healthy: number; needs_attention: number; active_sessions: number; total_capacity: number; average_cpu_percent: number | null; average_ram_percent: number | null; latest_heartbeat: string | null };
}

// Roadmap B1.10.3 — per-worker bucketed metric history (Worker Detail view)
export interface NodeHistoryPointDto {
  t: string;
  cpu_percent: number | null;
  ram_percent: number | null;
  active_sessions: number;
}

// Roadmap B1.8 — admin-portal-managed LDAP configuration
// (backend/app/api/schemas/admin_ldap.py). LdapConfigDto never carries the
// bind password, structurally — only bind_password_configured — matching
// the backend response shape exactly.
export interface LdapConfigDto {
  enabled: boolean;
  server_uri: string;
  use_starttls: boolean;
  bind_dn: string;
  bind_password_configured: boolean;
  base_dn: string;
  user_search_filter: string;
  group_attribute: string;
  group_role_mapping: Record<string, string>;
  updated_by: string | null;
}

export interface LdapConfigUpdateRequest {
  enabled: boolean;
  server_uri: string;
  use_starttls: boolean;
  bind_dn: string;
  // Omit entirely to keep the existing stored secret.
  bind_password?: string;
  base_dn: string;
  user_search_filter: string;
  group_attribute: string;
  group_role_mapping: Record<string, string>;
}

export interface LdapTestRequest {
  server_uri: string;
  use_starttls: boolean;
  bind_dn: string;
  bind_password: string;
  base_dn: string;
  user_search_filter: string;
  group_attribute: string;
  test_username?: string | null;
}

export interface LdapTestStepDto {
  name: string;
  ok: boolean;
  detail: string | null;
}

export interface LdapTestResponseDto {
  success: boolean;
  steps: LdapTestStepDto[];
  groups_discovered: number | null;
}

// Roadmap B1.10.2 — Operations Dashboard (backend/app/api/schemas/dashboard.py)
export type DashboardRange = "1h" | "6h" | "24h" | "7d";

export interface DashboardKpisDto {
  active_sessions: number;
  active_sessions_delta_last_hour: number | null;
  workers_healthy: number;
  workers_total: number;
  system_health: string;
  avg_cpu_percent: number | null;
  avg_ram_percent: number | null;
  users: number;
  files_processed_24h: number;
  blocked_files_24h: number;
  incidents_24h: number;
}

export interface SessionHistoryPointDto {
  t: string;
  count: number;
}

export type WorkerHealthLabel = "HEALTHY" | "DEGRADED" | "DRAINING" | "MAINTENANCE" | "OFFLINE";

export interface WorkerSummaryDto {
  id: string;
  hostname: string;
  health: WorkerHealthLabel;
  cpu_percent: number | null;
  ram_percent: number | null;
  active_sessions: number;
  capacity: number;
}

export interface DashboardWarningDto {
  kind: string;
  message: string;
  worker_hostname: string | null;
  username: string | null;
}

export interface DashboardResponseDto {
  generated_at: string;
  telemetry_stale: boolean;
  kpis: DashboardKpisDto;
  session_history: SessionHistoryPointDto[];
  workers: WorkerSummaryDto[];
  warnings: DashboardWarningDto[];
  file_statuses_24h: { status: string; count: number }[];
  quarantine_pending: number;
  quarantine_high_risk: number;
  recent_incidents: { id: string; severity: string; status: string; title: string; created_at: string }[];
}
