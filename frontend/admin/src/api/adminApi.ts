import { api } from "./client";

// URLSearchParams(obj) stringifies `undefined` values as the literal text
// "undefined" — a real bug caught during live browser testing (a request
// went out as "?status_filter=undefined"). This drops undefined entries
// before building the query string.
function queryString(params: Record<string, string | number | undefined>): string {
  const entries = Object.entries(params).filter(([, v]) => v !== undefined) as [string, string | number][];
  if (entries.length === 0) return "";
  const qs = new URLSearchParams(entries.map(([k, v]) => [k, String(v)])).toString();
  return qs ? `?${qs}` : "";
}
import type {
  AdminSessionDto,
  AdminSessionListDto,
  BrowserNodeDto,
  DashboardRange,
  DashboardResponseDto,
  EnrollResponse,
  FirstRunAdminRequest,
  FirstRunAdminResponse,
  FirstRunMfaConfirmResponse,
  FirstRunStatusResponse,
  GroupSummaryDto,
  GroupOverviewResponseDto,
  GroupDetailDto,
  IncidentDto,
  LdapConfigDto,
  LdapConfigUpdateRequest,
  LdapTestRequest,
  LdapTestResponseDto,
  LockoutStatusDto,
  NodeHistoryPointDto,
  PolicyDetailDto,
  PolicyListResponseDto,
  RevokeSessionsResponseDto,
  PolicySummaryDto,
  QuarantineFileDto,
  Role,
  SecurityEventDto,
  SessionStatus,
  SetupConfirmResponse,
  SystemHealthDto,
  UserSummaryDto,
  UserListResponseDto,
  WorkerOverviewDto,
} from "@shared/api/types";

// Only endpoints that actually exist on the Admin listener (section 48) —
// verified against a running `OPENRBI_LISTENER_MODE=admin` instance's own
// OpenAPI schema. No fallback to a user-only endpoint if one is ever
// "convenient" — if the Admin Portal needs a shared endpoint, it must be
// registered in the Admin listener (mfa* below is: app/api/mfa.py is a
// shared router, registered in every mode).
export const adminApi = {
  // Users
  listUsers: (params?: { search?: string; role?: string; group_id?: string; status?: string; auth_source?: string; mfa?: string; sort_by?: string; sort_dir?: string; offset?: number; limit?: number }) =>
    api.get<UserListResponseDto>(`/admin/users${queryString(params ?? {})}`),
  getUser: (id: string) => api.get<UserSummaryDto>(`/admin/users/${id}`),
  createUser: (payload: { username: string; password: string; role: Role; group_ids: string[] }) =>
    api.post<UserSummaryDto>("/admin/users", payload),
  enableUser: (id: string) => api.post<UserSummaryDto>(`/admin/users/${id}/enable`),
  disableUser: (id: string) => api.post<UserSummaryDto>(`/admin/users/${id}/disable`),
  resetPassword: (id: string, newPassword: string) =>
    api.post<{ status: string }>(`/admin/users/${id}/reset-password`, { new_password: newPassword }),
  updateRole: (id: string, role: Role) => api.put<UserSummaryDto>(`/admin/users/${id}/role`, { role }),
  updateGroups: (id: string, groupIds: string[]) =>
    api.put<UserSummaryDto>(`/admin/users/${id}/groups`, { group_ids: groupIds }),
  userSessions: (id: string) => api.get<AdminSessionDto[]>(`/admin/users/${id}/sessions`),
  revokeUserSessions: (id: string) => api.post<RevokeSessionsResponseDto>(`/admin/users/${id}/sessions/revoke`),
  getLockoutStatus: (id: string) => api.get<LockoutStatusDto>(`/admin/users/${id}/lockout`),
  lockAccount: (id: string) => api.post<LockoutStatusDto>(`/admin/users/${id}/lock`),
  unlockAccount: (id: string) => api.post<LockoutStatusDto>(`/admin/users/${id}/unlock`),

  // Groups
  listGroups: () => api.get<GroupSummaryDto[]>("/admin/groups"),
  getGroupsOverview: (params?: { search?: string; policy_id?: string; sort_by?: string; sort_dir?: string; offset?: number; limit?: number }) =>
    api.get<GroupOverviewResponseDto>(`/admin/groups-overview${queryString(params ?? {})}`),
  createGroup: (name: string, description: string | null) =>
    api.post<GroupSummaryDto>("/admin/groups", { name, description }),
  deleteGroup: (id: string) => api.delete<void>(`/admin/groups/${id}`),
  getGroup: (id: string) => api.get<GroupDetailDto>(`/admin/groups/${id}`),
  addGroupMember: (groupId: string, userId: string) => api.post<void>(`/admin/groups/${groupId}/members/${userId}`),
  removeGroupMember: (groupId: string, userId: string) => api.delete<void>(`/admin/groups/${groupId}/members/${userId}`),

  // Sessions
  listSessions: (params?: { search?: string; session_status?: string; worker_id?: string; since?: string; sort_by?: string; sort_dir?: string; offset?: number; limit?: number }) =>
    api.get<AdminSessionListDto>(`/admin/sessions${queryString(params ?? {})}`),
  getSession: (id: string) => api.get<AdminSessionDto>(`/admin/sessions/${id}`),
  disconnectSession: (id: string) => api.post<AdminSessionDto>(`/admin/sessions/${id}/disconnect`),
  isolateSession: (id: string) => api.post<AdminSessionDto>(`/admin/sessions/${id}/isolate`),
  restoreSession: (id: string) => api.post<AdminSessionDto>(`/admin/sessions/${id}/restore`),
  killSession: (id: string) => api.post<AdminSessionDto>(`/admin/sessions/${id}/kill`),

  // Policies
  listPolicies: (params?: { search?: string; policy_type?: string; status_filter?: string; usage?: string; sort_by?: string; sort_dir?: string; offset?: number; limit?: number }) => api.get<PolicyListResponseDto>(`/admin/policies${queryString(params ?? {})}`),
  getPolicy: (id: string) => api.get<PolicyDetailDto>(`/admin/policies/${id}`),
  createPolicy: (name: string, policyType: string, description?: string) =>
    api.post<PolicySummaryDto>("/admin/policies", { name, policy_type: policyType, description: description || null }),
  updatePolicy: (policyId: string, name: string, description?: string) =>
    api.put<PolicySummaryDto>(`/admin/policies/${policyId}`, { name, description: description || null }),
  createVersion: (
    policyId: string,
    payload: { content: Record<string, unknown>; file_rules: { rule_type: string; match_pattern: string; action: string; priority: number }[] },
  ) => api.post(`/admin/policies/${policyId}/versions`, payload),
  updateVersion: (
    policyId: string,
    versionId: string,
    payload: { content: Record<string, unknown>; file_rules: { rule_type: string; match_pattern: string; action: string; priority: number }[] },
  ) => api.put(`/admin/policies/${policyId}/versions/${versionId}`, payload),
  publishVersion: (policyId: string, versionId: string) =>
    api.post<PolicyDetailDto>(`/admin/policies/${policyId}/versions/${versionId}/publish`),
  rollback: (policyId: string, versionId: string) =>
    api.post<PolicySummaryDto>(`/admin/policies/${policyId}/rollback`, { version_id: versionId }),
  attachToGroup: (policyId: string, groupId: string) => api.post<void>(`/admin/policies/${policyId}/groups/${groupId}`),
  detachFromGroup: (policyId: string, groupId: string) => api.delete<void>(`/admin/policies/${policyId}/groups/${groupId}`),

  // Quarantine
  listQuarantine: (statusFilter?: string) =>
    api.get<QuarantineFileDto[]>(`/admin/quarantine${statusFilter ? `?status_filter=${statusFilter}` : ""}`),
  getQuarantineFile: (id: string) => api.get<QuarantineFileDto>(`/admin/quarantine/${id}`),
  releaseFile: (id: string, comment: string) => api.post<QuarantineFileDto>(`/admin/quarantine/${id}/release`, { comment }),
  rejectFile: (id: string, comment: string) => api.post<QuarantineFileDto>(`/admin/quarantine/${id}/reject`, { comment }),

  // Incidents
  listIncidents: (params?: { status_filter?: string; severity_filter?: string }) =>
    api.get<IncidentDto[]>(`/admin/incidents${queryString(params ?? {})}`),
  getIncident: (id: string) => api.get<IncidentDto>(`/admin/incidents/${id}`),
  updateIncident: (id: string, payload: { status?: string; assigned_to?: string; resolution?: string }) =>
    api.put<IncidentDto>(`/admin/incidents/${id}`, payload),

  // Audit
  listSecurityEvents: (params?: { event_type?: string; user_id?: string; session_id?: string; limit?: number; offset?: number }) =>
    api.get<SecurityEventDto[]>(`/admin/security-events${queryString(params ?? {})}`),

  // Health
  getHealth: () => api.get<SystemHealthDto>("/admin/health"),

  // Nodes (Workers)
  listNodes: () => api.get<BrowserNodeDto[]>("/admin/nodes"),
  getWorkersOverview: (params?: { search?: string; health?: string; node_status?: string; sort_by?: string; sort_dir?: string; offset?: number; limit?: number }) => api.get<WorkerOverviewDto>(`/admin/nodes/overview${queryString(params ?? {})}`),
  getNode: (id: string) => api.get<BrowserNodeDto>(`/admin/nodes/${id}`),
  getNodeMetrics: (id: string, range: DashboardRange) =>
    api.get<NodeHistoryPointDto[]>(`/admin/nodes/${id}/metrics?range=${range}`),
  drainNode: (id: string) => api.post<BrowserNodeDto>(`/admin/nodes/${id}/drain`),
  undrainNode: (id: string) => api.post<BrowserNodeDto>(`/admin/nodes/${id}/undrain`),
  maintenanceNode: (id: string) => api.post<BrowserNodeDto>(`/admin/nodes/${id}/maintenance`),
  unmaintenanceNode: (id: string) => api.post<BrowserNodeDto>(`/admin/nodes/${id}/unmaintenance`),

  // Operations dashboard (app/api/admin_dashboard.py — B1.10.2)
  getDashboard: (range: DashboardRange) => api.get<DashboardResponseDto>(`/admin/dashboard?range=${range}`),

  // LDAP configuration (app/api/admin_ldap.py — B1.8)
  getLdapConfig: () => api.get<LdapConfigDto>("/admin/ldap/config"),
  updateLdapConfig: (payload: LdapConfigUpdateRequest) => api.put<LdapConfigDto>("/admin/ldap/config", payload),
  testLdapConfig: (payload: LdapTestRequest) => api.post<LdapTestResponseDto>("/admin/ldap/test", payload),

  // First-run bootstrap (app/api/setup.py — B1.9). Deliberately
  // unauthenticated on the backend side; this client sends no cookie logic
  // of its own beyond the ApiClient's default credentials:"include".
  firstRunStatus: () => api.get<FirstRunStatusResponse>("/setup/status"),
  firstRunCreateAdmin: (payload: FirstRunAdminRequest) => api.post<FirstRunAdminResponse>("/setup/admin", payload),
  firstRunMfaConfirm: (mfaToken: string, code: string) =>
    api.post<FirstRunMfaConfirmResponse>("/setup/mfa/confirm", { mfa_token: mfaToken, code }),

  // Shared MFA (app/api/mfa.py — registered in every listener mode)
  mfaSetupEnroll: (mfaToken: string) => api.post<EnrollResponse>("/mfa/setup/enroll", { mfa_token: mfaToken }),
  mfaSetupConfirm: (mfaToken: string, code: string) =>
    api.post<SetupConfirmResponse>("/mfa/setup/confirm", { mfa_token: mfaToken, code }),
  mfaVerify: (mfaToken: string, code: string) => api.post("/auth/mfa/verify", { mfa_token: mfaToken, code }),
  // Admin-only MFA (app/api/admin_mfa.py)
  resetUserMfa: (userId: string) => api.post<{ status: string }>(`/mfa/admin/users/${userId}/reset`),
};

export type { SessionStatus };
