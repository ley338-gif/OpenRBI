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
  created_at: string;
  started_at: string | null;
  ended_at: string | null;
}

export interface AdminSessionDto extends SessionResponseDto {
  user_id: string;
  username: string;
}

// Roadmap B1.10.4 — bulk session revocation from the User Detail page
export interface RevokeSessionsResponseDto {
  terminated_count: number;
  session_ids: string[];
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
  groups: string[];
  created_at: string;
}

export interface GroupSummaryDto {
  id: string;
  name: string;
  description: string | null;
  member_count: number;
}

export type PolicyType = "NETWORK" | "DOWNLOADS" | "UPLOADS" | "CLIPBOARD" | "BROWSER" | "SESSION" | "MIME" | "SOURCE";
export type PolicyVersionStatus = "DRAFT" | "PUBLISHED" | "SUPERSEDED";
export type FileRuleType = "MIME" | "SOURCE";

export interface PolicySummaryDto {
  id: string;
  name: string;
  policy_type: PolicyType;
  description: string | null;
  current_version_id: string | null;
  current_version_number: number | null;
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
}
